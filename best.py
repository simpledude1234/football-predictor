"""Best bets: the picks most likely to land on the next match day.

Two short lists, at most one pick per game:
  - "safe":  safer tips with the highest chance (after learning from the track record),
             leaving out near-certain lines whose fair price is under 1.15
  - "value": higher-price picks with the highest chance
Each chosen tip is marked (tip["best"] = "safe" / "value") so the track record
scores the best bets on their own.
"""
import datetime as dt
from zoneinfo import ZoneInfo

N = 10
MAX_CHANCE = 87      # above this the fair price is under 1.15: bookmakers barely pay, so leave it out


def select(matches):
    now = dt.datetime.now(ZoneInfo("Europe/London")).strftime("%Y-%m-%d %H:%M")
    future = [m for m in matches if m["kickoff"] > now]
    if not future:
        return {"day": None, "safe": [], "value": []}
    day = min(m["iso"] for m in future)
    out = {"day": day}
    for kind in ("safe", "value"):
        cands = []
        for m in future:
            if m["iso"] != day:
                continue
            ts = [t for t in m["tips"] if t.get("chance") is not None and not t.get("skip")
                  and t["key"] != "player_booked" and bool(t.get("value")) == (kind == "value")
                  and t["chance"] <= MAX_CHANCE]
            if ts:
                rank = lambda t: (t["chance"], t["chance"] - (t.get("normal") or 50))   # ties: stands out most
                t = max(ts, key=rank)
                cands.append((rank(t), m, t))
        cands.sort(key=lambda c: c[0], reverse=True)
        out[kind] = []
        for ch, m, t in cands[:N]:
            t["best"] = kind
            out[kind].append({"match": f"{m['home']} v {m['away']}", "time": m["time"], "league": m["league"],
                              "label": t["label"], "pick": t["pick"], "chance": t["chance"],
                              "odds": t.get("min_odds") or round(100 / t["chance"], 2)})
    return out
