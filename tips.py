"""Turn a match prediction into plain tips (one pick per market).

The tips page shows exactly these, and the track record scores exactly these,
so the two always agree.
"""

GENERIC = {"total_goals": "Total goals", "total_shots": "Total shots", "total_sot": "Total shots on target",
           "home_sot": "Home shots on target", "away_sot": "Away shots on target",
           "home_cards": "Home bookings", "away_cards": "Away bookings", "total_cards": "Total bookings",
           "home_fouls": "Home fouls", "away_fouls": "Away fouls",
           "home_gk": "Home goal kicks", "away_gk": "Away goal kicks", "free_kicks": "Total free kicks",
           "total_offsides": "Total offsides", "home_offsides": "Home offsides", "away_offsides": "Away offsides",
           "total_corners": "Total corners", "home_corners": "Home corners", "away_corners": "Away corners",
           "total_tackles": "Total tackles", "home_tackles": "Home tackles", "away_tackles": "Away tackles"}


import bet_builder
import learn
import player_stats as PS
import predictor as P
import value

_VP = value.load_params()
_BB = bet_builder.load_params()


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
    out = []
    # Match result (the bookmakers' view: their prices beat our model in the test). Tested on 6,610
    # past games: always tipping the favourite landed 51%. A win tip only when the favourite has 65%+
    # (landed 78%), otherwise "favourite or draw" when that has 72%+ (landed 82%), otherwise no tip.
    if f[best] >= 65:
        res = f"{h} to win" if best == "H" else f"{a} to win" if best == "A" else "Draw"
        out.append({"key": "result", "market": "Match result", "label": "Match result",
                    "pick": f"{res} ({round(f[best])}%)", "side": best, "chance": round(f[best]),
                    "line": None, "star": False})
    else:
        fav = "H" if f["H"] >= f["A"] else "A"
        dc = f[fav] + f["D"]
        if dc >= 72:
            out.append({"key": "result", "market": "Match result", "label": "Match result",
                        "pick": f"{h if fav == 'H' else a} or draw ({round(dc)}%)", "side": fav + "D",
                        "chance": round(dc), "line": None, "star": False})
    # Both teams to score: before kick-off it rarely gets past 60%; tipping it every game landed 55%.
    # Shown only when it reaches the same 72% bar as the other markets.
    bt = max(m["btts"], 100 - m["btts"])
    if bt >= 72:
        out.append({"key": "btts", "market": "Both teams to score", "label": "Both teams to score",
                    "pick": "Yes" if m["btts"] >= 50 else "No", "side": "yes" if m["btts"] >= 50 else "no",
                    "chance": round(bt), "line": None, "star": False})
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
    for k in m["markets"]:
        if k["estimate"] or not _VP:
            continue
        v = value.pick(k["expected"], k.get("phi"), k.get("book_line"), _VP["shrink"].get(k["key"]), k["key"],
                       _VP.get("show", {}).get(k["key"], False))
        if v:
            out.append({"key": k["key"], "market": "Higher price: " + GENERIC[k["key"]],
                        "label": named.get(k["key"], GENERIC[k["key"]]),
                        "pick": f"{v['side'].title()} {v['line']}", "side": v["side"], "line": v["line"],
                        "chance": v["chance"], "min_odds": v["min_odds"], "value": True, "star": False})
    pmove, _ = learn.adjust("player", "player_booked", P.LEARNED)     # learned from the track record
    for p in m.get("players", []):
        out.append({"key": "player_booked", "market": "Player to be booked", "label": "Player to be booked",
                    "pick": f"{p['player']} ({h if p['team'] == 'home' else a})", "side": "player",
                    "line": None, "player": p["player"], "team": p["team"],
                    "chance": max(1, min(99, round(p["chance"] + 100 * pmove))),
                    "confirmed": p.get("confirmed", False), "star": False})   # no player pick is strong enough to star (see players.py)
    out += pstat_tips(h, a, m.get("pstats", []))
    bb = builder_tip(out + pstat_tips(h, a, m.get("pstats_safe", [])))   # 72%+ player legs, used only here
    if bb:
        out.append(bb)
    out += book_value(m, out)
    return out


# ------------------------------------------------------------------ real bookmaker prices (odds_api.py)
BV_EDGE = 1.05            # our chance x best price: at least 5% above the fair price (room for error)
BV_CHANCE = (35, 85)      # no long shots (too noisy) and no near-certainties (nothing to gain)
BV_MAX = 1.25             # more than 25% above fair is almost always a stale price or a mismatched game


def _book_key(t):
    if t["key"] == "result" and t.get("side") in ("H", "D", "A"):
        return t["side"]
    if t["key"] == "total_goals" and t.get("side") in ("over", "under") and t.get("line") is not None:
        return f"{t['side']}_{float(t['line'])}"
    return None


def book_value(m, out):
    """Marks each tip that has a real bookmaker price (best on offer, and where), and returns at most one
    "Bookmaker value" pick for the game: the result or total goals outcome where the best price beats the
    fair price by the most, if by at least 5%. The fair chance there is half ours and half the UK
    bookmakers' own (margin taken out), so one bookmaker's slow price is value but our own error is not."""
    best = (m.get("book") or {}).get("best") or {}
    if not best:
        return []
    for t in out:
        k = _book_key(t)
        if k and k in best and not t.get("skip"):
            t["book_price"] = best[k]
    h, a, f = m["home"], m["away"], m["final"]
    cands = [("result", k, None, f[k], "Match result", {"H": f"{h} to win", "D": "Draw", "A": f"{a} to win"}[k])
             for k in "HDA" if k in best and f.get(k) is not None]
    tg = next((k for k in m["markets"] if k["key"] == "total_goals"), None)
    if tg:
        for k in best:
            side, _, line = k.partition("_")
            if side in ("over", "under") and line:
                po = 100 * P.over_prob(tg["expected"], float(line), tg.get("phi") or 1.0)
                cands.append(("total_goals", side, float(line), po if side == "over" else 100 - po,
                              "Total goals", f"{side.title()} {float(line):g}"))
    fair = (m.get("book") or {}).get("fair") or {}
    good = []
    for key, side, line, ch, label, pick in cands:
        bk = side if key == "result" else f"{side}_{line}"
        price = best[bk]
        if bk not in fair:
            continue
        ch = (ch + fair[bk]) / 2       # half ours, half the UK bookmakers' own view: an old or odd price is not value
        if BV_CHANCE[0] <= ch <= BV_CHANCE[1] and BV_EDGE <= ch / 100 * price[0] <= BV_MAX:
            good.append((ch / 100 * price[0], key, side, line, ch, label, pick, price))
    if not good:
        return []
    r, key, side, line, ch, label, pick, price = max(good)
    return [{"key": key, "market": "Bookmaker value: " + label, "label": label, "pick": pick, "side": side,
             "line": line, "chance": round(ch), "book_price": price, "edge": round(100 * (r - 1)), "bv": True,
             "star": False}]


def pstat_tips(h, a, picks):
    """Player shots / shots on target / fouls (tested in player_stats.py); own tab on the page."""
    return [{"key": "pl_" + p["stat"], "market": PS.MARKET[p["stat"]], "label": PS.MARKET[p["stat"]],
             "pick": f"{p['player']} ({h if p['team'] == 'home' else a}): {PS.label(p['stat'], p['line'])}",
             "side": "over", "line": p["line"], "player": p["player"], "team": p["team"], "stat": p["stat"],
             "chance": p["chance"], "confirmed": p.get("confirmed", False), "star": False} for p in picks]


def builder_tip(tips):
    """One bet builder per game from its tips (tested in bet_builder.py); own tab on the page."""
    bb = bet_builder.build(tips, _BB)
    if not bb:
        return None
    return {"key": "bet_builder", "market": "Bet builder", "label": "Bet builder",
            "pick": " + ".join(t["pick"] if t["key"].startswith("pl_") else f"{t['label']}: {t['pick']}" for t in bb["legs"]),
            "side": None, "line": None, "legs": bb["legs"], "chance": bb["chance"], "star": False}
