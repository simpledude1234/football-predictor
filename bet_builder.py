"""Bet builder: one combination bet per game, built from that game's own tips.

Legs come only from markets already tested and tipped: team tips (72%+ ones and
the higher-price ones) and player stat picks (the priced lines and the 72%+
ones). No leg above MAX_LEG% and no player "1+ shot" leg: bookmakers price those
at 1.01-1.25, so they add almost nothing to the price of the bet builder (and
bet365's 1+ shot bets move to the substitute, a different bet from ours). At most one leg per kind of market (goals, shots, cards,
fouls, corners, offsides, tackles) and at most two player legs, never two from
the same player, so the bet mixes different things.

Picks in one game are linked (a game with lots of shots tends to have lots of
shots on target too), so the combined chance is not just the chances
multiplied: each pair of legs gets a correction measured on past games (how
often both landed, against what multiplying said), pulled towards "no link"
when there are few past examples. Legs are added, most likely first, while
the combined chance stays at MIN_CHANCE or more (a fair price of about 2.85 at
most, so the bet pays a real price); a game gets a bet builder only with 2 to 4
legs and a fair price of MIN_ODDS or more.

Run `py -3.13 bet_builder.py` to test: links are measured on the earlier half
of the logged games and the bet builders are scored on the later half.
Saves bet_builder_params.json.
"""
import json
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).parent
PARAMS = HERE / "bet_builder_params.json"
MIN_CHANCE = 35          # held-out (from 25 Oct 2026), 226 bet builders: said 41.2, landed 42.5
MAX_LEG = 80            # legs above this price under 1.25: they barely move the price
MIN_ODDS = 2.0          # the whole bet builder at a fair price of at least this
MIN_VALUE_LEG = 58
MIN_PLAYER_LEG = 55
MAX_LEGS = 4
SHRINK = 100.0          # past games of "no link" added to every pair (30 over-promised by ~4 points on held-out games; 100 lands as said)
GROUP = {"result": "goals", "btts": "goals", "total_goals": "goals",
         "total_shots": "shots", "total_sot": "shots", "home_sot": "shots", "away_sot": "shots",
         "home_cards": "cards", "away_cards": "cards", "total_cards": "cards",
         "home_fouls": "fouls", "away_fouls": "fouls",
         "total_corners": "corners", "home_corners": "corners", "away_corners": "corners",
         "total_offsides": "offsides", "home_offsides": "offsides", "away_offsides": "offsides",
         "total_tackles": "tackles", "home_tackles": "tackles", "away_tackles": "tackles"}


def load_params():
    return json.loads(PARAMS.read_text(encoding="utf-8")) if PARAMS.exists() else None


def family(t):
    """What kind of leg this is, for the pair links: e.g. "home_sot:over", "pl_shots:home"."""
    if t["key"].startswith("pl_"):
        return f"{t['key']}:{t['team']}"
    return f"{t['key']}:{t.get('side')}"


def pair_key(a, b):
    return "|".join(sorted((a, b)))


def legs_of(tips):
    out = []
    for t in tips:
        if t.get("skip") or t.get("estimate") or t.get("chance") is None or t.get("live"):
            continue
        if t["chance"] > MAX_LEG:
            continue
        if t["key"].startswith("pl_"):
            if t.get("stat") == "shots" and t.get("line") == 1:
                continue
            if t["chance"] >= MIN_PLAYER_LEG:
                out.append(t)
        elif t["key"] in GROUP and t["chance"] >= (MIN_VALUE_LEG if t.get("value") else 72):
            out.append(t)
    return sorted(out, key=lambda t: -t["chance"])


def combined(legs, links):
    p = 1.0
    for t in legs:
        p *= t["chance"] / 100
    for i in range(len(legs)):
        for j in range(i + 1, len(legs)):
            p *= links.get(pair_key(family(legs[i]), family(legs[j])), 1.0)
    return min(p, min(t["chance"] for t in legs) / 100)


def build(tips, params):
    """The bet builder for one game (or None): {"legs": [...], "chance", "odds"}."""
    if not params or not params.get("show"):
        return None
    links = params.get("links", {})
    chosen, groups, players = [], set(), defaultdict(int)
    for t in legs_of(tips):
        if len(chosen) == MAX_LEGS:
            break
        if t["key"].startswith("pl_"):
            if sum(players.values()) >= 2 or players[t["player"]]:
                continue
        elif GROUP[t["key"]] in groups:
            continue
        if combined(chosen + [t], links) * 100 < MIN_CHANCE:
            continue
        chosen.append(t)
        if t["key"].startswith("pl_"):
            players[t["player"]] += 1
        else:
            groups.add(GROUP[t["key"]])
    if len(chosen) < 2:
        return None
    ch = round(100 * combined(chosen, links))
    if 100 / ch < MIN_ODDS:
        return None
    return {"legs": [{k: t.get(k) for k in ("key", "label", "pick", "side", "line", "chance", "player", "team", "stat", "value")}
                     for t in chosen], "chance": ch, "odds": round(100 / ch, 2)}


# ------------------------------------------------------------------ test on past games
def _past_games(cache):
    """Logged games with each tip marked landed or not, plus player stat picks (predicted with
    only earlier games) and whether they landed."""
    import player_stats as PS
    import record
    pp = PS.load_params()
    pm = PS.Model(cache, pp["params"]) if pp else None
    log = record.load()
    by_key = {(e["date"], e["home"], e["away"]): e for e in log.values()}
    games = []
    for g in record.score(cache)["games"]:
        e = by_key.get((g["date"], g["home"], g["away"]))
        if not e:
            continue
        sides = {t["label"] + t["pick"]: t for t in e["tips"]}
        tips = []
        for r in g["tips"]:
            if r["hit"] is None or r.get("live") or r["key"] not in GROUP or r.get("chance") is None:
                continue
            src = sides.get(r["label"] + r["pick"], {})
            tips.append({"key": r["key"], "label": r["label"], "pick": r["pick"], "chance": r["chance"],
                         "side": src.get("side"), "line": src.get("line"), "hit": r["hit"],
                         "value": bool(r.get("value"))})
        em = cache["matches"].get(str(e.get("espn_id"))) if e.get("espn_id") else None
        if pm and em and em.get("pstats"):
            for p in [q for mode in ("price", "safe") for q in
                      PS.picks(pm, pp, em["home"], em["away"], em["date"], mode=mode,
                               xg=(em.get("odds") or {}).get("xg"))]:
                v = em["pstats"].get(f"{p['team']}|{p['player']}")
                if v is None:
                    continue                 # did not play: void
                tips.append({"key": "pl_" + p["stat"], "label": PS.MARKET[p["stat"]], "pick": p["player"],
                             "chance": p["chance"], "player": p["player"], "team": p["team"], "stat": p["stat"],
                             "line": p["line"], "side": "over", "hit": v[PS.IDX[p["stat"]]] >= p["line"]})
        games.append({"date": g["date"], "tips": tips})
    games.sort(key=lambda g: g["date"])
    return games


def fit_links(games):
    stat = defaultdict(lambda: [0, 0.0, 0])      # pair -> [both landed, sum of multiplied chances, n]
    for g in games:
        ts = legs_of(g["tips"])
        for i in range(len(ts)):
            for j in range(i + 1, len(ts)):
                a, b = ts[i], ts[j]
                s = stat[pair_key(family(a), family(b))]
                s[0] += a["hit"] and b["hit"]
                s[1] += a["chance"] * b["chance"] / 1e4
                s[2] += 1
    links = {}
    for k, (both, said, n) in stat.items():
        e = said / n
        links[k] = round((both + SHRINK * e) / (said + SHRINK * e), 3)
    return links


def backtest(cache):
    games = _past_games(cache)
    half = games[len(games) // 2]["date"]
    early, late = [g for g in games if g["date"] < half], [g for g in games if g["date"] >= half]
    links = fit_links(early)
    prm = {"links": links, "show": True}
    built = []
    for g in late:
        b = build(g["tips"], prm)
        if b:
            hit = {(t["key"], t["pick"], bool(t.get("value")), t.get("line")): t["hit"] for t in g["tips"]}
            built.append((b["chance"], all(hit[(t["key"], t["pick"], bool(t.get("value")), t.get("line"))] for t in b["legs"]), len(b["legs"]),
                          sum(1 for t in b["legs"] if t["key"].startswith("pl_"))))
    n = len(built)
    said = sum(b[0] for b in built) / n if n else None
    landed = 100 * sum(b[1] for b in built) / n if n else None
    plain = None
    # the same bet builders priced by just multiplying the chances (no links), for comparison
    flat = {"links": {}, "show": True}
    fb = [build(g["tips"], flat) for g in late]
    fb = [b for b in fb if b]
    if fb:
        plain = round(sum(b["chance"] for b in fb) / len(fb), 1)
    legs = defaultdict(lambda: [0, 0])
    for b in built:
        legs[b[2]][0] += b[1]
        legs[b[2]][1] += 1
    out = {"links": fit_links(games), "show": bool(n >= 40 and landed >= said - 5),
           "test": {"games": len(late), "built": n, "said": round(said, 1) if n else None,
                    "landed": round(landed, 1) if n else None, "said_if_just_multiplied": plain,
                    "with_player_legs": sum(1 for b in built if b[3]),
                    "by_legs": {k: {"built": v[1], "landed": round(100 * v[0] / v[1], 1)} for k, v in sorted(legs.items())},
                    "from": half}}
    return out


if __name__ == "__main__":
    import espn
    out = backtest(espn.load_cache())
    PARAMS.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["test"], indent=1), "show:", out["show"])
