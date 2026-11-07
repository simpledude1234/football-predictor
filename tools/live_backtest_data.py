"""Backtest helper: rebuild each past game's stats at minute 45 (half-time) and
minute 60 from ESPN's minute-by-minute commentary, and fit the "share still to
come" curves. Writes cache/live_bt_data.json for tools/live_backtest.js.

Curves are fitted on half the games (even ESPN ids) and the picks are scored
on the other half (odd ids), so the test games were never used for fitting.
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import espn  # noqa: E402

CACHE = espn.CACHE.parent
SHOT = {"Shot Off Target", "Shot Blocked", "Shot On Target", "Shot Hit Woodwork", "Goal", "Goal - Header",
        "Goal - Volley", "Goal - Free-kick", "Penalty - Scored", "Penalty - Saved", "Penalty - Missed",
        "Penalty - Hit Woodwork"}
SOT = {"Shot On Target", "Goal", "Goal - Header", "Goal - Volley", "Goal - Free-kick", "Penalty - Scored",
       "Penalty - Saved"}
GOAL = {"Goal", "Goal - Header", "Goal - Volley", "Goal - Free-kick", "Penalty - Scored", "Own Goal"}


def kinds(r):
    ty, txt = r[4], r[5]
    out = []
    if ty in SHOT:
        out.append("shots")
    if ty in SOT:
        out.append("sot")
    if ty in GOAL:
        out.append("goals")
    if ty == "Foul":           # counted once per moment, see dedupe()
        out.append("fouls")
    if ty == "Yellow Card":
        out += ["cards", "yellow"]
    if ty == "Red Card":
        out += ["cards", "red"]
    if ty == "Corner Awarded":
        out.append("corners")
    return out


def pos(r):
    """Minute of play: first-half stoppage counts as 45, second-half as 90."""
    period, sec = r[0], r[1] or 0
    if period == 1:
        return min(sec / 60, 45.0)
    return max(45.001, min(sec / 60, 90.0))


def dedupe(rows):
    """ESPN lists each foul two or three times (\"Foul by ...\", \"... wins a free kick\",
    repeats), all tagged with the fouling team. Keep one per team per moment."""
    seen, out = set(), []
    for r in rows:
        if r[4] == "Foul":
            key = (r[0], r[1], r[3])
            if key in seen:
                continue
            seen.add(key)
        out.append(r)
    return out


def snapshot(rows, upto):
    s = {h: {"goals": 0, "shots": 0, "sot": 0, "fouls": 0, "corners": 0, "yellow": 0, "red": 0} for h in ("home", "away")}
    for r in rows:
        if r[3] not in s or r[0] not in (1, 2) or pos(r) > upto:
            continue
        for k in kinds(r):
            if k != "cards":
                s[r[3]][k] += 1
    return s


def main():
    ev = json.loads((CACHE / "espn_events.json").read_text(encoding="utf-8"))
    store = espn.load_cache()["matches"]
    pre = json.loads((CACHE / "live_bt_prematch.json").read_text(encoding="utf-8"))
    curves_pos = {k: [] for k in ("shots", "sot", "fouls", "cards", "goals", "corners")}
    games, check = [], {"games": 0, "exact": {k: 0 for k in ("goals", "shots", "sot", "fouls", "cards", "corners")}}
    for eid, e in ev.items():
        m = store.get(eid)
        rows = dedupe([r for r in e["rows"] if r[0] in (1, 2)])
        if not m or not m.get("stats") or "home" not in m["stats"] or len(rows) < 20:
            continue
        full = snapshot(rows, 999)
        # how well commentary counts agree with ESPN's final totals
        check["games"] += 1
        st = m["stats"]
        for k, box in (("goals", lambda h: m["score"][h]), ("shots", lambda h: st[h]["totalShots"]),
                       ("sot", lambda h: st[h]["shotsOnTarget"]), ("fouls", lambda h: st[h]["foulsCommitted"]),
                       ("cards", lambda h: (st[h]["yellowCards"] or 0) + (st[h]["redCards"] or 0)),
                       ("corners", lambda h: st[h].get("wonCorners"))):
            got = [full[h]["yellow"] + full[h]["red"] if k == "cards" else full[h][k] for h in ("home", "away")]
            if got == [box("home"), box("away")]:
                check["exact"][k] += 1
        # games whose commentary is patchy for a stat are left out for that stat
        ok = {"goals": True}
        for k, bk in (("shots", "totalShots"), ("sot", "shotsOnTarget"), ("fouls", "foulsCommitted"), ("cards", None),
                      ("corners", "wonCorners")):
            ok[k] = e.get("v", 1) >= 2 if k == "corners" else True     # older downloads have no corners
            ok[k] = ok[k] and all(st[h].get(bk or "yellowCards") is not None and abs(
                (full[h]["yellow"] + full[h]["red"] if k == "cards" else full[h][k]) -
                ((st[h]["yellowCards"] or 0) + (st[h]["redCards"] or 0) if k == "cards" else (st[h][bk] or 0))) <= 2
                for h in ("home", "away"))
        if int(eid) % 2 == 0:          # fitting half
            for r in rows:
                for k in kinds(r):
                    if k in curves_pos and ok[k]:
                        curves_pos[k].append(pos(r))
        games.append({"id": eid, "ok": ok, "snap": {str(t): snapshot(rows, float(t)) for t in (20, 30, 45, 60, 75)},
                      "final_box": st, "score": m["score"]})
    curves = {}
    for k, ps in curves_pos.items():
        ps.sort()
        n = len(ps)
        curves[k] = [round(sum(1 for p in ps if p > t) / n, 4) for t in range(91)]
    by_id = {g["id"]: g for g in games}
    joined = [{"pre": p, **by_id[p["espn_id"]]} for p in pre if p["espn_id"] in by_id]
    out = {"curves": curves, "check": check, "games": joined}
    (CACHE / "live_bt_data.json").write_text(json.dumps(out), encoding="utf-8")
    print("commentary vs final totals (exact match, out of", check["games"], "games):", check["exact"])
    print("share still to come at 45/60:", {k: (v[45], v[60]) for k, v in curves.items()})
    print(len(joined), "games with pre-match predictions; usable per stat:",
          {k: sum(g["ok"][k] for g in joined) for k in ok})


if __name__ == "__main__":
    main()
