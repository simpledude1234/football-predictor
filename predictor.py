"""Prediction engine.

How it works (plain English):
1. Team ratings: every team gets a "for" and "against" rating for shots,
   shots on target, fouls, cards and goals, compared with the league average.
   Recent matches count more (a match 5 months old counts half), and teams
   with few matches are pulled towards average.
2. Bookmaker read: from the match-result and over/under 2.5 odds we work out
   how many goals the bookmakers expect from each team. That number carries a
   lot of information (team news, form, motivation).
3. Final number for each market = a small formula that combines (1) and (2),
   fitted on past seasons and checked on matches it never saw.
4. Expected numbers become over/under chances using the spread measured in
   past results.
"""
import json
import math
import pathlib

import numpy as np

import learn
import referees
import pandas as pd
from scipy import optimize, stats

from fetch_data import DATA, LEAGUES, season_codes

HERE = pathlib.Path(__file__).parent
PARAMS_FILE = HERE / "model_params.json"
LEARNED = learn.load()             # corrections learned from the track record (learn.py)

HALF_LIFE_DAYS = 150
PRIOR_MATCHES = 5.0
REF_PRIOR = 8.0
GK_BASE, GK_PER_MISS = 2.5, 0.55   # goal kicks ~ 2.5 + 0.55 x opponent off-target shots
OFFSIDES_PER_MATCH = 3.6           # free kicks = fouls + offsides (offsides not in free data)
DC_RHO = -0.08
SAFE = 0.72                        # "safer tip" = at least 72% chance
MIN_PRICE = 1.20                   # ...but no tip worth less than 1.20 (e.g. "bookings over 0.5")
MAX_SAFE = 1 / MIN_PRICE           # = 83%
EDGE = 0.05                        # a tip must beat how often its line normally lands by 5+ points
LINES = [x + 0.5 for x in range(0, 45)]

BASE = {
    "goals": ("FTHG", "FTAG"), "shots": ("HS", "AS"), "sot": ("HST", "AST"),
    "fouls": ("HF", "AF"), "cards": ("HCARD", "ACARD"), "miss": ("HMISS", "AMISS"),
}

# market -> (label, estimated?, which side the bookmaker goals feature belongs to)
MARKETS = {
    "total_shots": ("Total match shots", False, "total"),
    "total_sot": ("Total shots on target", False, "total"),
    "home_sot": ("Home shots on target", False, "home"),
    "away_sot": ("Away shots on target", False, "away"),
    "home_cards": ("Home bookings (cards)", False, "home"),
    "away_cards": ("Away bookings (cards)", False, "away"),
    "total_cards": ("Total match bookings (cards)", False, "total"),
    "home_fouls": ("Home fouls", False, "home"),
    "away_fouls": ("Away fouls", False, "away"),
    "home_gk": ("Home goal kicks", True, "home"),
    "away_gk": ("Away goal kicks", True, "away"),
    "free_kicks": ("Match free kicks", True, "total"),
}
MEASURED = [k for k, v in MARKETS.items() if not v[1]]


def actual_values(r):
    return {
        "total_shots": r.HS + r.AS, "total_sot": r.HST + r.AST,
        "home_sot": r.HST, "away_sot": r.AST,
        "home_cards": r.HCARD, "away_cards": r.ACARD, "total_cards": r.HCARD + r.ACARD,
        "home_fouls": r.HF, "away_fouls": r.AF,
    }


# ---------------------------------------------------------------- data
def load_league(code):
    frames = []
    for s in season_codes():
        p = DATA / f"{code}_{s}.csv"
        if p.exists() and p.stat().st_size > 100:
            frames.append(pd.read_csv(p, encoding="utf-8-sig", encoding_errors="replace"))
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "FTHG", "HS", "HST", "HF", "HY"]).copy()
    if "Referee" not in df:
        df["Referee"] = np.nan
    # sanity check: throw away rows with impossible numbers (bad or tampered data)
    limits = {"FTHG": 15, "FTAG": 15, "HS": 60, "AS": 60, "HST": 30, "AST": 30,
              "HF": 45, "AF": 45, "HY": 10, "AY": 10, "HR": 5, "AR": 5}
    for c, hi in limits.items():
        df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df[(df[c].isna() & c.endswith("R")) | df[c].between(0, hi)]
    df = df[(df.HST <= df.HS) & (df.AST <= df.AS)].copy()
    referees.fill(df, code)            # referee names where our data has none (Italy, Spain, Germany, France)
    df = df.assign(HCARD=df.HY + df.HR.fillna(0), ACARD=df.AY + df.AR.fillna(0),
                   HMISS=df.HS - df.HST, AMISS=df.AS - df.AST)
    return df.sort_values("Date").reset_index(drop=True)


def load_fixtures():
    fx = pd.read_csv(DATA / "fixtures.csv", encoding="utf-8-sig", encoding_errors="replace")
    fx = fx[fx.Div.isin(LEAGUES)].copy()
    fx["Date"] = pd.to_datetime(fx["Date"], dayfirst=True, errors="coerce")
    return fx


# ---------------------------------------------------------------- team ratings
def team_rates(hist, home, away, date):
    age = (date - hist.Date).dt.days.to_numpy()
    w = 0.5 ** (age / HALF_LIFE_DAYS)
    hm_h, am_h = (hist.HomeTeam == home).to_numpy(), (hist.AwayTeam == home).to_numpy()
    hm_a, am_a = (hist.HomeTeam == away).to_numpy(), (hist.AwayTeam == away).to_numpy()
    out = {}
    for stat, (hc, ac) in BASE.items():
        xh, xa = hist[hc].to_numpy(float), hist[ac].to_numpy(float)
        mu_h, mu_a = np.sum(w * xh) / w.sum(), np.sum(w * xa) / w.sum()
        m = (mu_h + mu_a) / 2 * PRIOR_MATCHES

        def rating(hm, am):
            f = np.sum(w[hm] * xh[hm]) + np.sum(w[am] * xa[am])
            fe = mu_h * w[hm].sum() + mu_a * w[am].sum()
            a = np.sum(w[hm] * xa[hm]) + np.sum(w[am] * xh[am])
            ae = mu_a * w[hm].sum() + mu_h * w[am].sum()
            return (f + m) / (fe + m), (a + m) / (ae + m)

        att_h, def_h = rating(hm_h, am_h)
        att_a, def_a = rating(hm_a, am_a)
        out[stat] = (mu_h * att_h * def_a, mu_a * att_a * def_h)
        out[stat + "_avg"] = (mu_h, mu_a)
    return out


def referee_factor(hist, ref, date):
    if not isinstance(ref, str) or not ref.strip():
        return 1.0
    age = (date - hist.Date).dt.days.to_numpy()
    w = 0.5 ** (age / (HALF_LIFE_DAYS * 2))
    tot = (hist.HCARD + hist.ACARD).to_numpy(float)
    avg = np.sum(w * tot) / w.sum()
    mk = (hist.Referee == ref).to_numpy()
    return float((np.sum(w[mk] * tot[mk]) + REF_PRIOR * avg) / (avg * w[mk].sum() + REF_PRIOR * avg))


def base_means(r, ref_mult=1.0):
    sh, sot, fo, ca, mi, go = (r[k] for k in ["shots", "sot", "fouls", "cards", "miss", "goals"])
    hc, ac = ca[0] * ref_mult, ca[1] * ref_mult
    lam_h = 0.6 * go[0] + 0.4 * sot[0] * r["goals_avg"][0] / r["sot_avg"][0]
    lam_a = 0.6 * go[1] + 0.4 * sot[1] * r["goals_avg"][1] / r["sot_avg"][1]
    return {
        "total_shots": sh[0] + sh[1], "total_sot": sot[0] + sot[1],
        "home_sot": sot[0], "away_sot": sot[1],
        "home_cards": hc, "away_cards": ac, "total_cards": hc + ac,
        "home_fouls": fo[0], "away_fouls": fo[1],
        "home_miss": mi[0], "away_miss": mi[1],
        "lam_h": lam_h, "lam_a": lam_a,
    }


# ---------------------------------------------------------------- goals
def score_matrix(lh, la, n=11):
    ph = stats.poisson.pmf(np.arange(n), lh)
    pa = stats.poisson.pmf(np.arange(n), la)
    m = np.outer(ph, pa)
    m[0, 0] *= 1 - lh * la * DC_RHO
    m[0, 1] *= 1 + lh * DC_RHO
    m[1, 0] *= 1 + la * DC_RHO
    m[1, 1] *= 1 - DC_RHO
    return m / m.sum()


def outcome_probs(lh, la):
    m = score_matrix(lh, la)
    tot = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
    return {"H": float(np.tril(m, -1).sum()), "D": float(np.trace(m)),
            "A": float(np.triu(m, 1).sum()), "BTTS": float(m[1:, 1:].sum()),
            "O25": float(m[tot > 2.5].sum())}


def market_probs(row):
    res = ou = None
    for p in ["Avg", "B365", "P", "Max"]:
        cols = [p + "H", p + "D", p + "A"]
        if all(c in row and pd.notna(row[c]) and row[c] > 1 for c in cols):
            inv = np.array([1 / row[c] for c in cols])
            res = dict(zip("HDA", inv / inv.sum()))
            break
    for p in ["Avg", "B365", "P", "Max"]:
        o, u = p + ">2.5", p + "<2.5"
        if o in row and u in row and pd.notna(row[o]) and pd.notna(row[u]) and row[o] > 1:
            io, iu = 1 / row[o], 1 / row[u]
            ou = io / (io + iu)
            break
    return res, ou


def market_lambdas(res, ou):
    """Goals the bookmakers expect from each team, read from their odds."""
    def err(x):
        lh, la = np.exp(x)
        p = outcome_probs(lh, la)
        return (p["H"] - res["H"]) ** 2 + (p["A"] - res["A"]) ** 2 + (p["O25"] - ou) ** 2
    sol = optimize.minimize(err, np.log([1.4, 1.1]), method="Nelder-Mead",
                            options={"xatol": 1e-3, "fatol": 1e-7})
    return tuple(float(v) for v in np.exp(sol.x))


# ---------------------------------------------------------------- distribution
def over_prob(mean, line, phi):
    """P(X > line). phi = spread (variance / mean) measured from past results."""
    k = math.floor(line)
    if phi is None or abs(phi - 1) < 0.03:
        return float(stats.poisson.sf(k, mean))
    if phi > 1:
        size = mean / (phi - 1)
        return float(stats.nbinom.sf(k, size, size / (size + mean)))
    p = 1 - phi                      # tighter than Poisson -> binomial shape
    n = max(int(round(mean / p)), k + 1)
    return float(stats.binom.sf(k, n, mean / n))


def main_line(mean, phi):
    return min(LINES, key=lambda L: abs(over_prob(mean, L, phi) - 0.5))


def safe_over_line(mean, phi):
    best = None
    for L in LINES:
        if over_prob(mean, L, phi) >= SAFE:
            best = L
        else:
            break
    return best


def safe_under_line(mean, phi):
    for L in LINES:
        if 1 - over_prob(mean, L, phi) >= SAFE:
            return L
    return None


def best_tip(mean, phi, normal, key=None):
    """The line where this game stands out most from a normal game in the league.
    normal: last year's actual values in the league for this market.
    Our chance must be at least 72% (but at most 83%, so the tip is worth 1.20+)
    and at least 5 points above how often the line normally lands; otherwise no
    tip (a normal game tells us nothing).
    Tested on 90 days of replays: 62% of games got a tip; they landed 79.8%
    against 66.9% normally (the old way: 78.9% against 70.6%)."""
    if normal is None or not len(normal):
        return None
    move, hide = learn.adjust("safe", key, LEARNED) if key else (0.0, False)
    if hide:                       # this market's recent tips fell below the bar: no tip for now
        return None
    best = None
    for L in LINES:
        po, bo = over_prob(mean, L, phi), float((normal > L).mean())
        for side, ch, base in (("over", po + move, bo), ("under", 1 - po + move, 1 - bo)):
            if SAFE <= ch <= MAX_SAFE and base < 0.97 and ch - base >= EDGE and (best is None or ch - base > best[2] - best[3]):
                best = (side, L, ch, base)
    if best is None:
        return None
    return {"side": best[0], "line": best[1], "chance": round(100 * best[2]), "normal": round(100 * best[3])}


STAT_OF = {"total_shots": ("shots", "total"), "total_sot": ("sot", "total"), "home_sot": ("sot", "home"),
           "away_sot": ("sot", "away"), "home_cards": ("cards", "home"), "away_cards": ("cards", "away"),
           "total_cards": ("cards", "total"), "home_fouls": ("fouls", "home"), "away_fouls": ("fouls", "away")}
PLAIN_GAMES = 10


def plain_means(hist, home, away, date):
    """What a bookmaker working from plain recent form would expect for each stat:
    each team's last 10 games (made and allowed), with the league's home/away split.
    Used to set a game's "bookmaker line" for the higher-price picks. None if too few games."""
    def last(team):
        g = hist[(hist.HomeTeam == team) | (hist.AwayTeam == team)].tail(PLAIN_GAMES)
        return g if len(g) >= 3 else None
    gh, ga = last(home), last(away)
    if gh is None or ga is None:
        return None
    recent = hist[hist.Date >= date - pd.Timedelta(days=365)]
    out = {}
    for s in ("shots", "sot", "fouls", "cards"):
        hc, ac = BASE[s]
        lh, la = float(recent[hc].mean()), float(recent[ac].mean())
        per = (lh + la) / 2

        def made(g, t):
            return float(np.where(g.HomeTeam == t, g[hc], g[ac]).mean())

        def allowed(g, t):
            return float(np.where(g.HomeTeam == t, g[ac], g[hc]).mean())
        out[s] = ((made(gh, home) + allowed(ga, away)) / 2 * lh / per,
                  (made(ga, away) + allowed(gh, home)) / 2 * la / per)
    return out


def plain_mean_for(key, pm):
    s, side = STAT_OF[key]
    h, a = pm[s]
    return h + a if side == "total" else (h if side == "home" else a)


def book_line(key, pm, phi):
    """The line a plain-form bookmaker would set for this game (both sides near evens)."""
    if not pm or key not in STAT_OF:
        return None
    return main_line(plain_mean_for(key, pm), phi)


def normal_values(recent):
    """Last year's actual values for each measured market (what a normal game looks like)."""
    return {k: v.to_numpy(float) for k, v in actual_values(recent).items()}


# ---------------------------------------------------------------- final formula
def features(k, bm, mlh, mla):
    side = MARKETS[k][2]
    g = mlh + mla if side == "total" else (mlh if side == "home" else mla)
    return np.array([1.0, bm[k], g, abs(mlh - mla)])


def final_mean(k, bm, mlh, mla, coefs):
    if mlh is None or k not in coefs:
        return bm[k]
    return max(0.2, float(features(k, bm, mlh, mla) @ np.array(coefs[k])))


def derived_means(bm, sot_final):
    """Estimated markets built from the measured ones."""
    miss_h = bm["home_miss"] * (sot_final[0] / bm["home_sot"]) if bm["home_sot"] else bm["home_miss"]
    miss_a = bm["away_miss"] * (sot_final[1] / bm["away_sot"]) if bm["away_sot"] else bm["away_miss"]
    return {"home_gk": GK_BASE + GK_PER_MISS * miss_a, "away_gk": GK_BASE + GK_PER_MISS * miss_h}


# ---------------------------------------------------------------- backtest
def backtest(eval_seasons=2):
    seasons = season_codes()
    rows = []
    first_eval = pd.Timestamp(f"20{seasons[eval_seasons - 1][:2]}-07-01")
    for code in LEAGUES:
        df = load_league(code)
        for i in np.where(df.Date >= first_eval)[0]:
            r = df.iloc[i]
            hist = df[df.Date < r.Date]
            if len(hist) < 100:
                continue
            bm = base_means(team_rates(hist, r.HomeTeam, r.AwayTeam, r.Date),
                            referee_factor(hist, r.Referee, r.Date))
            rec = {"league": code, "date": r.Date, "home": r.HomeTeam, "away": r.AwayTeam}
            for k, v in actual_values(r).items():
                rec[k + "_base"], rec[k + "_act"] = bm[k], v
            op = outcome_probs(bm["lam_h"], bm["lam_a"])
            rec.update({"pH": op["H"], "pD": op["D"], "pA": op["A"], "pBTTS": op["BTTS"],
                        "res": r.FTR, "btts": int(r.FTHG > 0 and r.FTAG > 0)})
            res, ou = market_probs(r)
            if res and ou:
                mlh, mla = market_lambdas(res, ou)
                mo = outcome_probs(mlh, mla)
                rec.update({"mH": res["H"], "mD": res["D"], "mA": res["A"], "mBTTS": mo["BTTS"],
                            "mlh": mlh, "mla": mla})
            rows.append(rec)
        print(f"backtest {code}: {len(rows)} matches so far", flush=True)
    return pd.DataFrame(rows)


def over_prob_vec(mean, k, phi):
    """Same as over_prob, for many matches at once (k = whole-number part of the line)."""
    if abs(phi - 1) < 0.03:
        return stats.poisson.sf(k, mean)
    if phi > 1:
        size = mean / (phi - 1)
        return stats.nbinom.sf(k, size, size / (size + mean))
    p = 1 - phi
    n = np.maximum(np.round(mean / p), k + 1)
    return stats.binom.sf(k, n, mean / n)


def tune_phi(pred, act):
    best = None
    for phi in np.arange(0.6, 2.01, 0.05):
        loss = 0.0
        for off in (-2, -1, 0, 1, 2):
            k = np.maximum(np.floor(pred) + off, 0)
            p = np.clip(over_prob_vec(pred, k, phi), 1e-6, 1 - 1e-6)
            y = act > k
            loss += -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
        if best is None or loss < best[1]:
            best = (float(round(phi, 2)), loss)
    return best[0]


def logloss(p, y):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def fit_params(bt):
    """Fit the final formula on older matches, then check it on newer ones it never saw."""
    bt = bt.sort_values("date").reset_index(drop=True)
    bt = bt.dropna(subset=["mlh"]).reset_index(drop=True)
    cut = int(len(bt) * 0.6)
    train, test = bt.iloc[:cut], bt.iloc[cut:]
    params = {"coefs": {}, "phi": {}, "report": {"matches_tested": int(len(test)),
              "test_period": f"{test.date.min():%d %b %Y} to {test.date.max():%d %b %Y}"}}

    def design(d, k):
        side = MARKETS[k][2]
        g = d.mlh + d.mla if side == "total" else (d.mlh if side == "home" else d.mla)
        return np.column_stack([np.ones(len(d)), d[k + "_base"], g, (d.mlh - d.mla).abs()])

    rep = {}
    for k in MEASURED:
        X, y = design(train, k), train[k + "_act"].to_numpy(float)
        coef, *_ = np.linalg.lstsq(X, y, rcond=None)
        pred = np.maximum(design(test, k) @ coef, 0.2)
        act = test[k + "_act"].to_numpy(float)
        avg = train.groupby("league")[k + "_act"].mean()
        base_avg = test.league.map(avg).to_numpy()
        rep[k] = {"avg_miss_final": round(float(np.mean(np.abs(act - pred))), 2),
                  "avg_miss_ratings_only": round(float(np.mean(np.abs(act - test[k + "_base"]))), 2),
                  "avg_miss_league_average": round(float(np.mean(np.abs(act - base_avg))), 2)}
        # refit on all data for live use; spread measured on the unseen part
        coef_all, *_ = np.linalg.lstsq(design(bt, k), bt[k + "_act"].to_numpy(float), rcond=None)
        params["coefs"][k] = [float(c) for c in coef_all]
        # spread: pick the value that gave the most accurate over/under chances
        # on the older matches, then check it on the newer ones below
        pred_tr = np.maximum(design(train, k) @ coef, 0.2)
        act_tr = train[k + "_act"].to_numpy(float)
        params["phi"][k] = tune_phi(pred_tr, act_tr)
        # calibration of "safer" tips on unseen matches
        n = hits = 0
        probs = []
        for p_, a_ in zip(pred, act):
            L = safe_over_line(p_, params["phi"][k])
            if L is not None:
                n += 1
                hits += a_ > L
                probs.append(over_prob(p_, L, params["phi"][k]))
        rep[k]["safer_over_tips"] = n
        rep[k]["safer_over_promised_%"] = round(100 * float(np.mean(probs)), 1) if probs else None
        rep[k]["safer_over_hit_%"] = round(100 * hits / max(n, 1), 1)
    params["phi"]["home_gk"] = params["phi"]["away_gk"] = 1.1
    params["phi"]["free_kicks"] = (params["phi"]["home_fouls"] + params["phi"]["away_fouls"]) / 2

    # match result: model vs bookmaker
    y = test.res.map({"H": 0, "D": 1, "A": 2}).to_numpy()
    model = test[["pH", "pD", "pA"]].to_numpy()
    mkt = test[["mH", "mD", "mA"]].to_numpy()
    ytr = train.res.map({"H": 0, "D": 1, "A": 2}).to_numpy()
    mtr, ktr = train[["pH", "pD", "pA"]].to_numpy(), train[["mH", "mD", "mA"]].to_numpy()
    ws = np.linspace(0, 1, 21)
    w_res = min(ws, key=lambda w: -np.mean(np.log((w * mtr + (1 - w) * ktr)[np.arange(len(ytr)), ytr])))
    params["w_result"] = float(w_res)
    blend = w_res * model + (1 - w_res) * mkt
    rep["match_result"] = {
        "model_pick_right_%": round(100 * float((model.argmax(1) == y).mean()), 1),
        "bookmaker_pick_right_%": round(100 * float((mkt.argmax(1) == y).mean()), 1),
        "final_pick_right_%": round(100 * float((blend.argmax(1) == y).mean()), 1),
        "model_share_in_final": float(w_res)}
    # BTTS: ratings model vs bookmaker-implied
    w_b = min(ws, key=lambda w: logloss(w * train.pBTTS + (1 - w) * train.mBTTS, train.btts))
    params["w_btts"] = float(w_b)
    fb = w_b * test.pBTTS + (1 - w_b) * test.mBTTS
    rep["btts"] = {
        "final_pick_right_%": round(100 * float(((fb > 0.5) == (test.btts == 1)).mean()), 1),
        "always_yes_right_%": round(100 * float(test.btts.mean()), 1),
        "strong_yes_(>=60%)_tips": int((fb >= 0.6).sum()),
        "strong_yes_hit_%": round(100 * float(test.btts[fb >= 0.6].mean()), 1) if (fb >= 0.6).any() else None,
        "strong_no_(<=40%)_tips": int((fb <= 0.4).sum()),
        "strong_no_hit_%": round(100 * float(1 - test.btts[fb <= 0.4].mean()), 1) if (fb <= 0.4).any() else None,
        "model_share_in_final": float(w_b)}
    params["report"]["markets"] = rep
    return params


# ---------------------------------------------------------------- live predictions
def league_norms(df):
    """League averages over the last year of `df` (the "normal" level for each market)."""
    recent = df[df.Date >= df.Date.max() - pd.Timedelta(days=365)]
    lg = {k: float(v.mean()) for k, v in actual_values(recent).items()}
    lg["home_gk"] = GK_BASE + GK_PER_MISS * float(recent.AMISS.mean())
    lg["away_gk"] = GK_BASE + GK_PER_MISS * float(recent.HMISS.mean())
    lg["free_kicks"] = lg["home_fouls"] + lg["away_fouls"] + OFFSIDES_PER_MATCH
    return lg


def predict_one(df, f, params, lg, code, name):
    """Predict one match `f` using only the matches in `df`."""
    phi, coefs = params["phi"], params["coefs"]
    ref = f.get("Referee")
    rm = referee_factor(df, ref, f.Date)
    bm = base_means(team_rates(df, f.HomeTeam, f.AwayTeam, f.Date), rm)
    op = outcome_probs(bm["lam_h"], bm["lam_a"])
    res, ou = market_probs(f)
    mlh = mla = None
    if res and ou:
        mlh, mla = market_lambdas(res, ou)
    means = {k: final_mean(k, bm, mlh, mla, coefs) for k in MEASURED}
    means.update(derived_means(bm, (means["home_sot"], means["away_sot"])))
    means["free_kicks"] = means["home_fouls"] + means["away_fouls"] + OFFSIDES_PER_MATCH
    if res:
        wr = params["w_result"]
        final = {k: wr * op[k] + (1 - wr) * res[k] for k in "HDA"}
    else:
        final = {k: op[k] for k in "HDA"}
    if mlh is not None:
        wb = params["w_btts"]
        btts = wb * op["BTTS"] + (1 - wb) * outcome_probs(mlh, mla)["BTTS"]
    else:
        btts = op["BTTS"]
    recent = df[df.Date >= f.Date - pd.Timedelta(days=365)]
    normal = normal_values(recent)
    normal["total_goals"] = (recent.FTHG + recent.FTAG).to_numpy(float)
    pm = plain_means(df, f.HomeTeam, f.AwayTeam, f.Date)
    markets = []
    for k, (label, est, _) in MARKETS.items():
        mean, ph = means[k], phi.get(k)
        ml = main_line(mean, ph)
        po = over_prob(mean, ml, ph)
        markets.append({"key": k, "label": label, "estimate": est,
                        "tip": None if est else best_tip(mean, ph, normal.get(k), k),
                        "book_line": None if est else book_line(k, pm, ph),
                        "expected": round(mean, 2), "league_avg": round(lg[k], 1),
                        "phi": ph,
                        "line": ml,
                        "over": round(100 * po), "under": round(100 * (1 - po)),
                        "safe_over": safe_over_line(mean, ph),
                        "safe_under": safe_under_line(mean, ph)})
    # total goals: the goals expected from the bookmakers' prices (their goals odds beat team stats),
    # tipped with the same rule as the other markets. Tested on 3,700 past games: 826 tips,
    # landed 79% (said 78%; a normal game 69%).
    gh, ga = (mlh, mla) if mlh is not None else (bm["lam_h"], bm["lam_a"])
    tg, nt = gh + ga, normal["total_goals"]
    ml = main_line(tg, 1.0)
    po = over_prob(tg, ml, 1.0)
    markets.append({"key": "total_goals", "label": "Total goals", "estimate": False,
                    "tip": best_tip(tg, 1.0, nt, "total_goals") if len(nt) >= 50 else None, "book_line": None,
                    "expected": round(tg, 2), "league_avg": round(float(nt.mean()), 1) if len(nt) else round(tg, 1),
                    "phi": 1.0, "line": ml, "over": round(100 * po), "under": round(100 * (1 - po)),
                    "safe_over": safe_over_line(tg, 1.0), "safe_under": safe_under_line(tg, 1.0)})
    n_home = int(((df.HomeTeam == f.HomeTeam) | (df.AwayTeam == f.HomeTeam)).sum())
    n_away = int(((df.HomeTeam == f.AwayTeam) | (df.AwayTeam == f.AwayTeam)).sum())
    return {
        "league": name, "code": code, "date": f.Date.strftime("%a %d %b"),
        "sort": f.Date.strftime("%Y%m%d") + str(f.get("Time", "")),
        "time": str(f.get("Time", "")), "home": f.HomeTeam, "away": f.AwayTeam,
        "kickoff": f.Date.strftime("%Y-%m-%d") + " " + str(f.get("Time", "00:00")),
        "iso": f.Date.strftime("%Y-%m-%d"),
        "referee": ref if isinstance(ref, str) and ref.strip() else "",
        "ref_factor": round(rm, 2),
        "goals_exp": (round(mlh if mlh else bm["lam_h"], 2), round(mla if mla else bm["lam_a"], 2)),
        "model": {k: round(100 * op[k]) for k in "HDA"},
        "bookie": {k: round(100 * res[k]) for k in "HDA"} if res else None,
        "final": {k: round(100 * v) for k, v in final.items()},
        "btts": round(100 * btts), "markets": markets,
        "data_matches": (n_home, n_away),
    }


LATEST_ODDS = True       # price fixtures from ESPN's latest odds when it has them


def espn_missing(rows, extra, teams, aliases=None):
    """ESPN's upcoming games of one league that fixtures.csv does not list yet (it can lag by a
    day or more, e.g. after an international break), as fixture rows with football-data names.
    extra: [{"day": "YYYY-MM-DD" (UK), "time": "HH:MM" (UK), "home", "away"}] with ESPN names.
    A game is added only if both teams map clearly onto this league's teams; never guessed.
    Games football-data does list get ESPN's latest odds instead of its early snapshot (tested on
    782 games this season: closing odds beat the snapshot for result, goals and both teams to
    score); `rows` is changed in place for those. Returns (added rows, games given latest odds)."""
    import espn
    match = espn.matcher(teams, aliases)
    have = [(i, d, h, a) for i, d, h, a in zip(rows.index, rows.Date, rows.HomeTeam, rows.AwayTeam)]
    busy = {(d.strftime("%Y-%m-%d"), t) for i, d, h, a in have if not pd.isna(d) for t in (h, a)}
    out, latest = [], 0
    for e in extra:
        h, a = match(e["home"]), match(e["away"])
        if not h or not a or h == a or h not in teams or a not in teams:
            print(f"  ESPN fixture skipped (team names unclear): {e['home']} v {e['away']}")
            continue
        day = pd.Timestamp(e["day"])
        same = [i for i, d, hh, aa in have if hh == h and aa == a and not pd.isna(d) and abs((d - day).days) <= 3]
        if same:                                       # football-data already has it: use the latest odds
            if LATEST_ODDS and e.get("odds"):
                for col, v in e["odds"].items():
                    rows.loc[same[0], col] = v
                latest += 1
            continue
        if (e["day"], h) in busy or (e["day"], a) in busy:
            continue
        busy |= {(e["day"], h), (e["day"], a)}
        out.append({"Div": e["code"], "Date": day, "Time": e["time"],
                    "HomeTeam": h, "AwayTeam": a, "Referee": None, **(e.get("odds") or {})})
    return out, latest


def predict_fixtures(params, extra=(), aliases=None):
    """Upcoming league games from fixtures.csv, plus any that only ESPN lists so far (extra)."""
    fx = load_fixtures()
    out = []
    for code, name in LEAGUES.items():
        df = load_league(code)
        teams = set(df.HomeTeam) | set(df.AwayTeam)
        lg = league_norms(df)
        rows = fx[fx.Div == code].copy()
        add, latest = espn_missing(rows, [e for e in extra if e["code"] == code], teams, aliases)
        if latest:
            print(f"{name}: {latest} games priced from ESPN's latest odds")
        if add:
            print(f"{name}: {len(add)} upcoming games taken from ESPN (not in fixtures.csv yet)")
            rows = pd.concat([rows, pd.DataFrame(add)], ignore_index=True)
        for _, f in referees.fill(rows, code).iterrows():
            if f.HomeTeam in teams and f.AwayTeam in teams:
                out.append(predict_one(df, f, params, lg, code, name))
    out.sort(key=lambda x: (x["sort"], x["league"]))
    return out


def replay(params, days=28, skip=()):
    """Predict each league match of the last `days` days using only games played before it."""
    out = []
    cutoff = pd.Timestamp.today().normalize() - pd.Timedelta(days=days)
    for code, name in LEAGUES.items():
        df = load_league(code)
        for _, f in df[df.Date >= cutoff].iterrows():
            if f"{code}|{f.Date:%Y-%m-%d}|{f.HomeTeam}|{f.AwayTeam}" in skip:
                continue
            hist = df[df.Date < f.Date]
            if len(hist) < 100:
                continue
            m = predict_one(hist, f, params, league_norms(hist), code, name)
            m["replay"] = True
            out.append(m)
    return out


# ---------------------------------------------------------------- track record
LOG_FILE = HERE / "predictions_log.csv"


def update_log(matches):
    """Keep the last prediction made before each match, so we can score it later."""
    rows = []
    for m in matches:
        if m["code"] not in LEAGUES:      # European cups: not scored yet
            continue
        base = {"code": m["code"], "date": m["iso"], "home": m["home"], "away": m["away"]}
        best = max(m["final"], key=m["final"].get)
        rows.append({**base, "market": "result", "pick": best, "chance": m["final"][best], "line": None})
        yes = m["btts"] >= 50
        rows.append({**base, "market": "btts", "pick": "yes" if yes else "no",
                     "chance": m["btts"] if yes else 100 - m["btts"], "line": None})
        for k in m["markets"]:
            if k["safe_over"] is not None:
                rows.append({**base, "market": k["key"], "pick": "over", "chance": SAFE * 100,
                             "line": k["safe_over"]})
            if k["safe_under"] is not None:
                rows.append({**base, "market": k["key"], "pick": "under", "chance": SAFE * 100,
                             "line": k["safe_under"]})
            rows.append({**base, "market": k["key"], "pick": "over" if k["over"] >= 50 else "under",
                         "chance": max(k["over"], k["under"]), "line": k["line"], "main": 1})
    new = pd.DataFrame(rows)
    if LOG_FILE.exists():
        old = pd.read_csv(LOG_FILE)
        now = pd.Timestamp.now()
        future = {(m["iso"], m["home"], m["away"]) for m in matches
                  if pd.to_datetime(m["kickoff"], errors="coerce") > now}
        logged = set(zip(old.date, old.home, old.away))
        # replace a match's old prediction only before kick-off; never rewrite history
        old = old[[t not in future for t in zip(old.date, old.home, old.away)]]
        new = new[[(t in future) or (t not in logged) for t in zip(new.date, new.home, new.away)]]
        new = pd.concat([old, new], ignore_index=True)
    new.to_csv(LOG_FILE, index=False)


def score_log():
    """Compare logged predictions with real results."""
    if not LOG_FILE.exists():
        return None
    log = pd.read_csv(LOG_FILE)
    if "main" not in log:
        log["main"] = np.nan
    results = []
    for code in log.code.unique():
        df = load_league(code)
        df["date"] = df.Date.dt.strftime("%Y-%m-%d")
        results.append(df.assign(code=code))
    res = pd.concat(results)
    j = log.merge(res, left_on=["code", "date", "home", "away"],
                  right_on=["code", "date", "HomeTeam", "AwayTeam"])
    if j.empty:
        return {"matches": 0}

    def outcome(r):
        if r.market == "result":
            return r.pick == r.FTR
        if r.market == "btts":
            return (r.FTHG > 0 and r.FTAG > 0) == (r.pick == "yes")
        val = actual_values(r)[r.market] if r.market in MEASURED else None
        if val is None:
            return None
        return val > r.line if r.pick == "over" else val < r.line

    j["hit"] = j.apply(outcome, axis=1)
    j = j.dropna(subset=["hit"])
    out = {"matches": int(j[["date", "home", "away"]].drop_duplicates().shape[0]),
           "from": j.date.min(), "to": j.date.max(), "groups": []}
    names = {k: v[0] for k, v in MARKETS.items()}
    names.update({"result": "Match result (our top pick)", "btts": "BTTS (our pick)"})
    for mk in ["result", "btts"] + MEASURED:
        for kind, sel in [("pick", j.market.eq(mk) & ~j.main.eq(1) & ~j.pick.isin(["over", "under"])),
                          ("safer", j.market.eq(mk) & ~j.main.eq(1) & j.pick.isin(["over", "under"])),
                          ("main line", j.market.eq(mk) & j.main.eq(1))]:
            s = j[sel]
            if len(s):
                out["groups"].append({"market": names[mk], "kind": kind, "n": int(len(s)),
                                      "hit": round(100 * float(s.hit.astype(float).mean()), 1),
                                      "promised": round(float(s.chance.mean()), 1)})
    return out


def load_or_fit_params(refit=False):
    if PARAMS_FILE.exists() and not refit:
        return json.loads(PARAMS_FILE.read_text())
    bt = backtest()
    bt.to_csv(HERE / "backtest_results.csv", index=False)
    params = fit_params(bt)
    params["fitted"] = pd.Timestamp.today().strftime("%Y-%m-%d")
    PARAMS_FILE.write_text(json.dumps(params, indent=2))
    return params


if __name__ == "__main__":
    p = load_or_fit_params(refit=True)
    print(json.dumps(p["report"], indent=2))
    print("phi", {k: round(v, 2) for k, v in p["phi"].items()})
