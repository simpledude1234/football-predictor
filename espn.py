"""ESPN's free public football feed: fixtures, odds, results and who was booked.

Finished matches are kept in a small local store (cache/espn_matches.json) so
each is downloaded only once. Only the few fields we need are stored.
"""
import datetime as dt
import difflib
import json
import pathlib
import re
import time
import unicodedata

import requests

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
SLUGS = {"E0": "eng.1", "E1": "eng.2", "I1": "ita.1", "I2": "ita.2", "SP1": "esp.1", "F1": "fra.1",
         "D1": "ger.1", "SC0": "sco.1", "UCL": "uefa.champions", "UEL": "uefa.europa", "UECL": "uefa.europa.conf"}
CACHE = pathlib.Path(__file__).parent / "cache" / "espn_matches.json"
_session = requests.Session()
_session.headers["User-Agent"] = "Mozilla/5.0"


def get_json(url):
    """HTTPS to ESPN only, no redirects, size-capped; the reply is read as data, never run."""
    if not url.startswith(BASE):
        raise ValueError("blocked: unexpected address")
    r = _session.get(url, timeout=30, allow_redirects=False)
    r.raise_for_status()
    if len(r.content) > 8_000_000:
        raise ValueError("blocked: reply far bigger than expected")
    time.sleep(0.12)                     # be polite to the free feed
    return r.json()


# ---------------------------------------------------------------- team names
DROP = {"fc", "cf", "afc", "sc", "sv", "as", "ac", "cd", "ud", "rc", "sk", "fk", "kaa", "krc", "vfl", "vfb",
        "tsg", "ss", "ssc", "1.", "club", "de", "the", "calcio", "us"}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower().replace("&", "and")
    return " ".join(w for w in re.split(r"[\s\-]+", s) if w and w not in DROP)


def matcher(names, aliases=None):
    """Returns a function that maps an ESPN team name onto one of `names`."""
    aliases = {norm(k): v for k, v in (aliases or {}).items()}
    by_norm = {norm(n): n for n in names}

    def match(espn_name):
        n = norm(espn_name)
        if n in aliases and aliases[n] in names:
            return aliases[n]
        if n in by_norm:
            return by_norm[n]
        for k, v in by_norm.items():              # "Leeds United" vs "Leeds"
            if k and (n.startswith(k + " ") or k.startswith(n + " ")):
                return v
        best = difflib.get_close_matches(n, list(by_norm), n=1, cutoff=0.8)
        return by_norm[best[0]] if best else None
    return match


# ---------------------------------------------------------------- matches
def _compact(slug, ev, summary):
    """Keep only what we need from a finished match."""
    comp = ev["competitions"][0]
    side = {t["team"]["id"]: t["homeAway"] for t in comp["competitors"]}
    names = {t["homeAway"]: t["team"]["displayName"] for t in comp["competitors"]}
    score = {t["homeAway"]: int(t.get("score") or 0) for t in comp["competitors"]}
    stats = {}
    for t in summary.get("boxscore", {}).get("teams", []):
        st = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
        # every team stat ESPN gives (passes, crosses, saves, clearances...), kept for future markets
        stats[side.get(t["team"]["id"], "?")] = {k: _num(v) for k, v in st.items()}
    players = []
    for r in summary.get("rosters", []):
        ha = side.get(r["team"]["id"], "?")
        for p in r.get("roster", []):
            st = {x["name"]: x.get("value") for x in p.get("stats", [])}
            played = p.get("starter") or p.get("subbedIn")
            if not played:
                continue
            players.append([p["athlete"].get("displayName", "?"), ha, int(bool(p.get("starter"))),
                            int(st.get("yellowCards") or 0), int(st.get("redCards") or 0), int(st.get("foulsCommitted") or 0)])
    return {"id": ev["id"], "slug": slug, "date": ev["date"][:10], "home": names.get("home"), "away": names.get("away"),
            "score": score, "stats": stats, "players": players, "full": True, "pstats": player_stats(summary, side),
            "odds": match_odds(summary)}


def _dec(ml):
    """American odds -> decimal."""
    ml = float(ml)
    return 1 + (ml / 100 if ml > 0 else 100 / -ml)


def _expected_goals(ph, pa, line, p_over):
    """Each team's expected goals that best match the win chances and the goals line (simple search)."""
    import math
    def probs(lh, la):
        P = lambda k, l: math.exp(-l) * l ** k / math.factorial(k)
        h = a = over = 0.0
        for i in range(11):
            for j in range(11):
                q = P(i, lh) * P(j, la)
                h += q * (i > j)
                a += q * (j > i)
                over += q * (i + j > line)
        return h, a, over
    best = None
    for lh in [x / 10 for x in range(2, 40)]:
        for la in [x / 10 for x in range(2, 40)]:
            if abs(lh + la - (line + 0.3)) > 2.2:
                continue
            h, a, o = probs(lh, la)
            e = (h - ph) ** 2 + (a - pa) ** 2 + ((o - p_over) ** 2 if p_over is not None else 0)
            if best is None or e < best[0]:
                best = (e, lh, la)
    return [best[1], best[2]] if best else None


def match_odds(summary):
    """Closing bookmaker odds (ESPN's pick centre): win/draw/win chances and each team's expected goals."""
    try:
        pc = (summary.get("pickcenter") or [{}])[0]
        h, a = _dec(pc["homeTeamOdds"]["moneyLine"]), _dec(pc["awayTeamOdds"]["moneyLine"])
        d = _dec(pc["drawOdds"]["moneyLine"])
    except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError):
        return None
    tot = 1 / h + 1 / a + 1 / d
    ph, pd_, pa = 1 / h / tot, 1 / d / tot, 1 / a / tot
    p_over = None
    try:
        o, u = _dec(pc["overOdds"]), _dec(pc["underOdds"])
        p_over = (1 / o) / (1 / o + 1 / u)
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        pass
    line = pc.get("overUnder") or 2.5
    return {"h": round(ph, 3), "d": round(pd_, 3), "a": round(pa, 3),
            "xg": _expected_goals(ph, pa, line, p_over)}


def _group(abbr):
    """ESPN position (e.g. "CD-L", "AM", "F") -> G, D, M or F."""
    a = abbr.upper()
    if not a or a == "SUB":
        return "?"                 # substitutes: taken from the player's starts instead
    if a.startswith(("DM", "CM")):
        return "M"
    if a.startswith("G"):
        return "G"
    if a in ("F", "CF", "ST", "LF", "RF", "CF-L", "CF-R", "SS") or a.startswith("CF") or a.endswith("W"):
        return "F"
    if a.startswith(("CD", "LB", "RB", "D", "SW")) or a in ("WB", "LWB", "RWB"):
        return "D"
    return "M" if a else "?"


def player_stats(summary, side):
    """Per player: [shots, shots on target, fouls committed, fouls won, minutes, position G/D/M/F], keyed "side|name".
    Minutes come from the substitution times (90 for a full match, stoppage time ignored)."""
    off, on = {}, {}
    for k in summary.get("keyEvents", []):
        if k.get("type", {}).get("type") != "substitution":
            continue
        ps = [x.get("athlete", {}).get("displayName") for x in k.get("participants", [])]
        mins = min(90, round((k.get("clock", {}).get("value") or 0) / 60))
        if len(ps) == 2:
            on[ps[0]], off[ps[1]] = mins, mins
    out = {}
    for r in summary.get("rosters", []):
        ha = side.get(r["team"]["id"], "?")
        for p in r.get("roster", []):
            if not (p.get("starter") or p.get("subbedIn")):
                continue
            name = p["athlete"].get("displayName", "?")
            st = {x["name"]: x.get("value") for x in p.get("stats", [])}
            if p.get("starter"):
                mins = off.get(name, 90) if p.get("subbedOut") else 90
            else:
                mins = 90 - on.get(name, 75)
                if p.get("subbedOut"):
                    mins = max(1, off.get(name, 90) - on.get(name, 75))
            out[f"{ha}|{name}"] = [int(st.get("totalShots") or 0), int(st.get("shotsOnTarget") or 0),
                                   int(st.get("foulsCommitted") or 0), int(st.get("foulsSuffered") or 0), max(1, mins),
                                   _group((p.get("position") or {}).get("abbreviation", ""))]
    return out


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_cache():
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    return {"matches": {}, "dates_done": {}}


def save_cache(c):
    CACHE.parent.mkdir(exist_ok=True)
    tmp = CACHE.with_suffix(".tmp")
    tmp.write_text(json.dumps(c, separators=(",", ":")), encoding="utf-8")
    tmp.replace(CACHE)


def update(days_ahead=21, season_start=None):
    """Download new finished matches and return upcoming fixtures for every competition."""
    c = load_cache()
    today = dt.date.today()
    if season_start is None:
        season_start = dt.date(today.year if today.month >= 7 else today.year - 1, 7, 1)
    upcoming = []
    for code, slug in SLUGS.items():
        try:
            cal_js = get_json(f"{BASE}{slug}/scoreboard?dates={today:%Y%m%d}")
        except Exception as e:
            print(f"ESPN {slug}: failed ({e})")
            continue
        cal = cal_js.get("leagues", [{}])[0].get("calendar", [])
        days = sorted({d[:10] for d in cal if isinstance(d, str)})
        if not days:        # European cups: calendar lists stages, not days -> check Tue/Wed/Thu
            first = dt.date(season_start.year, 9, 1)
            days = [str(first + dt.timedelta(days=i)) for i in range((today - first).days + days_ahead + 1)
                    if (first + dt.timedelta(days=i)).weekday() in (1, 2, 3)]
        done = set(c["dates_done"].get(slug, []))
        new = 0
        for d in days:
            day = dt.date.fromisoformat(d)
            if day < season_start or day > today + dt.timedelta(days=days_ahead):
                continue
            if day < today and d in done:
                continue
            try:
                js = cal_js if day == today else get_json(f"{BASE}{slug}/scoreboard?dates={day:%Y%m%d}")
            except Exception as e:
                print(f"ESPN {slug} {d}: failed ({e})")
                continue
            all_done = True
            for ev in js.get("events", []):
                st = ev["competitions"][0].get("status", ev.get("status", {})).get("type", {})
                if st.get("completed"):
                    if ev["id"] not in c["matches"]:
                        try:
                            c["matches"][ev["id"]] = _compact(slug, ev, get_json(f"{BASE}{slug}/summary?event={ev['id']}"))
                            new += 1
                        except Exception as e:
                            print(f"ESPN match {ev['id']}: failed ({e})")
                            all_done = False
                elif st.get("state") == "pre":
                    all_done = False
                    upcoming.append({"code": code, "slug": slug, "event": ev})
                else:              # in play: still linked, so the Live tab can follow it
                    all_done = False
                    upcoming.append({"code": code, "slug": slug, "event": ev, "in_play": True})
            if all_done and day < today:
                done.add(d)
        c["dates_done"][slug] = sorted(done)
        print(f"ESPN {slug}: {new} new finished matches stored")
        save_cache(c)
    backfill_extra(c)
    backfill_players(c)
    add_lineups(upcoming)
    return c, upcoming


def backfill_extra(c, limit=150):
    """Matches stored before every team stat was kept: fetch them again, a few at a time."""
    todo = [k for k, m in c["matches"].items() if m.get("stats") and not m.get("full")][:limit]
    for eid in todo:
        m = c["matches"][eid]
        try:
            s = get_json(f"{BASE}{m['slug']}/summary?event={eid}")
        except Exception as e:
            print(f"ESPN extra stats {eid}: failed ({e})")
            continue
        side = {}
        for r in s.get("header", {}).get("competitions", [{}])[0].get("competitors", []):
            side[r.get("team", {}).get("id") or r.get("id")] = r.get("homeAway")
        for t in s.get("boxscore", {}).get("teams", []):
            ha = side.get(t["team"]["id"])
            if ha in m["stats"]:
                st = {x["name"]: x.get("displayValue") for x in t.get("statistics", [])}
                m["stats"][ha].update({k: _num(v) for k, v in st.items()})
        m["full"] = True
    if todo:
        print(f"ESPN: all team stats added to {len(todo)} stored matches")
        save_cache(c)


def backfill_players(c, limit=150):
    """Matches stored before per-player shots, positions and closing odds were kept: fetch them again,
    a few at a time."""
    todo = [k for k, m in c["matches"].items() if "pstats" not in m or "odds" not in m][:limit]
    for eid in todo:
        m = c["matches"][eid]
        try:
            s = get_json(f"{BASE}{m['slug']}/summary?event={eid}")
        except Exception as e:
            print(f"ESPN player stats {eid}: failed ({e})")
            continue
        side = {}
        for r in s.get("header", {}).get("competitions", [{}])[0].get("competitors", []):
            side[r.get("team", {}).get("id") or r.get("id")] = r.get("homeAway")
        m["pstats"] = player_stats(s, side)
        m["odds"] = match_odds(s)
    if todo:
        print(f"ESPN: player shots and minutes added to {len(todo)} stored matches")
        save_cache(c)


def add_lineups(upcoming, hours=3):
    """Confirmed starting line-ups (ESPN shows them about an hour before kick-off)."""
    now = dt.datetime.now(dt.timezone.utc)
    found = 0
    for u in upcoming:
        ev = u["event"]
        try:
            ko = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        if not now < ko < now + dt.timedelta(hours=hours):
            continue
        try:
            s = get_json(f"{BASE}{u['slug']}/summary?event={ev['id']}")
        except Exception as e:
            print(f"ESPN line-up {ev['id']}: failed ({e})")
            continue
        side = {t["team"]["id"]: t["homeAway"] for t in ev["competitions"][0]["competitors"]}
        xi = {}
        for r in s.get("rosters", []):
            ha = side.get(r.get("team", {}).get("id"))
            names = [p["athlete"].get("displayName") for p in r.get("roster", []) if p.get("starter") and p.get("athlete")]
            if ha in ("home", "away") and len(names) == 11:
                xi[ha] = names
        if len(xi) == 2:
            u["lineup"] = xi
            found += 1
    print(f"ESPN: confirmed line-ups for {found} upcoming matches")
