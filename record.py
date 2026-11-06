"""Track record: save every tip before kick-off, then mark it right or wrong.

tips_log.json holds one entry per match with the tips exactly as shown on the
page. A match's tips can change until kick-off; after that they are frozen.
"""
import datetime as dt
import json
import pathlib
from zoneinfo import ZoneInfo

import pandas as pd

import predictor as P
from fetch_data import LEAGUES

LOG = pathlib.Path(__file__).parent / "tips_log.json"
UK = ZoneInfo("Europe/London")


def load():
    return json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {}


def _plain(o):
    """numpy numbers/booleans -> plain Python values."""
    return o.item() if hasattr(o, "item") else str(o)


def save(log):
    tmp = LOG.with_suffix(".tmp")
    tmp.write_text(json.dumps(log, indent=0, ensure_ascii=False, default=_plain), encoding="utf-8")
    tmp.replace(LOG)


def update(matches):
    log = load()
    now = dt.datetime.now(UK).strftime("%Y-%m-%d %H:%M")
    for m in matches:
        mid = f"{m['code']}|{m['iso']}|{m['home']}|{m['away']}"
        if mid in log and log[mid]["kickoff"] <= now:
            continue                                   # kicked off: never rewrite
        if m["kickoff"] <= now:
            continue
        log[mid] = {"code": m["code"], "league": m["league"], "date": m["iso"], "kickoff": m["kickoff"],
                    "home": m["home"], "away": m["away"], "espn_id": m.get("espn_id"), "tips": m["tips"]}
    save(log)
    return log


def add_replay(matches):
    """Store replayed past games (predicted with only earlier data). Never overwrites live tips."""
    log = load()
    for m in matches:
        mid = f"{m['code']}|{m['iso']}|{m['home']}|{m['away']}"
        if mid not in log:
            log[mid] = {"code": m["code"], "league": m["league"], "date": m["iso"], "kickoff": m["kickoff"],
                        "home": m["home"], "away": m["away"], "espn_id": m.get("espn_id"), "tips": m["tips"],
                        "replay": True}
    save(log)


def _actuals_from_fd(r):
    v = P.actual_values(r)
    v["result"] = r.FTR
    v["btts"] = "yes" if (r.FTHG > 0 and r.FTAG > 0) else "no"
    v["score"] = f"{int(r.FTHG)}-{int(r.FTAG)}"
    return v


def _actuals_from_espn(e):
    s = e.get("stats") or {}
    hs, as_ = s.get("home") or {}, s.get("away") or {}
    def g(d, k):
        return d.get(k)
    v = {}
    try:
        v.update({"total_shots": g(hs, "totalShots") + g(as_, "totalShots"),
                  "total_sot": g(hs, "shotsOnTarget") + g(as_, "shotsOnTarget"),
                  "home_sot": g(hs, "shotsOnTarget"), "away_sot": g(as_, "shotsOnTarget"),
                  "home_fouls": g(hs, "foulsCommitted"), "away_fouls": g(as_, "foulsCommitted")})
        hc = (g(hs, "yellowCards") or 0) + (g(hs, "redCards") or 0)
        ac = (g(as_, "yellowCards") or 0) + (g(as_, "redCards") or 0)
        v.update({"home_cards": hc, "away_cards": ac, "total_cards": hc + ac})
    except TypeError:
        pass
    v.update(_offsides_from_espn(e))
    h, a = e["score"]["home"], e["score"]["away"]
    v.update({"result": "H" if h > a else "A" if a > h else "D", "btts": "yes" if h and a else "no",
              "score": f"{h}-{a}"})
    return v


def _offsides_from_espn(e):
    s = e.get("stats") or {}
    hs, as_ = s.get("home") or {}, s.get("away") or {}
    ho, ao, hf, af = hs.get("offsides"), as_.get("offsides"), hs.get("foulsCommitted"), as_.get("foulsCommitted")
    if ho is None or ao is None:
        return {}
    v = {"home_offsides": ho, "away_offsides": ao, "total_offsides": ho + ao}
    if hf is not None and af is not None:
        v["free_kicks"] = hf + af + ho + ao        # free kicks = fouls + offsides
    return v


def score(espn_cache):
    """Every finished match with each tip marked right (True), wrong (False) or not checkable (None)."""
    log = load()
    fd = {}
    for code in {e["code"] for e in log.values() if e["code"] in LEAGUES}:
        df = P.load_league(code)
        df["iso"] = df.Date.dt.strftime("%Y-%m-%d")
        fd[code] = {(r.iso, r.HomeTeam, r.AwayTeam): r for r in df.itertuples()}
    espn_m = espn_cache.get("matches", {})
    now = dt.datetime.now(UK).strftime("%Y-%m-%d %H:%M")
    games, waiting = [], 0
    for mid, e in log.items():
        if e["kickoff"] > now:
            continue
        act, booked = None, None
        r = fd.get(e["code"], {}).get((e["date"], e["home"], e["away"]))
        em = espn_m.get(str(e.get("espn_id"))) if e.get("espn_id") else None
        if r is not None:
            act = _actuals_from_fd(r)
            if em:
                act.update(_offsides_from_espn(em))
        elif em:
            act = _actuals_from_espn(em)
        if em:
            booked = {(n, s) for n, s, st, y, rd, f in em["players"] if y + rd > 0}
            played = {(n, s) for n, s, *_ in em["players"]}
        if act is None:
            waiting += 1
            continue
        rows = []
        for t in e["tips"]:
            if t.get("skip"):          # "No tip" markets are not scored
                continue
            k, hit, shown = t["key"], None, "–"
            if k == "player_booked":
                if booked is not None:
                    who = (t["player"], t["team"])
                    if who in played:
                        hit = who in booked
                        shown = "booked" if hit else "not booked"
                    else:
                        shown = "did not play"
            elif k in ("result", "btts"):
                hit = act[k] == t["side"]
                shown = {"H": "home win", "D": "draw", "A": "away win"}.get(act[k], act[k]) if k == "result" else act[k]
                shown = shown.title() if k == "btts" else shown
            elif act.get(k) is not None:
                val = float(act[k])
                hit = val > t["line"] if t["side"] == "over" else val < t["line"]
                shown = f"{val:g}"
            rows.append({"label": t["label"], "market": t["market"], "pick": t["pick"], "actual": shown,
                         "hit": hit, "star": t.get("star", False)})
        games.append({"league": e["league"], "date": e["date"], "kickoff": e["kickoff"], "home": e["home"],
                      "away": e["away"], "score": act.get("score", ""), "tips": rows, "replay": e.get("replay", False)})
    games.sort(key=lambda g: g["kickoff"], reverse=True)
    summary = {}
    for g in games:
        for t in g["tips"]:
            if t["hit"] is None:
                continue
            for key in (t["market"], "__all__") + (("__star__",) if t["star"] else ()):
                s = summary.setdefault(key, [0, 0])
                s[0] += t["hit"]
                s[1] += 1
    return {"games": games, "summary": summary, "waiting": waiting}
