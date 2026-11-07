""""Better price" picks: a line near even money instead of a safe short-priced one.

For each over/under market we take the "even line": the line a normal game in
this league goes over about half the time, which is roughly where bookmakers
price both sides near evens (about 1.85 each). The model then says which side
it favours and how likely that is.

The model is a little over-confident on these lines, so its chance is pulled
towards 50% by a factor fitted on past games (`shrink`). A pick is shown only
when the pulled-in chance is at least MIN_CHANCE, with the lowest price worth
taking (1 / chance).

There are no free bookmaker prices for these markets, so these picks cannot be
tested against real odds; the test below checks only that the chances are right.
Run `py -3.13 value.py` to fit and test (needs backtest_results.csv and
team_stats test data), writing value_params.json.
"""
import datetime as dt
import json
import math
import zlib
import pathlib

import numpy as np

import predictor as P

HERE = pathlib.Path(__file__).parent
PARAMS = HERE / "value_params.json"
MIN_CHANCE = 58          # break-even at 1.85 is 54%; 58% leaves a margin for error


even_line = P.even_line


def raw_pick(mean, phi, line):
    po = P.over_prob(mean, line, phi)
    return ("over", po) if po >= 0.5 else ("under", 1 - po)


def pick(mean, phi, line, shrink):
    """The better-price pick for one market, or None."""
    if line is None or mean is None or shrink is None:
        return None
    side, p = raw_pick(mean, phi, line)
    ch = 0.5 + shrink * (p - 0.5)
    if 100 * ch < MIN_CHANCE:
        return None
    return {"side": side, "line": line, "chance": round(100 * ch),
            "min_odds": math.ceil(20 / ch) / 20}     # rounded up to the next 0.05


# ---------------------------------------------------------------- fitting and test
def _fit_shrink(recs):
    """recs: (raw chance of favoured side, landed 0/1). Best pull towards 50% by log score."""
    if not recs:
        return None
    p = np.array([r[0] for r in recs])
    y = np.array([r[1] for r in recs], float)
    best = None
    for s in np.arange(0.3, 1.21, 0.05):
        q = np.clip(0.5 + s * (p - 0.5), 1e-4, 1 - 1e-4)
        loss = -np.mean(y * np.log(q) + (1 - y) * np.log(1 - q))
        if best is None or loss < best[1]:
            best = (round(float(s), 2), loss)
    return best[0]


def _test(recs_by_half):
    """Fit on one half, score picks on the other, then swap."""
    n = won = 0
    said, odds = [], []
    for fit, test in (recs_by_half, recs_by_half[::-1]):
        s = _fit_shrink(fit)
        for p, y in test:
            ch = 0.5 + s * (p - 0.5)
            if 100 * ch >= MIN_CHANCE:
                n += 1
                won += y
                said.append(100 * ch)
                odds.append(math.ceil(20 / ch) / 20)
    return {"picks": n, "landed": round(100 * won / n, 1) if n else None,
            "said": round(float(np.mean(said)), 1) if n else None,
            "avg_min_odds": round(float(np.mean(odds)), 2) if n else None}


def _record(mean, phi, line, act):
    side, p = raw_pick(mean, phi, line)
    return p, int(act > line if side == "over" else act < line)


def main_market_records(bt, params):
    """From backtest_results.csv: the main model's final expected count at the even line."""
    bt = bt.dropna(subset=["mlh"]).sort_values("date").reset_index(drop=True)
    out = {}
    for k in P.MEASURED:
        side = P.MARKETS[k][2]
        coefs = np.array(params["coefs"][k])
        recs = []
        for code, d in bt.groupby("league"):
            d = d.reset_index(drop=True)
            acts = d[k + "_act"].to_numpy(float)
            dates = d.date.to_numpy()
            for i, r in enumerate(d.itertuples()):
                lo = dates[i] - np.timedelta64(365, "D")
                normal = acts[(dates < dates[i]) & (dates >= lo)]
                line = even_line(normal)
                if line is None or len(normal) < 50:
                    continue
                g = r.mlh + r.mla if side == "total" else (r.mlh if side == "home" else r.mla)
                mean = max(float(coefs @ np.array([1.0, getattr(r, k + "_base"), g, abs(r.mlh - r.mla)])), 0.2)
                recs.append((r.home + r.away + str(r.date), _record(mean, params["phi"][k], line, getattr(r, k + "_act"))))
        out[k] = recs
    return out


def team_stats_records(cache, ts_params):
    import team_stats as T
    preds = T.test_preds(cache)
    out = {}
    for k in T.KEYS:
        recs = []
        for p in preds:
            if k not in p["mean"] or k not in p["nm"]:
                continue
            line = even_line(p["nm"][k])
            if line is not None:
                recs.append((p["id"], _record(p["mean"][k], ts_params["phi"][k], line, p["act"][k])))
        out[k] = recs
    return out


def fit(main_recs, ts_recs):
    out = {"fitted": str(dt.date.today()), "min_chance": MIN_CHANCE, "shrink": {}, "test": {}}
    for k, recs in {**main_recs, **ts_recs}.items():
        half = lambda i: zlib.crc32(str(i).encode()) % 2
        halves = ([r for i, r in recs if half(i) == 0], [r for i, r in recs if half(i) == 1])
        out["test"][k] = _test(halves)
        out["shrink"][k] = _fit_shrink([r for _, r in recs])
    return out


def load_params():
    return json.loads(PARAMS.read_text(encoding="utf-8")) if PARAMS.exists() else None


def refit(cache, ts_params):
    import pandas as pd
    bt = pd.read_csv(HERE / "backtest_results.csv", parse_dates=["date"])
    params = json.loads(P.PARAMS_FILE.read_text())
    res = fit(main_market_records(bt, params), team_stats_records(cache, ts_params))
    PARAMS.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    return res


if __name__ == "__main__":
    import espn
    import team_stats as T
    res = refit(espn.load_cache(), T.load_params())
    for k, v in res["test"].items():
        print(f"{k:16} shrink {res['shrink'][k]}  {v}")
