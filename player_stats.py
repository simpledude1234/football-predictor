"""Player stats: shots, shots on target, fouls committed and fouls won.

For every player we take, this season, how many of each he makes per 90
minutes, recent games counting more (players with few minutes are pulled
towards the average for their position: keeper, defender, midfielder,
forward), times the minutes he usually plays, times how much this opponent
usually allows, times a home/away factor, times the match itself: the
bookmakers' expected goals for his team and the opponent compared with his
team's usual games (a favourite's forwards shoot more; an underdog defends
and fouls more). Counts are spread out a little more than pure chance (a
negative binomial), so a player who usually has 2 shots still often has 0.

Two kinds of pick:
  "price": the page's Player stats tab. Lines priced about 1.60 to 1.92
           (a 52-62% chance), the most likely one per player.
  "safe":  72%+ lines, used only as bet builder legs.
Only regular starters get picks (started 4 of the team's last 5 games), or
named starters once the line-ups are out. A player who does not play voids
the pick, the same as at the bookmakers.

ESPN has no per-player tackles, so there is no tackles market.

Run `py -3.13 player_stats.py` to test on past games: settings are chosen on
the games before the cut-off and scored on the games after it, which the
settings never saw. Saved to player_stats_params.json; only stat/line pairs
whose test picks landed as often as they said are tipped.
"""
import bisect
import json
import math
import pathlib
from collections import Counter, defaultdict

HERE = pathlib.Path(__file__).parent
PARAMS = HERE / "player_stats_params.json"
BAR = 72                       # safe picks (bet builder legs)
PRICE = (52.0, 62.5)           # price picks: fair price about 1.92 down to 1.60
MIN_TEST = {"safe": 15, "price": 30}
IDX = {"shots": 0, "sot": 1, "fouls": 2, "fwon": 3}
LINES = {"shots": (1, 2, 3, 4), "sot": (1, 2), "fouls": (1, 2), "fwon": (1, 2)}
NAMES = {"shots": "shots", "sot": "shots on target", "fouls": "fouls", "fwon": "fouls won"}
MARKET = {"shots": "Player shots", "sot": "Player shots on target", "fouls": "Player fouls", "fwon": "Player fouls won"}
# what the opponent allows: (ESPN team stat, whose) -- "opp" = made by the opponent's opponents
TEAM_STAT = {"shots": ("totalShots", "opp"), "sot": ("shotsOnTarget", "opp"),
             "fouls": ("foulsCommitted", "opp"), "fwon": ("foulsCommitted", "own")}
ZERO = {s: 0.0 for s in IDX}
DEFAULT = {"k90": 1.0, "half": None, "opp": 0.5, "pos": True, "own_b": dict(ZERO), "opp_b": dict(ZERO),
           "disp": {"shots": 2.0, "sot": 1.5, "fouls": 3.0, "fwon": 3.0},
           "ratio": {"shots": True, "sot": False, "fouls": False, "fwon": False}, "move": {}}
TEAM_PRIOR = 5.0


def load_params():
    return json.loads(PARAMS.read_text(encoding="utf-8")) if PARAMS.exists() else None


def size(params, stat, lam):
    """Spread: a fixed size, or (ratio) one that grows with the mean (spread in proportion to it)."""
    d = params["disp"][stat]
    return max(0.05, d * lam) if params.get("ratio", {}).get(stat) else d


def at_least(k, lam, r):
    """Chance of k or more with mean lam (negative binomial, size r)."""
    if lam <= 0:
        return 0.0
    p = r / (r + lam)
    term = p ** r                     # P(0)
    cdf = term
    for i in range(1, k):
        term *= (i - 1 + r) / i * (1 - p)
        cdf += term
    return max(0.0, 1.0 - cdf)


def xg_of(m, side):
    """(own, opponent) expected goals from the closing odds stored with a past match, if any."""
    xg = (m.get("odds") or {}).get("xg")
    if not xg:
        return None
    return (xg[0], xg[1]) if side == "home" else (xg[1], xg[0])


class Model:
    def __init__(self, cache, params=None):
        self.p = {**DEFAULT, **(params or {})}
        ms = [m for m in cache.get("matches", {}).values() if m.get("pstats") and m.get("stats")]
        ms.sort(key=lambda m: m["date"])
        self.ms = ms
        self.team = defaultdict(list)          # team -> [match] by date
        for m in ms:
            for s in ("home", "away"):
                self.team[m[s]].append(m)
        self.dates = {t: [m["date"] for m in g] for t, g in self.team.items()}
        # league-wide averages: per 90 by position, home/away split, team per game
        tot = defaultdict(lambda: [0.0] * 5)
        side_tot = {"home": [0.0] * 4, "away": [0.0] * 4}
        for m in ms:
            for key, v in m["pstats"].items():
                sd = key.split("|", 1)[0]
                g = v[5] if len(v) > 5 else "?"
                for i in range(4):
                    tot[g][i] += v[i]
                    tot["all"][i] += v[i]
                    if sd in side_tot:
                        side_tot[sd][i] += v[i]
                tot[g][4] += v[4]
                tot["all"][4] += v[4]
        self.prior90 = {g: [t[i] / (t[4] / 90) if t[4] else 0.5 for i in range(4)] for g, t in tot.items()}
        n = max(1, len(ms))
        self.ha = {sd: [(side_tot[sd][i] / n) / ((tot["all"][i] / 2) / n) if tot["all"][i] else 1.0 for i in range(4)]
                   for sd in ("home", "away")}
        self.team_avg = {}
        for stat, (espn_name, _) in TEAM_STAT.items():
            vals = [m["stats"][s].get(espn_name) for m in ms for s in ("home", "away")]
            vals = [v for v in vals if v is not None]
            self.team_avg[stat] = sum(vals) / len(vals) if vals else 1.0
        self._sq = {}

    def games_before(self, team, date):
        g = self.team.get(team, [])
        return g[:bisect.bisect_left(self.dates.get(team, []), date)]

    def opp_factor(self, opp, date, stat):
        espn_name, whose = TEAM_STAT[stat]
        vals = []
        for m in self.games_before(opp, date):
            s = "home" if m["home"] == opp else "away"
            o = "away" if s == "home" else "home"
            v = m["stats"][o if whose == "opp" else s].get(espn_name)
            if v is not None:
                vals.append(v)
        avg = self.team_avg[stat]
        f = (sum(vals) + TEAM_PRIOR * avg) / (len(vals) + TEAM_PRIOR) / avg
        return f ** self.p["opp"]

    def squad(self, team, date, lineup=None):
        """Regular starters (or the named eleven): per-90 rates, usual minutes and the expected
        goals of the games those rates come from."""
        ck = (team, date, tuple(lineup or ()))
        if ck in self._sq:
            return self._sq[ck]
        games = self.games_before(team, date)
        if len(games) < 3:
            return {}
        last5 = {id(m) for m in games[-5:]}
        half = self.p.get("half")
        st = defaultdict(lambda: {"x": [0.0] * 4, "w90": 0.0, "starts5": 0, "start_mins": [], "pos": Counter(),
                                  "xg": [0.0, 0.0, 0.0]})
        ng = len(games)
        for gi, m in enumerate(games):
            side = "home" if m["home"] == team else "away"
            w = 0.5 ** ((ng - 1 - gi) / half) if half else 1.0
            xg = xg_of(m, side)
            starters = {n for n, s, starter, *_ in m["players"] if s == side and starter}
            for key, v in m["pstats"].items():
                sd, name = key.split("|", 1)
                if sd != side:
                    continue
                p = st[name]
                for i in range(4):
                    p["x"][i] += w * v[i]
                p["w90"] += w * v[4] / 90
                if len(v) > 5 and v[5] != "?":
                    p["pos"][v[5]] += 1
                if xg:                         # minutes-weighted expected goals of his games
                    p["xg"][0] += w * v[4] * xg[0]
                    p["xg"][1] += w * v[4] * xg[1]
                    p["xg"][2] += w * v[4]
                if name in starters:
                    p["start_mins"].append(v[4])
                    if id(m) in last5:
                        p["starts5"] += 1
        k = self.p["k90"]
        out = {}
        names = lineup if lineup else [n for n, p in st.items() if p["starts5"] >= 4]
        for name in names:
            p = st.get(name)
            if not p or not p["start_mins"]:
                continue
            g = p["pos"].most_common(1)[0][0] if p["pos"] else "all"
            prior = self.prior90.get(g if self.p.get("pos") else "all", self.prior90["all"])
            mins = sum(p["start_mins"][-10:]) / len(p["start_mins"][-10:])
            rate = [(p["x"][i] + k * prior[i]) / (p["w90"] + k) for i in range(4)]
            xg = (p["xg"][0] / p["xg"][2], p["xg"][1] / p["xg"][2]) if p["xg"][2] else None
            out[name] = {"rate": rate, "mins": mins, "games": len(p["start_mins"]), "pos": g, "xg": xg}
        self._sq[ck] = out
        return out

    def chances(self, team, opp, side, date, lineup=None, xg=None):
        """[{player, stat, line, chance}] for every regular starter, every stat and line.
        xg: (own, opponent) expected goals for this match from the bookmakers, if known."""
        rows = []
        f = {stat: self.opp_factor(opp, date, stat) for stat in IDX}
        for name, p in self.squad(team, date, lineup).items():
            r_own = r_opp = 1.0
            if xg and p["xg"]:
                r_own = max(0.3, min(3.0, xg[0] / p["xg"][0]))
                r_opp = max(0.3, min(3.0, xg[1] / p["xg"][1]))
            for stat, i in IDX.items():
                base = p["rate"][i] * p["mins"] / 90 * f[stat] * self.ha[side][i]
                lam = base * r_own ** self.p["own_b"][stat] * r_opp ** self.p["opp_b"][stat]
                for line in LINES[stat]:
                    rows.append({"player": name, "stat": stat, "line": line, "lam": lam, "base": base,
                                 "r_own": r_own, "r_opp": r_opp,
                                 "chance": 100 * at_least(line, lam, size(self.p, stat, lam))})
        return rows


def label(stat, line):
    return f"{line}+ {NAMES[stat] if line > 1 else NAMES[stat].replace('shots', 'shot').replace('fouls', 'foul')}"


def picks(model, params, home, away, date, lineup=None, n=6, move=None, xg=None, mode="price"):
    """The player picks for one match.
    price: per player the most likely line priced 1.60-1.92, at most n per match (most likely first).
    safe: 72%+ lines, the highest line per player and stat (bet builder legs).
    xg: (home, away) expected goals from the bookmakers, if known."""
    if not params or not home or not away:
        return []
    ok = (params.get("show") or {}).get(mode, {})
    move = move or {}
    fix = (params.get("params", {}).get("move") or {}).get(mode, {})   # top-pick over-confidence, from the test
    best = {}
    for side, team, opp in (("home", home, away), ("away", away, home)):
        x = (xg if side == "home" else (xg[1], xg[0])) if xg else None
        for r in model.chances(team, opp, side, date, (lineup or {}).get(side), x):
            key = f"{r['stat']}_{r['line']}"
            if not ok.get(key):
                continue
            ch = r["chance"] + 100 * (move.get(r["stat"], 0.0) + fix.get(key, 0.0))
            pick = {"player": r["player"], "team": side, "stat": r["stat"], "line": r["line"],
                    "chance": min(97, round(ch)), "confirmed": bool(lineup)}
            if mode == "safe":
                if ch < BAR:
                    continue
                k2 = (r["player"], r["stat"])
                if k2 not in best or r["line"] > best[k2]["line"]:
                    best[k2] = pick
            else:
                if not PRICE[0] <= ch <= PRICE[1]:
                    continue
                if r["player"] not in best or ch > best[r["player"]]["chance"]:
                    best[r["player"]] = pick
    return sorted(best.values(), key=lambda x: -x["chance"])[:n]


# ------------------------------------------------------------------ test on past games
def _cases(cache, params, start=None, end=None, model=None):
    """Every starter in every stored match from start to end, predicted with only earlier games."""
    m = model or Model(cache, params)
    out = []
    for g in m.ms:
        if (start and g["date"] < start) or (end and g["date"] >= end):
            continue
        for side, team, opp in (("home", g["home"], g["away"]), ("away", g["away"], g["home"])):
            started = {n for n, s, st, *_ in g["players"] if s == side and st}
            for r in m.chances(team, opp, side, g["date"], None, xg_of(g, side)):
                v = g["pstats"].get(f"{side}|{r['player']}")
                if v is None or r["player"] not in started:
                    continue          # did not start: void (only starters are scored here)
                out.append({**r, "date": g["date"], "id": g["id"], "side": side, "hit": v[IDX[r["stat"]]] >= r["line"]})
    return out


def _reprice(cases, prm):
    out = []
    for c in cases:
        st = c["stat"]
        lam = c["base"] * c["r_own"] ** prm["own_b"][st] * c["r_opp"] ** prm["opp_b"][st]
        out.append({**c, "lam": lam, "chance": 100 * at_least(c["line"], lam, size(prm, st, lam))})
    return out


def _loss(cases):
    s = 0.0
    for c in cases:
        p = min(max(c["chance"] / 100, 1e-4), 1 - 1e-4)
        s -= math.log(p if c["hit"] else 1 - p)
    return s / max(1, len(cases))


def _shown(cache, prm, show, mode, start=None, end=None):
    """The picks the page would have shown for each stored match from start to end, and how they did."""
    m = Model(cache, prm)
    out = []
    for g in m.ms:
        if (start and g["date"] < start) or (end and g["date"] >= end):
            continue
        xg = (g.get("odds") or {}).get("xg")
        for p in picks(m, {"params": prm, "show": {mode: show}}, g["home"], g["away"], g["date"], xg=xg, mode=mode):
            v = g["pstats"].get(f"{p['team']}|{p['player']}")
            if v is not None:                    # did not play: void
                out.append({**p, "id": g["id"], "hit": v[IDX[p["stat"]]] >= p["line"]})
    return out


def _summary(t):
    n = len(t)
    return {"picks": n, "said": round(sum(c["chance"] for c in t) / n, 1) if n else None,
            "landed": round(100 * sum(c["hit"] for c in t) / n, 1) if n else None}


def backtest(cache, cut=None, verbose=False):
    dates = sorted(m["date"] for m in cache["matches"].values() if m.get("pstats"))
    cut = cut or dates[len(dates) // 2]
    start = dates[0]
    say = print if verbose else (lambda *a: None)
    # 1. how a player's rate is worked out, on the early games
    best = None
    for pos in (False, True):
        for k90 in (1.0, 2.0, 4.0, 8.0):
            for half in (None, 12, 6, 4, 3):
                for opp in (0.0, 0.5, 1.0):
                    prm = {**DEFAULT, "k90": k90, "half": half, "opp": opp, "pos": pos}
                    cs = _cases(cache, prm, start, cut)
                    l = _loss(cs)
                    if best is None or l < best[0]:
                        best = (l, prm, cs)
    prm, cs = dict(best[1]), best[2]
    say("rate settings", {k: prm[k] for k in ("k90", "half", "opp", "pos")}, "early loss", round(best[0], 5))
    # 2. per stat: match context (bookmakers' expected goals) and spread, same early games
    prm["own_b"], prm["opp_b"], prm["disp"], prm["ratio"] = dict(ZERO), dict(ZERO), dict(prm["disp"]), dict(prm["ratio"])
    for stat in IDX:
        sub = [c for c in cs if c["stat"] == stat]
        tries = []
        for ob in (-1.0, -0.5, 0.0, 0.5, 1.0, 1.5):
            for pb in (-1.0, -0.5, 0.0, 0.5, 1.0):
                for ratio in (False, True):
                    for r in ((1.5, 3.0, 6.0, 12.0, 50.0) if not ratio else (1.0, 2.0, 4.0, 8.0, 16.0)):
                        p2 = {**prm, "own_b": {**prm["own_b"], stat: ob}, "opp_b": {**prm["opp_b"], stat: pb},
                              "disp": {**prm["disp"], stat: r}, "ratio": {**prm["ratio"], stat: ratio}}
                        tries.append((_loss(_reprice(sub, p2)), ob, pb, r, ratio))
        l, ob, pb, r, ratio = min(tries)
        prm["own_b"][stat], prm["opp_b"][stat], prm["disp"][stat], prm["ratio"][stat] = ob, pb, r, ratio
        say(stat, "own goals power", ob, "opponent goals power", pb, "spread", r, ratio)
    # how much each improvement helps on the later games (lower = better)
    test_all = _cases(cache, prm, cut, None)
    plain = {**prm, "own_b": dict(ZERO), "opp_b": dict(ZERO)}
    losses = {"final": round(_loss(test_all), 5), "without_match_odds": round(_loss(_reprice(test_all, plain)), 5),
              "first_version": round(_loss(_cases(cache, {**DEFAULT, "half": None, "pos": False}, cut, None)), 5)}
    say("later games, average error:", losses)
    # 3. top picks run hotter than all picks (the best-looking lines are picked): measure that on the
    #    early games and take it off, then score the shown picks on the later games
    every = {f"{st}_{ln}": True for st in IDX for ln in LINES[st]}
    prm["move"] = {}
    res, show, overall = {}, {}, {}
    for mode in ("price", "safe"):
        prm["move"][mode] = {}
        early = _shown(cache, prm, every, mode, start, cut)
        for key in every:
            t = [c for c in early if f"{c['stat']}_{c['line']}" == key]
            if t:
                gap = (sum(c["hit"] for c in t) / len(t)) - sum(c["chance"] for c in t) / len(t) / 100
                prm["move"][mode][key] = round(max(-0.15, min(0.15, gap * len(t) / (len(t) + 50))), 3)
        test = _shown(cache, prm, every, mode, cut, None)
        res[mode], show[mode] = {}, {}
        for key in every:
            s = _summary([c for c in test if f"{c['stat']}_{c['line']}" == key])
            res[mode][key] = s
            n, landed, said = s["picks"], s["landed"], s["said"]
            if mode == "safe":
                show[mode][key] = bool(n >= MIN_TEST[mode] and landed >= BAR and landed >= said - 4)
            else:      # priced picks: must land about as often as they say
                show[mode][key] = bool(n >= MIN_TEST[mode] and landed >= said - 3)
        final = _shown(cache, prm, show[mode], mode, cut, None)  # again with only the lines that passed
        for key in every:
            t = [c for c in final if f"{c['stat']}_{c['line']}" == key]
            if t:
                res[mode][key]["shown"] = _summary(t)
        overall[mode] = _summary(final)
        say(mode, "shown picks on later games:", overall[mode])
    return {"params": prm, "cut": cut, "test": res, "show": show, "overall": overall, "losses": losses,
            "test_games": len({c["id"] for c in test_all})}


if __name__ == "__main__":
    import espn
    out = backtest(espn.load_cache(), verbose=True)
    PARAMS.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for mode in ("price", "safe"):
        for k, v in out["test"][mode].items():
            print(mode, k, v.get("shown") or v, out["show"][mode][k])
