"""The system learns from its own track record.

Before each build it looks at every finished tip from the last DAYS days (live
tips and replays) and, for each market, compares how often the tips landed with
the chance they stated. Next time, that market's chances are moved by the gap,
trusted more as tips pile up (gap x n / (n + TRUST)). A market whose recent
tips fall below the bar it needs (72% for safer tips, 54% for higher-price
picks, the break-even at 1.85) is not tipped until its record recovers.
Player-booking chances are corrected the same way (never paused); player stat
picks (shots, fouls...) are corrected, and paused if they land under 50%. Bet builders are
scored but not learned from.
Live picks are scored in the track record but not learned from (yet).

Writes learn_params.json; predictor.best_tip and value.pick read it.
"""
import datetime as dt
import json
import pathlib

HERE = pathlib.Path(__file__).parent
FILE = HERE / "learn_params.json"
DAYS = 120
TRUST = 100              # after 100 tips the gap counts half, after 300 three quarters
MAX_MOVE = 0.15
MIN_TO_HIDE = 50
BARS = {"safe": 72, "value": 54, "pstat": 50}   # player stats: priced lines (said 52-62%)


def learn(track):
    cut = str(dt.date.today() - dt.timedelta(days=DAYS))
    g = {"safe": {}, "value": {}, "player": {}, "pstat": {}}
    for game in track["games"]:
        if game["date"] < cut:
            continue
        for t in game["tips"]:
            if t["hit"] is None or t.get("chance") is None or t.get("key") is None or t.get("live"):
                continue
            if t["key"] == "bet_builder" or t.get("bv"):      # combinations / bookmaker-price picks: scored, not learned from
                continue
            kind = "player" if t["key"] == "player_booked" else "pstat" if t["key"].startswith("pl_") else "value" if t.get("value") else "safe"
            s = g[kind].setdefault(t["key"], [0, 0, 0.0])
            s[0] += 1
            s[1] += t["hit"]
            s[2] += t["chance"]
    out = {"updated": str(dt.date.today()), "days": DAYS, "safe": {}, "value": {}, "player": {}, "pstat": {}}
    for kind, d in g.items():
        for k, (n, hit, said) in d.items():
            landed, claimed = 100 * hit / n, said / n
            move = max(-MAX_MOVE, min(MAX_MOVE, (landed - claimed) / 100 * n / (n + TRUST)))
            out[kind][k] = {"n": n, "landed": round(landed, 1), "said": round(claimed, 1),
                            "move": round(move, 3),
                            "hide": kind in BARS and n >= MIN_TO_HIDE and landed < BARS[kind]}
    FILE.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def load():
    return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {"safe": {}, "value": {}}


def adjust(kind, key, learned=None):
    """(how much to move this market's chances, whether to stop tipping it)."""
    d = (learned if learned is not None else load()).get(kind, {}).get(key)
    return (d["move"], d["hide"]) if d else (0.0, False)


def note(learned):
    """One plain line for the page."""
    kinds = ("safe", "value", "player", "pstat")
    moved = [(k, v) for kind in kinds for k, v in learned.get(kind, {}).items() if abs(v["move"]) >= 0.01]
    hidden = [k for kind in kinds for k, v in learned.get(kind, {}).items() if v["hide"]]
    n = sum(v["n"] for kind in kinds for v in learned.get(kind, {}).values())
    return (f"Learns from its own record: {n:,} finished tips from the last {DAYS} days checked; "
            f"{len(moved)} market{'s' if len(moved) != 1 else ''} adjusted"
            + (f", {len(hidden)} paused for falling below the bar" if hidden else "") + ".")
