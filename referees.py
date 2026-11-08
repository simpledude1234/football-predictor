"""Referee names for Serie A, LaLiga, Bundesliga and Ligue 1.

Our main data (football-data.co.uk) names the referee only for English and
Scottish games. This fills the gap from football-data.org's free plan, so the
booking predictions can use each referee's record in these leagues too.

The key is read from the FOOTBALL_DATA_KEY setting (GitHub Secret) or, on this
PC, from the file .football_data_key (never committed). With no key, nothing
changes. Past seasons are saved in cache/referees_fd.json, so each run only asks
for the current season (4 requests; the free plan allows 10 a minute).
Only api.football-data.org is contacted, and only names and dates are kept.
"""
import datetime as dt
import json
import os
import pathlib
import time
from collections import Counter, defaultdict

import requests

HERE = pathlib.Path(__file__).parent
CACHE = HERE / "cache" / "referees_fd.json"
KEY_FILE = HERE / ".football_data_key"
API = "https://api.football-data.org/v4/competitions/{}/matches"
COMPS = {"I1": "SA", "SP1": "PD", "D1": "BL1", "F1": "FL1"}   # our league code -> theirs
PAST = 4                                                        # past seasons kept
_MAPS = {}
ON = True                                                       # tested 2026-11-08: better booking predictions in all 4 leagues


def _key():
    k = os.environ.get("FOOTBALL_DATA_KEY", "").strip()
    if not k and KEY_FILE.exists():
        k = KEY_FILE.read_text(encoding="utf-8").strip()
    return k if k.isalnum() and 20 <= len(k) <= 64 else ""


def _season_now():
    t = dt.date.today()
    return t.year if t.month >= 7 else t.year - 1


def _fetch(comp, season, key):
    r = requests.get(API.format(comp), params={"season": season}, timeout=30,
                     headers={"X-Auth-Token": key}, allow_redirects=False)
    if r.status_code == 429:                       # over the limit: wait a minute, try once more
        time.sleep(65)
        r = requests.get(API.format(comp), params={"season": season}, timeout=30,
                         headers={"X-Auth-Token": key}, allow_redirects=False)
    if r.status_code != 200 or len(r.content) > 5_000_000:
        print(f"  referees: {comp} {season} not available ({r.status_code})")
        return None
    out = []
    for m in r.json().get("matches", []):
        refs = [x.get("name") for x in (m.get("referees") or []) if x.get("type") == "REFEREE" and x.get("name")]
        h, a = (m.get("homeTeam") or {}).get("name"), (m.get("awayTeam") or {}).get("name")
        if h and a and m.get("utcDate"):
            out.append([str(m["utcDate"])[:16], str(h)[:60], str(a)[:60], str(refs[0])[:60] if refs else ""])
    return out


def update():
    """Download what is missing (past seasons once, the current season every time)."""
    key = _key()
    if not key:
        return
    store = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    now, calls = _season_now(), 0
    for comp in COMPS.values():
        for season in range(now - PAST, now + 1):
            s = str(season)
            if season != now and s in store.get(comp, {}):
                continue
            if calls:
                time.sleep(6.5)                   # stay under 10 requests a minute
            rows = _fetch(comp, season, key)
            calls += 1
            if rows is not None:
                store.setdefault(comp, {})[s] = rows
            elif season != now:
                store.setdefault(comp, {})[s] = []   # not in the free plan: don't ask again
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(store, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"  referees: {calls} requests, {sum(len(v) for c in store.values() for v in c.values())} matches saved")


def _games(code):
    store = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    rows = [r for v in store.get(COMPS.get(code, ""), {}).values() for r in v]
    return [(dt.datetime.strptime(r[0], "%Y-%m-%dT%H:%M").date(), r[1], r[2], r[3]) for r in rows]


def _name_map(games, dates, homes, aways):
    """Their team names -> ours: each of our names goes to the name it most often
    lines up with in the same home/away slot within a day (the two lists use
    different spellings, e.g. 'Inter' and 'FC Internazionale Milano')."""
    by_day = defaultdict(list)
    for g in games:
        by_day[g[0]].append(g)
    votes = defaultdict(Counter)
    for d, h, a in zip(dates, homes, aways):
        for k in (-1, 0, 1):
            for g in by_day.get(d + dt.timedelta(days=k), ()):
                votes[h][g[1]] += 1
                votes[a][g[2]] += 1
    out = {}
    for ours, c in votes.items():
        (best, n), = c.most_common(1)
        if n >= 3:
            out[ours] = best
    return out


def fill(df, code, cols=("Date", "HomeTeam", "AwayTeam")):
    """Fill empty referee names in a league table (past games or fixtures) in place."""
    games = _games(code) if ON else []
    if not games or df.empty:
        return df
    if "Referee" not in df:
        df["Referee"] = None
    dates = [x.date() if hasattr(x, "date") else x for x in df[cols[0]]]
    names = _name_map(games, dates, list(df[cols[1]]), list(df[cols[2]]))
    if len(df) >= 100:
        _MAPS[code] = names                       # learnt from past games, reused for fixtures
    else:
        names = {**names, **_MAPS.get(code, {})}
    look = {}
    for d, h, a, ref in games:
        if ref:
            for k in (-1, 0, 1):
                look.setdefault((d + dt.timedelta(days=k), h, a), ref)
    refs = df["Referee"].astype(object).tolist()
    for i, (d, h, a) in enumerate(zip(dates, df[cols[1]], df[cols[2]])):
        if isinstance(refs[i], str) and refs[i].strip():
            continue
        r = look.get((d, names.get(h), names.get(a)))
        if r:
            refs[i] = r
    df["Referee"] = refs
    return df


if __name__ == "__main__":
    update()
