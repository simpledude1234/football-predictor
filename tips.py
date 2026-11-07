"""Turn a match prediction into plain tips (one pick per market).

The tips page shows exactly these, and the track record scores exactly these,
so the two always agree.
"""

GENERIC = {"total_shots": "Total shots", "total_sot": "Total shots on target",
           "home_sot": "Home shots on target", "away_sot": "Away shots on target",
           "home_cards": "Home bookings", "away_cards": "Away bookings", "total_cards": "Total bookings",
           "home_fouls": "Home fouls", "away_fouls": "Away fouls",
           "home_gk": "Home goal kicks", "away_gk": "Away goal kicks", "free_kicks": "Total free kicks",
           "total_offsides": "Total offsides", "home_offsides": "Home offsides", "away_offsides": "Away offsides",
           "total_corners": "Total corners", "home_corners": "Home corners", "away_corners": "Away corners",
           "total_tackles": "Total tackles", "home_tackles": "Home tackles", "away_tackles": "Away tackles"}


def make_tips(m):
    h, a = m["home"], m["away"]
    named = {"home_sot": f"{h} shots on target", "away_sot": f"{a} shots on target",
             "home_cards": f"{h} bookings", "away_cards": f"{a} bookings",
             "home_fouls": f"{h} fouls", "away_fouls": f"{a} fouls",
             "home_gk": f"{h} goal kicks", "away_gk": f"{a} goal kicks",
             "home_offsides": f"{h} offsides", "away_offsides": f"{a} offsides",
             "home_corners": f"{h} corners", "away_corners": f"{a} corners",
             "home_tackles": f"{h} tackles", "away_tackles": f"{a} tackles"}
    f = m["final"]
    best = max("HDA", key=lambda k: f[k])
    res = f"{h} to win" if best == "H" else f"{a} to win" if best == "A" else "Draw"
    out = [{"key": "result", "market": "Match result", "label": "Result",
            "pick": res + (" (close call)" if f[best] < 45 else ""), "side": best, "line": None,
            "star": f[best] >= 60},
           {"key": "btts", "market": "Both teams to score", "label": "Both teams to score",
            "pick": "Yes" if m["btts"] >= 50 else "No", "side": "yes" if m["btts"] >= 50 else "no",
            "line": None, "star": m["btts"] >= 62 or m["btts"] <= 38}]
    for k in m["markets"]:
        label = named.get(k["key"], GENERIC[k["key"]])
        if not k["estimate"]:
            t = k.get("tip")
            if t is None:      # a normal game for this market: nothing worth tipping
                out.append({"key": k["key"], "market": GENERIC[k["key"]], "label": label, "pick": "No tip",
                            "side": None, "line": None, "skip": True, "star": False})
                continue
            out.append({"key": k["key"], "market": GENERIC[k["key"]], "label": label,
                        "pick": f"{t['side'].title()} {t['line']}", "side": t["side"], "line": t["line"],
                        "chance": t["chance"], "normal": t["normal"],
                        "star": t["chance"] - t["normal"] >= 12, "estimate": False})
            continue
        # goal kicks and free kicks: estimates (no free data to test them), old rule
        rel = (k["expected"] - k["league_avg"]) / k["league_avg"] if k["league_avg"] else 0
        if rel >= 0 and k["safe_over"] is not None:
            side, line = "over", k["safe_over"]
        elif rel < 0 and k["safe_under"] is not None:
            side, line = "under", k["safe_under"]
        else:
            side, line = ("over" if k["over"] >= 50 else "under"), k["line"]
        out.append({"key": k["key"], "market": GENERIC[k["key"]], "label": named.get(k["key"], GENERIC[k["key"]]),
                    "pick": f"{side.title()} {line}", "side": side, "line": line,
                    "star": abs(rel) > 0.12 and not k["estimate"], "estimate": k["estimate"]})
    for p in m.get("players", []):
        out.append({"key": "player_booked", "market": "Player to be booked", "label": "Player to be booked",
                    "pick": f"{p['player']} ({h if p['team'] == 'home' else a})", "side": "player",
                    "line": None, "player": p["player"], "team": p["team"], "chance": p["chance"],
                    "confirmed": p.get("confirmed", False), "star": False})   # no player pick is strong enough to star (see players.py)
    return out
