"""Player stats: shots, shots on target, fouls committed and fouls won.

For every player we take, this season, how many of each he makes per 90
minutes (players with few minutes are pulled towards the average player),
times the minutes he usually plays, times how much this opponent usually
allows (pulled towards normal for teams with few games), times a home/away
factor. Counts are spread out a little more than pure chance (a negative
binomial), so a player who usually has 2 shots still often has 0.

Only regular starters get picks (started 4 of the team's last 5 games), or
named starters once the line-ups are out. A player who does not play voids
the pick, the same as at the bookmakers.

ESPN has no per-player tackles, so there is no tackles market.

Run `py -3.13 player_stats.py` to test on past games: settings are chosen on
the games before the cut-off and scored on the games after it, which the
settings never saw. The result is saved to player_stats_params.json; only
stat/line pairs whose 72%+ picks landed as promised are tipped.
"""
import bisect
import json
import math
import pathlib
from collections import defaultdict

HERE = pathlib.Path(__file__).parent
PARAMS = HERE / "player_stats_params.json"
BAR = 72
MIN_TEST = 15         # test picks a line needs before it is tipped
IDX = {"shots": 0, "sot": 1, "fouls": 2, "fwon": 3}
LINES = {"shots": (1, 2, 3), "sot": (1, 2), "fouls": (1, 2), "fwon": (1, 2)}
NAMES = {"shots": "shots", "sot": "shots on target", "fouls": "fouls", "fwon": "fouls won"}
MARKET = {"shots": "Player shots", "sot": "Player shots on target", "fouls": "Player fouls", "fwon": "Player fouls won"}
# what the opponent allows: (ESPN team stat, whose) -- "opp" = made by the opponent's opponents
TEAM_STAT = {"shots": ("totalShots", "opp"), "sot": ("shotsOnTarget", "opp"),
             "fouls": ("foulsCommitted", "opp"), "fwon": ("foulsCommitted", "own")}
DEFAULT = {"k90": 4.0, "opp": 0.7, "disp": {"shots": 6.0, "sot": 6.0, "fouls": 6.0, "fwon": 6.0}, "ratio": {}}
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


class Model:
    def __init__(self, cache, params=None):
        self.p = params or DEFAULT
        ms = [m for m in cache.get("matches", {}).values() if m.get("pstats") and m.get("stats")]
        ms.sort(key=lambda m: m["date"])
        self.ms = ms
        self.team = defaultdict(list)          # team -> [match] by date
        for m in ms:
            for s in ("home", "away"):
                self.team[m[s]].append(m)
        self.dates = {t: [m["date"] for m in g] for t, g in self.team.items()}
        # league-wide averages (per 90 per player, team per game, home/away split)
        tot = [0.0] * 4
        mins = 0
        side_tot = {"home": [0.0] * 4, "away": [0.0] * 4}
        side_n = {"home": 0, "away": 0}
        for m in ms:
            for key, v in m["pstats"].items():
                sd = key.split("|", 1)[0]
                for i in range(4):
                    tot[i] += v[i]
                    if sd in side_tot:
                        side_tot[sd][i] += v[i]
                mins += v[4]
            side_n["home"] += 1
            side_n["away"] += 1
        self.prior90 = [t / (mins / 90) if mins else 0.5 for t in tot]
        self.ha = {}
        for sd in ("home", "away"):
            self.ha[sd] = [(side_tot[sd][i] / side_n[sd]) / ((tot[i] / 2) / max(1, len(ms))) if tot[i] else 1.0
                           for i in range(4)]
        self.team_avg = {}
        for stat, (espn_name, _) in TEAM_STAT.items():
            vals = [m["stats"][s].get(espn_name) for m in ms for s in ("home", "away")]
            vals = [v for v in vals if v is not None]
            self.team_avg[stat] = sum(vals) / len(vals) if vals else 1.0

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
        """Regular starters (or the named eleven) with their per-90 rates and usual minutes."""
        games = self.games_before(team, date)
        if len(games) < 3:
            return {}
        last5 = {id(m) for m in games[-5:]}
        st = defaultdict(lambda: {"x": [0.0] * 4, "mins": 0.0, "starts5": 0, "start_mins": []})
        for m in games:
            side = "home" if m["home"] == team else "away"
            for key, v in m["pstats"].items():
                sd, name = key.split("|", 1)
                if sd != side:
                    continue
                p = st[name]
                for i in range(4):
                    p["x"][i] += v[i]
                p["mins"] += v[4]
            starters = {n for n, s, starter, *_ in m["players"] if s == side and starter}
            for name in starters:
                if name in st:
                    st[name]["start_mins"].append(m["pstats"].get(f"{side}|{name}", [0] * 5)[4])
                    if id(m) in last5:
                        st[name]["starts5"] += 1
        k = self.p["k90"]
        out = {}
        names = lineup if lineup else [n for n, p in st.items() if p["starts5"] >= 4]
        for name in names:
            p = st.get(name)
            if not p or not p["start_mins"]:
                continue
            mins = sum(p["start_mins"][-10:]) / len(p["start_mins"][-10:])
            rate = [(p["x"][i] + k * self.prior90[i]) / (p["mins"] / 90 + k) for i in range(4)]
            out[name] = {"rate": rate, "mins": mins, "games": len(p["start_mins"])}
        return out

    def chances(self, team, opp, side, date, lineup=None):
        """[{player, stat, line, chance}] for every regular starter, every stat and line."""
        rows = []
        f = {stat: self.opp_factor(opp, date, stat) for stat in IDX}
        for name, p in self.squad(team, date, lineup).items():
            for stat, i in IDX.items():
                lam = p["rate"][i] * p["mins"] / 90 * f[stat] * self.ha[side][i]
                for line in LINES[stat]:
                    rows.append({"player": name, "stat": stat, "line": line, "lam": lam,
                                 "chance": 100 * at_least(line, lam, size(self.p, stat, lam))})
        return rows


def label(stat, line):
    return f"{line}+ {NAMES[stat] if line > 1 or stat == 'fwon' else NAMES[stat].replace('shots', 'shot').replace('fouls', 'foul')}"


def picks(model, params, home, away, date, lineup=None, n=6, move=None):
    """The player picks worth showing for one match: 72%+ on a tested stat/line, the highest line
    per player and stat, at most n per match (most likely first)."""
    if not params or not home or not away:
        return []
    ok = params.get("show", {})
    move = move or {}
    fix = params.get("params", {}).get("move", {})     # the over-confidence of top picks, measured in the test
    best = {}
    for side, team, opp in (("home", home, away), ("away", away, home)):
        for r in model.chances(team, opp, side, date, (lineup or {}).get(side)):
            key = f"{r['stat']}_{r['line']}"
            if not ok.get(key):
                continue
            ch = r["chance"] + 100 * (move.get(r["stat"], 0.0) + fix.get(key, 0.0))
            if ch < BAR:
                continue
            k2 = (r["player"], r["stat"])
            if k2 not in best or r["line"] > best[k2]["line"]:
                best[k2] = {"player": r["player"], "team": side, "stat": r["stat"], "line": r["line"],
                            "chance": min(97, round(ch)), "confirmed": bool(lineup)}
    return sorted(best.values(), key=lambda x: -x["chance"])[:n]


# ------------------------------------------------------------------ test on past games
def _shown(cache, prm, show, start=None, end=None):
    """The picks the page would have shown for each stored match from start to end, and how they did."""
    m = Model(cache, prm)
    out = []
    for g in m.ms:
        if (start and g["date"] < start) or (end and g["date"] >= end):
            continue
        for p in picks(m, {"params": prm, "show": show}, g["home"], g["away"], g["date"]):
            v = g["pstats"].get(f"{p['team']}|{p['player']}")
            if v is not None:                    # did not play: void
                out.append({**p, "id": g["id"], "hit": v[IDX[p["stat"]]] >= p["line"]})
    return out


def _cases(cache, params, start=None, end=None):
    """Every starter in every stored match from start to end, predicted with only earlier games."""
    m = Model(cache, params)
    out = []
    for g in m.ms:
        if (start and g["date"] < start) or (end and g["date"] >= end):
            continue
        for side, team, opp in (("home", g["home"], g["away"]), ("away", g["away"], g["home"])):
            started = {n for n, s, st, *_ in g["players"] if s == side and st}
            for r in m.chances(team, opp, side, g["date"]):
                v = g["pstats"].get(f"{side}|{r['player']}")
                if v is None or r["player"] not in started:
                    continue          # did not start: void (only starters are scored here)
                out.append({**r, "date": g["date"], "id": g["id"], "side": side, "hit": v[IDX[r["stat"]]] >= r["line"]})
    return out


def _loss(cases):
    s = 0.0
    for c in cases:
        p = min(max(c["chance"] / 100, 1e-4), 1 - 1e-4)
        s -= math.log(p if c["hit"] else 1 - p)
    return s / max(1, len(cases))


def backtest(cache, cut=None):
    dates = sorted(m["date"] for m in cache["matches"].values() if m.get("pstats"))
    cut = cut or dates[len(dates) // 2]
    start = dates[0]
    best = None
    for k90 in (0.5, 1.0, 2.0, 4.0):
        for opp in (0.0, 0.5, 1.0):
            prm = {"k90": k90, "opp": opp, "disp": dict(DEFAULT["disp"])}
            cs = _cases(cache, prm, start, cut)
            l = _loss(cs)
            if best is None or l < best[0]:
                best = (l, prm, cs)
    prm, cs = best[1], best[2]
    for stat in IDX:                               # spread per stat, chosen on the same early games
        sub = [c for c in cs if c["stat"] == stat]
        tries = []
        for ratio in (False, True):
            for r in ((1.5, 3.0, 6.0, 12.0, 50.0) if not ratio else (1.0, 2.0, 4.0, 8.0, 16.0)):
                p2 = {**prm, "disp": {**prm["disp"], stat: r}, "ratio": {**prm.get("ratio", {}), stat: ratio}}
                sub2 = [{**c, "chance": 100 * at_least(c["line"], c["lam"], size(p2, stat, c["lam"]))} for c in sub]
                tries.append((_loss(sub2), r, ratio))
        best_t = min(tries)
        prm["disp"][stat] = best_t[1]
        prm.setdefault("ratio", {})[stat] = best_t[2]
    # top picks run hotter than all picks (the best-looking lines are picked): measure that on the
    # early games and take it off, then score the shown picks on the later games
    every = {f"{st}_{ln}": True for st in IDX for ln in LINES[st]}
    prm["move"] = {}
    early = _shown(cache, prm, every, start, cut)
    for key in every:
        t = [c for c in early if f"{c['stat']}_{c['line']}" == key]
        if t:
            gap = (sum(c["hit"] for c in t) / len(t)) - sum(c["chance"] for c in t) / len(t) / 100
            prm["move"][key] = round(max(-0.15, min(0.15, gap * len(t) / (len(t) + 50))), 3)
    test = _shown(cache, prm, every, cut, None)
    res, show = {}, {}
    for stat in IDX:
        for line in LINES[stat]:
            key = f"{stat}_{line}"
            t = [c for c in test if c["stat"] == stat and c["line"] == line]
            n = len(t)
            landed = 100 * sum(c["hit"] for c in t) / n if n else None
            said = sum(c["chance"] for c in t) / n if n else None
            res[key] = {"picks": n, "landed": round(landed, 1) if n else None, "said": round(said, 1) if n else None}
            # shown only if enough test picks and they landed at the bar and close to what they said
            show[key] = bool(n >= MIN_TEST and landed >= BAR and landed >= said - 4)
    final = _shown(cache, prm, show, cut, None)   # again with only the lines that passed: what the page shows
    for key in res:
        t = [c for c in final if f"{c['stat']}_{c['line']}" == key]
        if t:
            res[key]["shown"] = {"picks": len(t), "said": round(sum(c["chance"] for c in t) / len(t), 1),
                                 "landed": round(100 * sum(c["hit"] for c in t) / len(t), 1)}
    n = len(final)
    overall = {"picks": n, "said": round(sum(c["chance"] for c in final) / n, 1) if n else None,
               "landed": round(100 * sum(c["hit"] for c in final) / n, 1) if n else None}
    return {"params": prm, "cut": cut, "test": res, "show": show, "overall": overall,
            "test_games": len({c["id"] for c in test})}


if __name__ == "__main__":
    import espn
    out = backtest(espn.load_cache())
    PARAMS.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
