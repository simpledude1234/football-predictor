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


def pre_match(m):
    """The pre-match numbers the live model starts from (to replay live picks after the game)."""
    out = {"goals_exp": m["goals_exp"],
           "markets": [{k: x.get(k) for k in ("key", "expected", "phi", "estimate")} for x in m["markets"]]}
    if m.get("squad"):                 # players' booking rates (live player picks)
        out["squad"] = m["squad"]
    if m.get("fh"):                    # players' fouls per game (live player picks)
        out["fh"] = m["fh"]
    return out


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
                    "home": m["home"], "away": m["away"], "espn_id": m.get("espn_id"), "tips": m["tips"],
                    "pre": pre_match(m)}
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
                        "replay": True, "pre": pre_match(m)}
    save(log)


def _actuals_from_fd(r):
    v = P.actual_values(r)
    v["result"] = r.FTR
    v["total_goals"] = int(r.FTHG + r.FTAG)
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
              "score": f"{h}-{a}", "total_goals": h + a})
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
    for espn_name, name in (("wonCorners", "corners"), ("totalTackles", "tackles")):
        h, a = hs.get(espn_name), as_.get(espn_name)
        if h is not None and a is not None:
            v.update({f"home_{name}": h, f"away_{name}": a, f"total_{name}": h + a})
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
        pst = None
        if em:
            booked = {(n, s) for n, s, st, y, rd, f in em["players"] if y + rd > 0}
            played = {(n, s) for n, s, *_ in em["players"]}
            pst = em.get("pstats")
        if act is None:
            waiting += 1
            continue

        def judge(t):
            """(landed True/False/None, what happened) for one tip."""
            k, hit, shown = t["key"], None, "–"
            if k.startswith("pl_"):
                if pst is not None:
                    v = pst.get(f"{t['team']}|{t['player']}")
                    if v is None:
                        shown = "did not play"           # void, as at the bookmakers
                    else:
                        n = v[("shots", "sot", "fouls", "fwon").index(t["stat"])]
                        hit, shown = n >= t["line"], str(n)
            elif k == "bet_builder":
                res = [judge(x) for x in t["legs"]]
                hits = [r[0] for r in res]
                hit = False if False in hits else None if None in hits else True
                shown = ", ".join(r[1] for r in res)
            elif k == "player_booked":
                if booked is not None:
                    who = (t["player"], t["team"])
                    if who in played:
                        hit = who in booked
                        shown = "booked" if hit else "not booked"
                    else:
                        shown = "did not play"
            elif k in ("result", "btts"):
                hit = act[k] in t["side"] if k == "result" else act[k] == t["side"]   # "HD" = home or draw
                shown = {"H": "home win", "D": "draw", "A": "away win"}.get(act[k], act[k]) if k == "result" else act[k]
                shown = shown.title() if k == "btts" else shown
            elif act.get(k) is not None:
                val = float(act[k])
                hit = val > t["line"] if t["side"] == "over" else val < t["line"]
                shown = f"{val:g}"
            return hit, shown

        rows = []
        for t in e["tips"]:
            if t.get("skip"):          # "No tip" markets are not scored
                continue
            k = t["key"]
            hit, shown = judge(t)
            row = {"label": t["label"], "market": t["market"].replace("Better price: ", "Higher price: "),
                   "pick": t["pick"], "actual": shown, "key": k, "chance": t.get("chance"),
                   "hit": hit, "star": t.get("star", False), "value": t.get("value", False),
                   "min_odds": t.get("min_odds"), "best": t.get("best"), "bv": t.get("bv", False),
                   "book_price": t.get("book_price")}
            if k == "bet_builder":
                row["legs"] = [{"pick": x["pick"] if x["key"].startswith("pl_") else f"{x['label']}: {x['pick']}",
                                "hit": judge(x)[0], "actual": judge(x)[1]} for x in t["legs"]]
            rows.append(row)
        for lp in e.get("live", []):
            rows.append({"label": f"Live {lp['at']}': {lp['market']}", "market": "Live: " + lp["market"],
                         "pick": lp["pick"], "actual": "", "key": lp["key"], "chance": lp["chance"],
                         "hit": lp["hit"], "star": False, "value": False, "live": True})
        games.append({"league": e["league"], "date": e["date"], "kickoff": e["kickoff"], "home": e["home"],
                      "away": e["away"], "score": act.get("score", ""), "tips": rows, "replay": e.get("replay", False)})
    games.sort(key=lambda g: g["kickoff"], reverse=True)
    summary = {}
    for g in games:
        for t in g["tips"]:
            if t["hit"] is None:
                continue
            keys = (t["market"], "__bv__") if t.get("bv") else (t["market"], "__value__") if t.get("value") else (t["market"],) if t.get("key") == "player_booked" else \
                (t["market"], "__pstat__") if (t.get("key") or "").startswith("pl_") else \
                (t["market"], "__bb__") if t.get("key") == "bet_builder" else \
                (t["market"], "__live__") if t.get("live") else \
                (t["market"], "__all__") + (("__star__",) if t["star"] else ())
            for key in keys:
                s = summary.setdefault(key, [0, 0])
                s[0] += t["hit"]
                s[1] += 1
    return {"games": games, "summary": summary, "waiting": waiting}
