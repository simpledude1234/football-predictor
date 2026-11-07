"""Live picks in the track record.

The Live tab works its picks out in the visitor's browser, so the server never
sees them. Instead, once a game is over, it is replayed: ESPN's minute-by-minute
commentary is used to rebuild the score and stats at 45' and 60', the page's own
live model (live_model.js, run with node) gives its picks from exactly that
moment, and each pick is marked right or wrong against the final stats.
Only what had happened by that minute is used, so the picks are the ones the
Live tab would have shown then.

A stat whose commentary count differs from ESPN's final total by more than 2 is
left out for that game (the commentary missed events, so the state is wrong).
"""
import datetime as dt
import json
import pathlib
import subprocess
import sys
from zoneinfo import ZoneInfo

import espn
import record
import tips

HERE = pathlib.Path(__file__).parent
sys.path.insert(0, str(HERE / "tools"))
import fetch_events  # noqa: E402
import live_backtest_data as LB  # noqa: E402

MINUTES = (45, 60)
PER_RUN = 120            # games replayed per build (the first runs catch up on older games)
STAT_OF = {"total_shots": "shots", "total_sot": "sot", "home_sot": "sot", "away_sot": "sot",
           "home_cards": "cards", "away_cards": "cards", "total_cards": "cards",
           "home_fouls": "fouls", "away_fouls": "fouls"}
BOX = {"shots": "totalShots", "sot": "shotsOnTarget", "fouls": "foulsCommitted"}


def _state(snap, at):
    if at == 45:
        return {"state": "in", "status": "STATUS_HALFTIME", "period": 1, "clock": 45, **snap}
    return {"state": "in", "status": "STATUS_SECOND_HALF", "period": 2, "clock": at, **snap}


def _ok(rows, em):
    """Which stats the commentary counted properly (within 2 of the final totals)."""
    full = LB.snapshot(rows, 999)
    st = em.get("stats") or {}
    ok = {"goals": all(full[h]["goals"] == em["score"][h] for h in ("home", "away"))}
    for k in ("shots", "sot", "fouls", "cards"):
        try:
            ok[k] = all(abs((full[h]["yellow"] + full[h]["red"] if k == "cards" else full[h][k]) -
                            ((st[h]["yellowCards"] or 0) + (st[h]["redCards"] or 0) if k == "cards" else st[h][BOX[k]]))
                        <= 2 for h in ("home", "away"))
        except (KeyError, TypeError):
            ok[k] = False
    return ok


def update(cache, limit=PER_RUN):
    log = record.load()
    matches = cache.get("matches", {})
    now = dt.datetime.now(ZoneInfo("Europe/London")) - dt.timedelta(hours=3)
    todo = [(mid, e) for mid, e in log.items()
            if e.get("pre") and e.get("espn_id") and "live" not in e and str(e["espn_id"]) in matches
            and e["kickoff"] <= now.strftime("%Y-%m-%d %H:%M")]
    todo.sort(key=lambda x: x[1]["kickoff"], reverse=True)
    jobs, info = [], {}
    for mid, e in todo[:limit]:
        em = matches[str(e["espn_id"])]
        try:
            s = espn.get_json(f"{espn.BASE}{em['slug']}/summary?event={em['id']}")
        except Exception as ex:
            print(f"Live replay {em['id']}: failed ({ex})")
            continue
        rows, _ = fetch_events.commentary_rows(s)
        rows = LB.dedupe([r for r in rows if r[0] in (1, 2)])
        if len(rows) < 20:            # no usable commentary for this game
            log[mid]["live"] = []
            continue
        info[mid] = (e, em, _ok(rows, em))
        for at in MINUTES:
            jobs.append({"id": mid, "at": at, "m": e["pre"], "L": _state(LB.snapshot(rows, float(at)), at)})
    if jobs:
        r = subprocess.run(["node", str(HERE / "tools" / "live_run.js")], input=json.dumps(jobs),
                           capture_output=True, text=True, timeout=300, check=True)
        for res in json.loads(r.stdout):
            e, em, ok = info[res["id"]]
            act = record._actuals_from_espn(em)
            out = log[res["id"]].setdefault("live", [])
            for p in res["list"]:
                k = p["key"]
                if k in ("result", "btts"):
                    if not ok["goals"]:
                        continue
                    hit = act[k] == p["side"]
                    pick = ({"H": f"{e['home']} to win", "A": f"{e['away']} to win", "D": "Draw"}[p["side"]]
                            if k == "result" else p["side"].title())
                    market = "Match result" if k == "result" else "Both teams to score"
                else:
                    if not ok.get(STAT_OF.get(k), False) or act.get(k) is None:
                        continue
                    hit = act[k] > p["line"] if p["pick"] == "over" else act[k] < p["line"]
                    pick = f"{p['pick'].title()} {p['line']}"
                    market = tips.GENERIC[k]
                out.append({"at": res["at"], "key": k, "market": market, "pick": pick,
                            "chance": p["chance"], "hit": bool(hit)})
        for mid in info:
            log[mid].setdefault("live", [])
    record.save(log)
    print(f"Live picks replayed for {len(info)} finished games")
