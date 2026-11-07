"""Backtest helper for live "player to be booked" picks.

Rebuilds every past game at 20, 30, 45, 60 and 75 minutes from ESPN's commentary:
who is on the pitch (starters, then substitutions), each player's fouls and cards
so far, and which players were booked later in the game. Only games whose
commentary counts the bookings exactly and the fouls to within 2 per team are used.
Run after tools/fetch_events.py and tools/live_prematch.py.
Writes cache/live_pl_data.json for tools/live_players_bt.js.
"""
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import espn  # noqa: E402
import live_backtest_data as LB  # noqa: E402
import players  # noqa: E402

CACHE = espn.CACHE.parent
AT = (20, 30, 45, 60, 75)


def name_before_bracket(txt, lead=""):
    t = txt[len(lead):] if lead and txt.startswith(lead) else txt
    i = t.find(" (")
    return t[:i].strip() if i > 0 else None


def events(rows, teams):
    """[(minute, kind, name)] with kind foul / yellow / red / on / off, each foul once.
    Names come from the players ESPN attaches to each event (for a foul, the fouler
    is listed first), so they match the team sheet; the text is the fallback."""
    out, seen = [], set()
    for r in rows:
        ty, txt, at = r[4], r[5], LB.pos(r)
        who = [x for x in (r[6] if len(r) > 6 else []) if x]
        if ty == "Foul":
            n = who[0] if who else next((name_before_bracket(txt, lead) for lead in ("Foul by ", "Penalty conceded by ")
                                         if txt.startswith(lead)), None)
            if n and (r[0], r[1], n) not in seen:
                seen.add((r[0], r[1], n))
                out.append((at, "foul", n))
        elif ty in ("Yellow Card", "Red Card"):
            n = who[0] if who else name_before_bracket(txt)
            if n and (r[0], r[1], n, ty) not in seen:
                seen.add((r[0], r[1], n, ty))
                out.append((at, "yellow" if ty == "Yellow Card" else "red", n))
        elif ty == "Substitution":
            for t in teams:
                lead = f"Substitution, {t}. "
                if txt.startswith(lead) and " replaces " in txt:
                    a, b = txt[len(lead):].rstrip(".").split(" replaces ", 1)
                    a, b = a.strip(), b.split(" because ")[0].strip()
                    if len(who) >= 2:          # use the team-sheet spelling of the same two players
                        a = min(who[:2], key=lambda x: _dist(x, a))
                        b = [x for x in who[:2] if x != a][0] if len(set(who[:2])) == 2 else b
                    out.append((at, "on", a))
                    out.append((at, "off", b))
    return sorted(out, key=lambda e: e[0])


def _dist(x, y):
    import difflib
    return 1 - difflib.SequenceMatcher(None, x, y).ratio()


def main():
    ev = json.loads((CACHE / "espn_events.json").read_text(encoding="utf-8"))
    cache = espn.load_cache()
    store = cache["matches"]
    global PM
    PM = players.PlayerModel(cache)
    pre = {p["espn_id"]: p for p in json.loads((CACHE / "live_bt_prematch.json").read_text(encoding="utf-8"))}
    games, skipped = [], {"no data": 0, "commentary off": 0}
    for eid, p in pre.items():
        e, m = ev.get(eid), store.get(eid)
        if not e or e.get("v", 1) < 2 or not m or not m.get("players") or not m.get("stats"):
            skipped["no data"] += 1
            continue
        rows = [r for r in e["rows"] if r[0] in (1, 2)]
        evs = events(rows, (m["home"], m["away"]))
        side_of = {n: s for n, s, *_ in m["players"]}
        st = m["stats"]
        # commentary must agree with the final box score
        cards = {h: sum(1 for _, k, n in evs if k in ("yellow", "red") and side_of.get(n) == h) for h in ("home", "away")}
        fouls = {h: sum(1 for _, k, n in evs if k == "foul" and side_of.get(n) == h) for h in ("home", "away")}
        ok = all(cards[h] == (st[h]["yellowCards"] or 0) + (st[h]["redCards"] or 0) and
                 abs(fouls[h] - (st[h]["foulsCommitted"] or 0)) <= 2 for h in ("home", "away"))
        if not ok:
            skipped["commentary off"] += 1
            continue
        snaps = {}
        for t in AT:
            on = {n: s for n, s, starter, *_ in m["players"] if starter}
            fl, yl, rd = {}, {}, {}
            for at, k, n in evs:
                if at > t:
                    break
                if k == "on" and n in side_of:
                    on[n] = side_of[n]
                elif k == "off":
                    on.pop(n, None)
                elif k == "foul":
                    fl[n] = fl.get(n, 0) + 1
                elif k == "yellow":
                    yl[n] = 1
                elif k == "red":
                    rd[n] = 1
                    on.pop(n, None)
            later = sorted({n for at, k, n in evs if at > t and k in ("yellow", "red")})
            snaps[str(t)] = {
                "players": {h: [[n, 1 if on.get(n) == h else 0, yl.get(n, 0), rd.get(n, 0), fl.get(n, 0)]
                                for n, s, *_ in m["players"] if s == h] for h in ("home", "away")},
                "cards": {h: {"yellow": sum(1 for n in yl if side_of.get(n) == h),
                              "red": sum(1 for n in rd if side_of.get(n) == h)} for h in ("home", "away")},
                "later": later}
        p = {**p, "fh": {h: PM.foul_habit(m[h], m["date"]) for h in ("home", "away")}}
        games.append({"id": eid, "pre": p, "snap": snaps})
    (CACHE / "live_pl_data.json").write_text(json.dumps({"games": games}), encoding="utf-8")
    print(f"{len(games)} games rebuilt for player bookings; left out: {skipped}")


if __name__ == "__main__":
    main()
