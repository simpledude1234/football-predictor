"""Backtest helper: download minute-by-minute events (shots, fouls, cards, goals)
for the finished matches already in cache/espn_matches.json.
Saves cache/espn_events.json (local only; resumable)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import espn  # noqa: E402

OUT = espn.CACHE.parent / "espn_events.json"
KEEP = {"Shot Off Target", "Shot Blocked", "Shot On Target", "Goal", "Goal - Header", "Goal - Free-kick",
        "Penalty - Scored", "Own Goal", "Foul", "Yellow Card", "Red Card", "Penalty - Saved", "Penalty - Missed",
        "Shot Hit Woodwork", "Halftime", "End Regular Time", "Substitution", "Corner Awarded"}
VERSION = 3   # 2: also substitutions and corners, longer text; 3: players involved (for live player bookings)


def commentary_rows(s):
    """Minute-by-minute events from an ESPN match summary:
    [period, clock secs, clock text, side, type, text, players involved (for a foul: who fouled first)]."""
    side = {}
    for t in s.get("header", {}).get("competitions", [{}])[0].get("competitors", []):
        side[t["team"]["displayName"]] = t["homeAway"]
    rows, types = [], set()
    for x in s.get("commentary", []):
        p = x.get("play") or {}
        ty = (p.get("type") or {}).get("text")
        if not ty:
            continue
        types.add(ty)
        if ty not in KEEP and "Goal" not in ty and "Card" not in ty and "Penalty" not in ty and "Shot" not in ty:
            continue
        txt = p.get("text") or x.get("text") or ""
        who = side.get((p.get("team") or {}).get("displayName"), "?")
        if ty == "Corner Awarded":     # "Corner, Hull City. Conceded by ..." names the team that won it
            who = next((h for n, h in side.items() if txt.startswith(f"Corner, {n}.")), who)
        rows.append([p.get("period", {}).get("number"), (p.get("clock") or {}).get("value"),
                     (p.get("clock") or {}).get("displayValue"), who, ty, txt[:120],
                     [str((q.get("athlete") or {}).get("displayName") or "")[:60] for q in (p.get("participants") or [])[:3]]])
    return rows, types


def main():
    c = espn.load_cache()
    ev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [m for m in c["matches"].values() if m["id"] not in ev or ev[m["id"]].get("v", 1) < VERSION]
    print(f"{len(todo)} matches to fetch", flush=True)
    for i, m in enumerate(todo):
        try:
            s = espn.get_json(f"{espn.BASE}{m['slug']}/summary?event={m['id']}")
        except Exception as e:
            print(f"{m['id']}: failed ({e})", flush=True)
            continue
        rows, types = commentary_rows(s)
        ev[m["id"]] = {"rows": rows, "types": sorted(types), "v": VERSION}
        if i % 25 == 0:
            OUT.write_text(json.dumps(ev, separators=(",", ":")), encoding="utf-8")
            print(f"{i}/{len(todo)}", flush=True)
    OUT.write_text(json.dumps(ev, separators=(",", ":")), encoding="utf-8")
    print("done", len(ev), flush=True)


if __name__ == "__main__":
    main()
