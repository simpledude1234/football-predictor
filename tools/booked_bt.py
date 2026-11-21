"""Test the player-to-be-booked model (players.py) on games it was not fitted on.

    py tools/booked_bt.py            # test: weights fitted before SPLIT, scored after it
    py tools/booked_bt.py --fit      # print weights fitted on all games, to paste into players.W

1) every regular player in every match after SPLIT (before line-ups, as the site does;
   void if he did not play): model 2 vs model 1, no match factor;
2) the site's logged picks after SPLIT, with the card-heavy-match factor at several strengths.
"""
import collections
import json
import math
import pathlib
import sys

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import players as PL

SPLIT = "2026-10-15"
cache = json.loads((ROOT / "cache" / "espn_matches.json").read_text(encoding="utf-8"))
pm = PL.PlayerModel(cache)
M = sorted(cache["matches"].values(), key=lambda m: m["date"])


def features(team, before):
    """The same numbers players.candidates uses, per regular player: (x, name)."""
    avg, (c_all, f_all) = pm._pos_avgs()
    games = [m for m in pm.team_games.get(team, []) if m["date"] < before]
    H = collections.defaultdict(lambda: {"mins": 0, "cards": 0, "fouls": 0, "pos": collections.Counter(), "m5": 0.0, "red": False})
    n5 = min(5, len(games))
    for i, m in enumerate(games):
        side = "home" if m["home"] == team else "away"
        booked = {n for n, s, st, y, r, f in m["players"] if s == side and y + r > 0}
        for key, v in m["pstats"].items():
            s, n = key.split("|", 1)
            if s != side or not v[4]:
                continue
            h = H[n]
            h["mins"] += v[4]; h["fouls"] += v[2]; h["cards"] += n in booked; h["pos"][v[5]] += 1
            if i >= len(games) - 5:
                h["m5"] += v[4] / n5
    if games:
        last = games[-1]
        for n, s, st, y, r, f in last["players"]:
            if s == ("home" if last["home"] == team else "away") and r > 0:
                H[n]["red"] = True
    out = {}
    for n, h in H.items():
        if h["m5"] < PL.MIN_MINS or h["red"]:
            continue
        pos = h["pos"].most_common(1)[0][0] if h["pos"] else "?"
        c90, f90 = avg.get(pos, (c_all, f_all)) if pos != "?" else (c_all, f_all)
        card = (h["cards"] + PL.SHRINK_MINS / 90 * c90) / (h["mins"] + PL.SHRINK_MINS) * 90
        foul = (h["fouls"] + PL.SHRINK_MINS / 90 * f90) / (h["mins"] + PL.SHRINK_MINS) * 90
        out[n] = [1.0, math.log(card / c_all), math.log(foul / f_all), math.log(max(h["m5"], 1) / 90)] + \
                 [1.0 if pos == p else 0.0 for p in "DMF"]
    return out


def rows(lo="2026-09-01", hi="2099"):
    out = []
    for m in M:
        if not lo <= m["date"] < hi:
            continue
        booked = {(n, s) for n, s, st, y, r, f in m["players"] if y + r > 0}
        played = {(n, s) for n, s, *_ in m["players"]}
        for side in ("home", "away"):
            if len([g for g in pm.team_games[m[side]] if g["date"] < m["date"]]) < 4:
                continue
            for n, x in features(m[side], m["date"]).items():
                if (n, side) in played:
                    out.append({"id": m["id"], "date": m["date"], "team": m[side], "n": n, "x": x, "y": (n, side) in booked})
    return out


def fit(rs, l2=1.0):
    A = np.array([r["x"] for r in rs]); y = np.array([r["y"] for r in rs], float)
    w = np.zeros(A.shape[1]); reg = np.r_[0, np.ones(len(w) - 1)] * l2
    for _ in range(50):
        p = 1 / (1 + np.exp(-A @ w))
        w -= np.linalg.solve((A * (p * (1 - p))[:, None]).T @ A + np.diag(reg), A.T @ (p - y) + reg * w)
    return dict(zip(["const", "card", "foul", "mins", "pos_D", "pos_M", "pos_F"], np.round(w, 3).tolist()))


def ll(p, y):
    return float(-np.mean([math.log(a if b else 1 - a) for a, b in zip(p, y)]))


if "--fit" in sys.argv:
    print("W =", fit(rows()))
    sys.exit()

PL.W = fit(rows(hi=SPLIT))
print("weights fitted before", SPLIT, PL.W)
test = rows(lo=SPLIT)
new, old, ys, ids = [], [], [], []
for r in test:
    o = {c["player"]: c["chance"] for c in pm.candidates_v1(r["team"], r["date"], None)}.get(r["n"])
    if o is None:
        continue
    nw = {c["player"]: c["chance"] for c in pm.candidates(r["team"], r["date"], None)}[r["n"]]
    new.append(nw / 100); old.append(o / 100); ys.append(r["y"]); ids.append(r["id"])
base = float(np.mean(ys))
print(f"\n1) {len(ys)} held-out player-games, {100*base:.1f}% booked. Log loss (lower = better): "
      f"no model {ll([base]*len(ys), ys):.4f}, model 1 {ll(old, ys):.4f}, model 2 {ll(new, ys):.4f}")
for name, ps in (("model 1", old), ("model 2", new)):
    by = collections.defaultdict(list)
    for p, y, i in zip(ps, ys, ids):
        by[i].append((p, y))
    top = [t for g in by.values() for t in sorted(g, key=lambda t: -t[0])[:3]]
    print(f"   top 3 per match, {name}: said {100*np.mean([t[0] for t in top]):.1f}%, landed {100*np.mean([t[1] for t in top]):.1f}% ({len(top)} picks)")

# 2) the site's logged picks: the card-heavy-match factor at several strengths
log = json.loads((ROOT / "tips_log.json").read_text(encoding="utf-8"))
picks = []
for e in log.values():
    em = cache["matches"].get(str(e.get("espn_id")))
    if not em or e["date"] < SPLIT:
        continue
    booked = {(n, s) for n, s, st, y, r, f in em["players"] if y + r > 0}
    played = {(n, s) for n, s, *_ in em["players"]}
    for t in e["tips"]:
        if t["key"] != "player_booked" or not t.get("chance") or (t["player"], t["team"]) not in played:
            continue
        team = em[t["team"]]
        v1 = {c["player"]: c["chance"] for c in pm.candidates_v1(team, e["date"], None)}.get(t["player"])
        v2 = {c["player"]: c["chance"] for c in pm.candidates(team, e["date"], None)}.get(t["player"])
        if v1 and v2:
            f = math.log(1 - t["chance"] / 100) / math.log(1 - v1 / 100)     # the factor the site used
            picks.append((v2 / 100, f, (t["player"], t["team"]) in booked))
y = [p[2] for p in picks]
print(f"\n2) {len(picks)} logged picks after {SPLIT} (landed {100*np.mean(y):.1f}%), model 2 with the match factor at:")
for a in (0, 0.25, 0.5, 0.75, 1.0):
    p = [1 - math.exp(math.log(1 - v) * f ** a) for v, f, _ in picks]
    print(f"   strength {a}: said {100*np.mean(p):.1f}%, log loss {ll(p, y):.4f}")
