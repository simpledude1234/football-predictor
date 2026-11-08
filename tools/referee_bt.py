"""Do referee names (football-data.org) make booking predictions better in
Serie A, LaLiga, Bundesliga and Ligue 1? Predicts each game's bookings from
earlier games only, with and without the referee's record, and compares.
Run: python tools/referee_bt.py   (after python referees.py has saved the names)
"""
import pathlib
import sys

import numpy as np
from scipy import stats

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import predictor as P   # noqa: E402
import referees         # noqa: E402

PHI = 12.0   # spread of booking counts (negative binomial), same for both runs


def nb_logp(mu, y):
    p = PHI / (PHI + mu)
    return stats.nbinom.logpmf(y, PHI, p)


def run(code):
    referees.ON = True
    df = P.load_league(code)
    named = df.Referee.notna() & (df.Referee.astype(str).str.strip() != "")
    rows = []
    start = df.Date.min() + np.timedelta64(365, "D")
    for i in np.where((df.Date >= start).to_numpy() & named.to_numpy())[0]:
        r = df.iloc[i]
        hist = df[df.Date < r.Date]
        tr = P.team_rates(hist, r.HomeTeam, r.AwayTeam, r.Date)
        rf = P.referee_factor(hist, r.Referee, r.Date)
        base = tr["cards"][0] + tr["cards"][1]
        rows.append((base, base * rf, r.HCARD + r.ACARD, rf, (hist.Referee == r.Referee).sum()))
    a = np.array(rows, float)
    if not len(a):
        return {"tested": 0}
    return {"games": len(df), "named": int(named.sum()), "tested": len(a),
            "without": -nb_logp(a[:, 0], a[:, 2]).mean(), "with": -nb_logp(a[:, 1], a[:, 2]).mean(),
            "mae_without": np.abs(a[:, 0] - a[:, 2]).mean(), "mae_with": np.abs(a[:, 1] - a[:, 2]).mean(),
            "spread": a[:, 3].std(), "rows": a}


if __name__ == "__main__":
    for code in list(referees.COMPS) + ["E0", "E1"]:
        x = run(code)
        if not x["tested"]:
            print(code, "no referee names yet"); continue
        a = x["rows"]
        hi, lo = a[a[:, 3] >= 1.1], a[a[:, 3] <= 0.9]
        print(f"{code}: {x['named']} of {x['games']} games named; tested {x['tested']}. "
              f"Log score {x['without']:.4f} -> {x['with']:.4f} (lower is better); "
              f"average miss {x['mae_without']:.3f} -> {x['mae_with']:.3f} bookings. "
              f"Strict referees (x1.1+): {len(hi)} games, said {hi[:, 1].mean():.2f}, got {hi[:, 2].mean():.2f}; "
              f"lenient (x0.9-): {len(lo)} games, said {lo[:, 1].mean():.2f}, got {lo[:, 2].mean():.2f}")
