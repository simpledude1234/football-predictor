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
        "Shot Hit Woodwork", "Halftime", "End Regular Time"}


def commentary_rows(s):
    """Minute-by-minute events from an ESPN match summary: [period, clock secs, clock text, side, type, text]."""
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
        rows.append([p.get("period", {}).get("number"), (p.get("clock") or {}).get("value"),
                     (p.get("clock") or {}).get("displayValue"), side.get((p.get("team") or {}).get("displayName"), "?"),
                     ty, (p.get("text") or "")[:60]])
    return rows, types


def main():
    c = espn.load_cache()
    ev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    todo = [m for m in c["matches"].values() if m["id"] not in ev]
    print(f"{len(todo)} matches to fetch", flush=True)
    for i, m in enumerate(todo):
        try:
            s = espn.get_json(f"{espn.BASE}{m['slug']}/summary?event={m['id']}")
        except Exception as e:
            print(f"{m['id']}: failed ({e})", flush=True)
            continue
        rows, types = commentary_rows(s)
        ev[m["id"]] = {"rows": rows, "types": sorted(types)}
        if i % 25 == 0:
            OUT.write_text(json.dumps(ev, separators=(",", ":")), encoding="utf-8")
            print(f"{i}/{len(todo)}", flush=True)
    OUT.write_text(json.dumps(ev, separators=(",", ":")), encoding="utf-8")
    print("done", len(ev), flush=True)


if __name__ == "__main__":
    main()
