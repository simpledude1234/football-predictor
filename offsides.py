"""Offsides and free kicks, from ESPN's stored match stats.

Each team gets two numbers: how often it is caught offside, and how often it
catches its opponents offside, compared with the league normal. Few games are
pulled towards normal (PRIOR games of "normal" are added to every team).
Expected home offsides = league home normal x home team's rate x away team's rate.

Free kicks = both teams' fouls + both teams' offsides (the usual bookmaker
definition). Fouls come from the main model, offsides from this one.

Run `py -3.13 offsides.py` to test it on past games and save offsides_params.json:
settings are chosen on half the games (by ESPN id) and scored on the other half, then
the other way round, so every game is scored by settings that never saw it.
"""
import datetime as dt
import json
import pathlib

import numpy as np

import predictor as P

HERE = pathlib.Path(__file__).parent
PARAMS = HERE / "offsides_params.json"
PRIOR = 5.0
MIN_GAMES = 3            # each team needs this many stored games before we tip
KEYS = ("total_offsides", "home_offsides", "away_offsides", "free_kicks")
LABELS = {"total_offsides": "Total offsides", "home_offsides": "Home offsides",
          "away_offsides": "Away offsides", "free_kicks": "Match free kicks"}


def _rows(cache):
    out = []
    for eid, m in cache.get("matches", {}).items():
        s = m.get("stats") or {}
        h, a = s.get("home") or {}, s.get("away") or {}
        if h.get("offsides") is None or a.get("offsides") is None:
            continue
        out.append({"id": eid, "slug": m["slug"], "date": m["date"], "home": m["home"], "away": m["away"],
                    "off": (h["offsides"], a["offsides"]), "fouls": (h.get("foulsCommitted"), a.get("foulsCommitted"))})
    out.sort(key=lambda r: r["date"])
    return out


class Model:
    def __init__(self, cache):
        self.rows = _rows(cache)

    def _before(self, date):
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

    def means(self, home, away, slug, date, stat="off", rows=None):
        """Expected (home, away) count for `stat` ("off" or "fouls"), using only games before `date`."""
        rows = self._before(date) if rows is None else rows
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

    def normal(self, slug, date):
        """Last year's actual values in this competition (what a normal game looks like)."""
        lo = str(dt.date.fromisoformat(date) - dt.timedelta(days=365))
        rs = [r for r in self.rows if r["slug"] == slug and lo <= r["date"] < date]
        if len(rs) < 20:
            return None
        fk = [sum(r["fouls"]) + sum(r["off"]) for r in rs if None not in r["fouls"]]
        return {"total_offsides": np.array([sum(r["off"]) for r in rs], float),
                "home_offsides": np.array([r["off"][0] for r in rs], float),
                "away_offsides": np.array([r["off"][1] for r in rs], float),
                "free_kicks": np.array(fk, float) if len(fk) >= 20 else None}


def load_params():
    return json.loads(PARAMS.read_text(encoding="utf-8")) if PARAMS.exists() else None


def add_markets(m, model, params, slug):
    """Add offsides markets to match `m` and make free kicks measured (fouls + offsides)."""
    if not params or not m.get("espn_home") or not slug:
        return
    e = model.means(m["espn_home"], m["espn_away"], slug, m["iso"])
    nm = model.normal(slug, m["iso"])
    if not e or not nm or e["games"] < MIN_GAMES:
        return
    fouls = {k["key"]: k["expected"] for k in m["markets"]}
    means = {"home_offsides": e["home"], "away_offsides": e["away"], "total_offsides": e["home"] + e["away"]}
    if fouls.get("home_fouls") is not None and fouls.get("away_fouls") is not None:
        means["free_kicks"] = fouls["home_fouls"] + fouls["away_fouls"] + means["total_offsides"]
    m["markets"] = [k for k in m["markets"] if k["key"] != "free_kicks" or "free_kicks" not in means]
    for key in KEYS:
        if key not in means or key not in params["phi"]:
            continue
        mean, ph = means[key], params["phi"][key]
        ok = params["show"].get(key, False) and nm.get(key) is not None
        ml = P.main_line(mean, ph)
        po = P.over_prob(mean, ml, ph)
        m["markets"].append({"key": key, "label": LABELS[key], "estimate": False,
                             "tip": P.best_tip(mean, ph, nm[key]) if ok else None,
                             "expected": round(mean, 2),
                             "league_avg": round(float(nm[key].mean()), 1) if nm.get(key) is not None else None,
                             "phi": ph, "line": ml, "over": round(100 * po), "under": round(100 * (1 - po)),
                             "safe_over": P.safe_over_line(mean, ph), "safe_under": P.safe_under_line(mean, ph)})


# ---------------------------------------------------------------- test
def _tips(preds, k, phi):
    hit, cl = [], []
    for p in preds:
        if p["nm"].get(k) is None:
            continue
        t = P.best_tip(p["mean"][k], phi, p["nm"][k])
        if t:
            a = p["act"][k]
            hit.append((a > t["line"]) if t["side"] == "over" else (a < t["line"]))
            cl.append(t["chance"])
    return (100 * float(np.mean(hit)), float(np.mean(cl))) if hit else (None, None)


def _fit_phi(fk, k):
    phi = P.tune_phi(np.array([p["mean"][k] for p in fk]), np.array([p["act"][k] for p in fk], float))
    for _ in range(30):            # widen the spread until tips land as often as they claim
        land, cl = _tips(fk, k, phi)
        if land is None or land >= cl - 1:
            break
        phi = round(phi + 0.05, 2)
    return phi


def backtest(cache):
    mo = Model(cache)
    rows = mo.rows
    preds = []
    for i, r in enumerate(rows):
        before = [x for x in rows[:i] if x["date"] < r["date"]]
        e = mo.means(r["home"], r["away"], r["slug"], r["date"], "off", before)
        f = mo.means(r["home"], r["away"], r["slug"], r["date"], "fouls", before)
        if not e or e["games"] < MIN_GAMES:
            continue
        mo_rows, mo.rows = mo.rows, before
        nm = mo.normal(r["slug"], r["date"])
        mo.rows = mo_rows
        if not nm:
            continue
        p = {"id": r["id"], "nm": nm,
             "mean": {"home_offsides": e["home"], "away_offsides": e["away"], "total_offsides": e["home"] + e["away"]},
             "act": {"home_offsides": r["off"][0], "away_offsides": r["off"][1], "total_offsides": sum(r["off"])}}
        if f and None not in r["fouls"]:
            p["mean"]["free_kicks"] = f["home"] + f["away"] + e["home"] + e["away"]
            p["act"]["free_kicks"] = sum(r["fouls"]) + sum(r["off"])
        preds.append(p)
    halves = ([p for p in preds if int(p["id"]) % 2 == 0], [p for p in preds if int(p["id"]) % 2 == 1])
    out = {"fitted": str(dt.date.today()), "phi": {}, "show": {}, "test": {}}
    for k in KEYS:
        n = hit = 0
        claim, base = [], []
        games = 0
        for fit, test in (halves, halves[::-1]):       # fit on one half, score the other, then swap
            phi = _fit_phi([p for p in fit if k in p["mean"]], k)
            for p in test:
                if k not in p["mean"] or p["nm"].get(k) is None:
                    continue
                games += 1
                t = P.best_tip(p["mean"][k], phi, p["nm"][k])
                if not t:
                    continue
                a = p["act"][k]
                n += 1
                hit += (a > t["line"]) if t["side"] == "over" else (a < t["line"])
                claim.append(t["chance"])
                base.append(t["normal"])
        out["phi"][k] = _fit_phi([p for p in preds if k in p["mean"]], k)    # live setting: all games
        res = {"games": games, "tips": n,
               "landed": round(100 * hit / n, 1) if n else None,
               "claimed": round(float(np.mean(claim)), 1) if n else None,
               "normal": round(float(np.mean(base)), 1) if n else None}
        out["test"][k] = res
        # show only if tips landed within 3 points of what they claimed and beat a normal game
        out["show"][k] = bool(n >= 30 and res["landed"] >= res["claimed"] - 3 and res["landed"] > res["normal"])
    return out


if __name__ == "__main__":
    import espn
    res = backtest(espn.load_cache())
    print(json.dumps(res, indent=1))
    PARAMS.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", PARAMS.name)
