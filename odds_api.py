"""Real bookmaker prices from The Odds API (free plan, about 500 requests a month).

What it gives: match result (home / draw / away) and total goals over/under from
UK bookmakers, for every league on the site. Both teams to score and player
bets cost far more requests per game on this plan, so they are left out.

Budget: each league costs 2 requests (2 markets x 1 region). A league is fetched
only when it has a game in the next 48 hours, and at most once every FRESH_HOURS
hours; the prices are kept in cache/odds_api.json. Nothing is fetched once fewer
than KEEP requests are left this month.

The key comes from the ODDS_API_KEY environment variable (a GitHub secret) and
is never printed or saved. Replies are read as data only.

For each game we keep the best price on offer for each outcome and which
bookmaker has it, plus how many bookmakers priced the game.
"""
import datetime as dt
import difflib
import json
import os
import pathlib
import re
import unicodedata

import requests

HERE = pathlib.Path(__file__).parent
CACHE = HERE / "cache" / "odds_api.json"
BASE = "https://api.the-odds-api.com/v4/sports/"
FRESH_HOURS = 20
KEEP = 25
SPORT = {"E0": "soccer_epl", "E1": "soccer_efl_champ", "I1": "soccer_italy_serie_a", "I2": "soccer_italy_serie_b",
         "SP1": "soccer_spain_la_liga", "F1": "soccer_france_ligue_one", "D1": "soccer_germany_bundesliga",
         "SC0": "soccer_spl", "UCL": "soccer_uefa_champs_league", "UEL": "soccer_uefa_europa_league",
         "UECL": "soccer_uefa_europa_conference_league"}
MIN_BOOKS = 3        # a best price needs at least this many bookmakers on the game (no stale one-offs)


def _load():
    try:
        return json.loads(CACHE.read_text(encoding="utf-8"))
    except Exception:
        return {"leagues": {}, "remaining": None}


def _get(sport, key):
    r = requests.get(BASE + sport + "/odds", timeout=30, allow_redirects=False,
                     params={"apiKey": key, "regions": "uk", "markets": "h2h,totals", "oddsFormat": "decimal"})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}")          # never the URL: it holds the key
    if len(r.content) > 5_000_000:
        raise RuntimeError("reply far bigger than expected")
    rem = r.headers.get("x-requests-remaining")
    return r.json(), (int(float(rem)) if rem not in (None, "") else None)


def _slim(events):
    """Only what the page needs from each game: best price per outcome, and from whom."""
    out = []
    for ev in events if isinstance(events, list) else []:
        best, books = {}, 0
        for b in ev.get("bookmakers") or []:
            books += 1
            for mk in b.get("markets") or []:
                for o in mk.get("outcomes") or []:
                    try:
                        price = float(o["price"])
                    except (KeyError, TypeError, ValueError):
                        continue
                    if mk.get("key") == "h2h":
                        k = "D" if o.get("name") == "Draw" else "H" if o.get("name") == ev.get("home_team") else \
                            "A" if o.get("name") == ev.get("away_team") else None
                    elif mk.get("key") == "totals" and o.get("point") is not None:
                        k = f"{str(o.get('name', '')).lower()}_{float(o['point'])}"
                    else:
                        k = None
                    if k and (k not in best or price > best[k][0]):
                        best[k] = [price, str(b.get("title", ""))[:30]]
        out.append({"home": ev.get("home_team"), "away": ev.get("away_team"), "time": ev.get("commence_time"),
                    "books": books, "best": best})
    return out


def update(matches):
    """Fetch the leagues with a game in the next 48 hours whose prices are older than FRESH_HOURS."""
    data = _load()
    key = (os.environ.get("ODDS_API_KEY") or "").strip()
    if not key:
        print("Bookmaker prices: no ODDS_API_KEY, using saved prices only")
        return data
    now = dt.datetime.now(dt.timezone.utc)
    soon = (now + dt.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M")
    today = now.strftime("%Y-%m-%d")
    codes = sorted({m["code"] for m in matches if m.get("code") in SPORT and today <= m["kickoff"] <= soon})
    for code in codes:
        old = data["leagues"].get(code, {}).get("fetched")
        if old and now - dt.datetime.fromisoformat(old) < dt.timedelta(hours=FRESH_HOURS):
            continue
        if data.get("remaining") is not None and data["remaining"] < KEEP:
            print(f"Bookmaker prices: only {data['remaining']} requests left this month, keeping saved prices")
            break
        try:
            events, rem = _get(SPORT[code], key)
        except Exception as e:
            print(f"Bookmaker prices: {code} skipped ({str(e)[:80].replace(key, '***')})")
            continue
        data["leagues"][code] = {"fetched": now.isoformat(timespec="minutes"), "events": _slim(events)}
        if rem is not None:
            data["remaining"] = rem
        print(f"Bookmaker prices: {code} {len(data['leagues'][code]['events'])} games, {rem} requests left")
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(data, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
    return data


# ------------------------------------------------------------------ matching games by team names
WORDS = {"fc", "cf", "afc", "sc", "ac", "as", "ss", "us", "sv", "vfb", "vfl", "fsv", "tsg", "rc", "rcd", "cd", "ud",
         "sd", "ca", "club", "de", "the", "calcio", "1", "04", "05", "1899", "1846", "1907", "1913", "1919", "aj"}
SHORT = {"man": "manchester", "utd": "united", "ath": "athletic", "nott'm": "nottingham", "nottm": "nottingham",
         "wolves": "wolverhampton", "sheffield weds": "sheffield wednesday", "qpr": "queens park rangers",
         "psg": "paris saint germain", "paris sg": "paris saint germain", "inter": "internazionale",
         "espanol": "espanyol", "sociedad": "real sociedad", "betis": "real betis", "m'gladbach": "monchengladbach",
         "ein frankfurt": "eintracht frankfurt", "leverkusen": "bayer leverkusen", "la coruna": "deportivo la coruna"}


def _norm(name):
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = SHORT.get(s, s)
    s = " ".join(SHORT.get(w, w) for w in re.split(r"[\s\-\.]+", s))
    return " ".join(w for w in s.split() if w not in WORDS)


def _sim(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b or a in b or b in a:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def attach(matches, data):
    """m["book"] = best prices for each game that could be matched (same league, kick-off within a day)."""
    n = 0
    for m in matches:
        evs = (data.get("leagues", {}).get(m.get("code")) or {}).get("events") or []
        best, score = None, 0.0
        for ev in evs:
            if not ev.get("time") or abs((dt.date.fromisoformat(ev["time"][:10]) - dt.date.fromisoformat(m["iso"])).days) > 1:
                continue
            s = max(_sim(m["home"], ev["home"]), _sim(m.get("espn_home"), ev["home"])) + \
                max(_sim(m["away"], ev["away"]), _sim(m.get("espn_away"), ev["away"]))
            if s > score:
                best, score = ev, s
        if best and score >= 1.5 and best["books"] >= MIN_BOOKS:
            m["book"] = {"best": best["best"], "books": best["books"]}
            n += 1
    if matches:
        print(f"Bookmaker prices matched to {n} of {len(matches)} games")
