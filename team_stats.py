"""Offsides, corners, tackles and free kicks, from ESPN's stored match stats.

For each stat every team gets two numbers: how many it makes (offsides it is
caught in, corners it wins, tackles it makes) and how many its opponents make,
both compared with the league normal. Teams with few games are pulled towards
normal (PRIOR games of "normal" are added to every team).
Expected home count = league home normal x home team's rate x away team's "allowed" rate.

Free kicks = both teams' fouls + both teams' offsides (the usual bookmaker
definition). Fouls come from the main model, offsides from this one.

Run `py -3.13 team_stats.py` to test it on past games and save team_stats_params.json:
settings are chosen on half the games (by ESPN id) and scored on the other half, then
the other way round, so every game is scored by settings that never saw it.
"""
import datetime as dt
import json
import pathlib

import numpy as np

import predictor as P

HERE = pathlib.Path(__file__).parent
PARAMS = HERE / "team_stats_params.json"
PRIOR = 5.0
MIN_GAMES = 3            # each team needs this many stored games before we tip
# stat in our rows -> (ESPN name, market name)
STATS = {"off": ("offsides", "offsides"), "corners": ("wonCorners", "corners"), "tackles": ("totalTackles", "tackles")}
KEYS = tuple(f"{w}_{name}" for _, name in STATS.values() for w in ("total", "home", "away")) + ("free_kicks",)
LABELS = {**{f"{w}_{name}": f"{w.title()} {name}" for _, name in STATS.values() for w in ("total", "home", "away")},
          "free_kicks": "Match free kicks"}


def _rows(cache):
    out = []
    for eid, m in cache.get("matches", {}).items():
        s = m.get("stats") or {}
        h, a = s.get("home") or {}, s.get("away") or {}
        if not h or not a:
            continue
        r = {"id": eid, "slug": m["slug"], "date": m["date"], "home": m["home"], "away": m["away"],
             "fouls": (h.get("foulsCommitted"), a.get("foulsCommitted"))}
        if None in r["fouls"]:
            r["fouls"] = (None, None)
        for st, (espn_name, _) in STATS.items():
            v = (h.get(espn_name), a.get(espn_name))
            r[st] = v if None not in v else (None, None)
        out.append(r)
    out.sort(key=lambda r: r["date"])
    return out


class Model:
    def __init__(self, cache):
        self.rows = _rows(cache)

    def before(self, date):
        return [r for r in self.rows if r["date"] < date]

    @staticmethod
    def _norm(rows, slug, date, stat):
        lo = str(dt.date.fromisoformat(date) - dt.timedelta(days=365))
        rs = [r for r in rows if r["slug"] == slug and r["date"] >= lo and r[stat][0] is not None]
        if len(rs) < 20:
            rs = [r for r in rows if r[stat][0] is not None]
        if not rs:
            return None
        return (float(np.mean([r[stat][0] for r in rs])), float(np.mean([r[stat][1] for r in rs])))

    def means(self, home, away, slug, date, stat, rows=None):
        """Expected (home, away) count for `stat` ("off", "corners", "tackles" or "fouls"),
        using only games before `date`."""
        rows = self.before(date) if rows is None else rows
        lg = self._norm(rows, slug, date, stat)
        if lg is None:
            return None
        norms = {}

        def rate(team):
            made = base_m = conc = base_c = 0.0
            n = 0
            for r in rows:
                if team not in (r["home"], r["away"]) or r[stat][0] is None:
                    continue
                if r["slug"] not in norms:
                    norms[r["slug"]] = self._norm(rows, r["slug"], date, stat) or lg
                nh, na = norms[r["slug"]]
                me = 0 if r["home"] == team else 1
                made += r[stat][me]
                base_m += (nh, na)[me]
                conc += r[stat][1 - me]
                base_c += (nh, na)[1 - me]
                n += 1
            per = (lg[0] + lg[1]) / 2
            return ((made + PRIOR * per) / (base_m + PRIOR * per), (conc + PRIOR * per) / (base_c + PRIOR * per), n)

        ah, ch, nh_ = rate(home)
        aa, ca, na_ = rate(away)
        return {"home": lg[0] * ah * ca, "away": lg[1] * aa * ch, "games": min(nh_, na_), "norm": lg}

    def normal(self, slug, date, rows=None):
        """Last year's actual values in this competition (what a normal game looks like)."""
        lo = str(dt.date.fromisoformat(date) - dt.timedelta(days=365))
        rows = self.rows if rows is None else rows
        rs = [r for r in rows if r["slug"] == slug and lo <= r["date"] < date]
        out = {}
        for st, (_, name) in STATS.items():
            v = [r[st] for r in rs if r[st][0] is not None]
            if len(v) >= 20:
                out[f"total_{name}"] = np.array([x[0] + x[1] for x in v], float)
                out[f"home_{name}"] = np.array([x[0] for x in v], float)
                out[f"away_{name}"] = np.array([x[1] for x in v], float)
        fk = [sum(r["fouls"]) + sum(r["off"]) for r in rs if r["fouls"][0] is not None and r["off"][0] is not None]
        if len(fk) >= 20:
            out["free_kicks"] = np.array(fk, float)
        return out


def _means_for(model, home, away, slug, date, rows):
    out = {}
    for st, (_, name) in STATS.items():
        e = model.means(home, away, slug, date, st, rows)
        if e and e["games"] >= MIN_GAMES:
            out.update({f"home_{name}": e["home"], f"away_{name}": e["away"], f"total_{name}": e["home"] + e["away"]})
    return out


def load_params():
    return json.loads(PARAMS.read_text(encoding="utf-8")) if PARAMS.exists() else None


def add_markets(m, model, params, slug):
    """Add offsides, corners and tackles markets to match `m`, and make free kicks measured (fouls + offsides)."""
    if not params or not m.get("espn_home") or not slug:
        return
    nm = model.normal(slug, m["iso"])
    means = _means_for(model, m["espn_home"], m["espn_away"], slug, m["iso"], model.before(m["iso"]))
    fouls = {k["key"]: k["expected"] for k in m["markets"]}
    if "total_offsides" in means and fouls.get("home_fouls") is not None and fouls.get("away_fouls") is not None:
        means["free_kicks"] = fouls["home_fouls"] + fouls["away_fouls"] + means["total_offsides"]
    if "free_kicks" in means and "free_kicks" in nm:
        m["markets"] = [k for k in m["markets"] if k["key"] != "free_kicks"]   # replaces the old estimate
    for key in KEYS:
        if key not in means or key not in nm or key not in params["phi"]:
            continue
        mean, ph = means[key], params["phi"][key]
        ml = P.main_line(mean, ph)
        po = P.over_prob(mean, ml, ph)
        m["markets"].append({"key": key, "label": LABELS[key], "estimate": False,
                             "tip": P.best_tip(mean, ph, nm[key]) if params["show"].get(key) else None,
                             "even_line": P.even_line(nm[key]),
                             "expected": round(mean, 2), "league_avg": round(float(nm[key].mean()), 1),
                             "phi": ph, "line": ml, "over": round(100 * po), "under": round(100 * (1 - po)),
                             "safe_over": P.safe_over_line(mean, ph), "safe_under": P.safe_under_line(mean, ph)})


# ---------------------------------------------------------------- test
_LINES = np.array(P.LINES)
_K = np.floor(_LINES)


def _fast_tip(mean, phi, base_over):
    """Same rule as predictor.best_tip, all lines at once (the test calls it many thousands of times).
    base_over: how often each line normally goes over."""
    po = P.over_prob_vec(np.full(len(_LINES), float(mean)), _K, phi)
    ch = np.empty(2 * len(_LINES))
    base = np.empty(2 * len(_LINES))
    ch[0::2], ch[1::2] = po, 1 - po                  # same order as best_tip: over then under, line by line
    base[0::2], base[1::2] = base_over, 1 - base_over
    edge = np.where((ch >= P.SAFE) & (base < 0.97) & (ch - base >= P.EDGE), ch - base, -np.inf)
    i = int(np.argmax(edge))
    if not np.isfinite(edge[i]):
        return None
    return {"side": "over" if i % 2 == 0 else "under", "line": float(_LINES[i // 2]),
            "chance": round(100 * ch[i]), "normal": round(100 * base[i])}


def _usable(preds, k):
    return [p for p in preds if k in p["mean"] and k in p["nm"]]


def _tips(preds, k, phi):
    hit, cl = [], []
    for p in _usable(preds, k):
        t = _fast_tip(p["mean"][k], phi, p["bo"][k])
        if t:
            a = p["act"][k]
            hit.append((a > t["line"]) if t["side"] == "over" else (a < t["line"]))
            cl.append(t["chance"])
    return (100 * float(np.mean(hit)), float(np.mean(cl))) if hit else (None, None)


def _fit_phi(preds, k):
    fk = _usable(preds, k)
    phi = P.tune_phi(np.array([p["mean"][k] for p in fk]), np.array([p["act"][k] for p in fk], float))
    for _ in range(30):            # widen the spread until tips land as often as they claim
        land, cl = _tips(fk, k, phi)
        if land is None or land >= cl - 1:
            break
        phi = round(phi + 0.05, 2)
    return phi


def test_preds(cache):
    """Every stored game predicted from only the games before it."""
    mo = Model(cache)
    rows = mo.rows
    preds = []
    for i, r in enumerate(rows):
        before = [x for x in rows[:i] if x["date"] < r["date"]]
        nm = mo.normal(r["slug"], r["date"], before)
        mean = _means_for(mo, r["home"], r["away"], r["slug"], r["date"], before)
        act = {}
        for st, (_, name) in STATS.items():
            if r[st][0] is not None:
                act.update({f"home_{name}": r[st][0], f"away_{name}": r[st][1], f"total_{name}": sum(r[st])})
        f = mo.means(r["home"], r["away"], r["slug"], r["date"], "fouls", before)
        if f and r["fouls"][0] is not None and "total_offsides" in mean and "total_offsides" in act:
            mean["free_kicks"] = f["home"] + f["away"] + mean["total_offsides"]
            act["free_kicks"] = sum(r["fouls"]) + act["total_offsides"]
        mean = {k: v for k, v in mean.items() if k in act}
        if mean:
            preds.append({"id": r["id"], "nm": nm, "mean": mean, "act": act,
                          "bo": {k: (v[:, None] > _LINES).mean(0) for k, v in nm.items()}})
    return preds


def backtest(cache, preds=None):
    preds = test_preds(cache) if preds is None else preds
    halves = ([p for p in preds if int(p["id"]) % 2 == 0], [p for p in preds if int(p["id"]) % 2 == 1])
    out = {"fitted": str(dt.date.today()), "phi": {}, "show": {}, "test": {}}
    for k in KEYS:
        n = hit = games = 0
        claim, base = [], []
        for fit, test in (halves, halves[::-1]):       # fit on one half, score the other, then swap
            phi = _fit_phi(fit, k)
            for p in _usable(test, k):
                games += 1
                t = _fast_tip(p["mean"][k], phi, p["bo"][k])
                if not t:
                    continue
                a = p["act"][k]
                n += 1
                hit += (a > t["line"]) if t["side"] == "over" else (a < t["line"])
                claim.append(t["chance"])
                base.append(t["normal"])
        out["phi"][k] = _fit_phi(preds, k)    # live setting: all games
        res = {"games": games, "tips": n,
               "landed": round(100 * hit / n, 1) if n else None,
               "claimed": round(float(np.mean(claim)), 1) if n else None,
               "normal": round(float(np.mean(base)), 1) if n else None}
        out["test"][k] = res
        # show only if, on games the settings never saw, tips cleared the site's own bar:
        # landed at least 72% of the time and at least 5 points more often than in a normal game
        out["show"][k] = bool(n >= 30 and res["landed"] >= 100 * P.SAFE and res["landed"] - res["normal"] >= 100 * P.EDGE)
    return out


if __name__ == "__main__":
    import espn
    res = backtest(espn.load_cache())
    print(json.dumps(res["test"], indent=1))
    print("show:", res["show"])
    PARAMS.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", PARAMS.name)
