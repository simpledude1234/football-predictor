"""Corners from football-data.co.uk's files: five seasons, every league we load.

ESPN only has games since the summer, so corners use football-data's own corner
counts (HC/AC) instead: thousands of games per league. The model is the same as
the other team stats: league normal x the team's corners-won rate x the
opponent's corners-allowed rate. Each rate compares a team with the normal of the
league it was playing in at the time, so promoted and relegated teams keep their
history. Older games count for less (their weight halves every HALF_LIFE days,
chosen by the test), and every team gets PRIOR games of "normal" added so a few
odd games don't swing it.
"""
import datetime as dt
import zlib

import numpy as np
import pandas as pd

from fetch_data import ALL_LEAGUES, DATA, season_codes

SEASONS = 5
PRIOR = 5.0
MIN_GAMES = 3
HALF_LIVES = (120, 240, 365, 730, 100000)   # tried in the test; 100000 = old games count the same
HALF_LIFE = 240                  # best in the test (`py -3.13 corners.py`)
PLAIN_GAMES = 10
KEYS = ("total_corners", "home_corners", "away_corners")


def _day(d):
    return (np.datetime64(d, "D") - np.datetime64("1970-01-01", "D")).astype(int)


def load_rows():
    frames = []
    for code in ALL_LEAGUES:
        for s in season_codes(SEASONS):
            p = DATA / f"{code}_{s}.csv"
            if not p.exists() or p.stat().st_size < 100:
                continue
            try:
                df = pd.read_csv(p, encoding="utf-8-sig", encoding_errors="replace",
                                 usecols=lambda c: c in ("Date", "HomeTeam", "AwayTeam", "HC", "AC"))
            except Exception:
                continue
            if not {"Date", "HomeTeam", "AwayTeam", "HC", "AC"} <= set(df):
                continue
            df["code"] = code
            frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["code", "Date", "HomeTeam", "AwayTeam", "HC", "AC", "day"])
    df = pd.concat(frames, ignore_index=True)
    df["Date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    for c in ("HC", "AC"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["Date", "HomeTeam", "AwayTeam", "HC", "AC"])
    df = df[df.HC.between(0, 30) & df.AC.between(0, 30)].copy()     # throw away impossible numbers
    df["day"] = (df.Date - pd.Timestamp("1970-01-01")).dt.days
    return df.sort_values(["day", "code"]).reset_index(drop=True)


class Corners:
    def __init__(self, half_life=HALF_LIFE, rows=None):
        self.half_life = half_life
        df = load_rows() if rows is None else rows
        self.df = df
        self.league = {}
        for code, g in df.groupby("code"):
            self.league[code] = (g.day.to_numpy(), g.HC.to_numpy(float), g.AC.to_numpy(float))
        # league normal at the time of each game (the year before it)
        nh = np.full(len(df), np.nan)
        na = np.full(len(df), np.nan)
        for code, (days, hc, ac) in self.league.items():
            idx = np.flatnonzero(df.code.to_numpy() == code)
            ch, ca = np.concatenate([[0], np.cumsum(hc)]), np.concatenate([[0], np.cumsum(ac)])
            lo = np.searchsorted(days, days - 365, "left")
            hi = np.searchsorted(days, days, "left")
            n = hi - lo
            ok = n >= 20
            nh[idx[ok]] = (ch[hi] - ch[lo])[ok] / n[ok]
            na[idx[ok]] = (ca[hi] - ca[lo])[ok] / n[ok]
        nh[np.isnan(nh)] = np.nanmean(nh) if np.isfinite(nh).any() else 5.0
        na[np.isnan(na)] = np.nanmean(na) if np.isfinite(na).any() else 4.0
        self.teams = {}
        for side, made, conc, bm, bc in (("HomeTeam", "HC", "AC", nh, na), ("AwayTeam", "AC", "HC", na, nh)):
            for t, idx in df.groupby(side).indices.items():
                self.teams.setdefault(t, []).append(np.column_stack(
                    [df.day.to_numpy()[idx], df[made].to_numpy(float)[idx], bm[idx],
                     df[conc].to_numpy(float)[idx], bc[idx]]))
        self.teams = {t: (lambda a: a[np.argsort(a[:, 0], kind="stable")])(np.vstack(v)) for t, v in self.teams.items()}

    def _norm(self, code, day):
        if code not in self.league:
            return None
        days, hc, ac = self.league[code]
        lo, hi = np.searchsorted(days, day - 365, "left"), np.searchsorted(days, day, "left")
        if hi - lo < 20:
            return None
        return hc[lo:hi], ac[lo:hi]

    def _rate(self, team, day, per):
        a = self.teams.get(team)
        if a is None:
            return 1.0, 1.0, 0, None
        a = a[:np.searchsorted(a[:, 0], day, "left")]
        w = 0.5 ** ((day - a[:, 0]) / self.half_life)
        made = (w @ a[:, 1] + PRIOR * per) / (w @ a[:, 2] + PRIOR * per)
        conc = (w @ a[:, 3] + PRIOR * per) / (w @ a[:, 4] + PRIOR * per)
        last = a[-PLAIN_GAMES:]
        plain = (last[:, 1].mean(), last[:, 3].mean()) if len(last) >= 3 else None
        return made, conc, len(a), plain

    def predict(self, home, away, code, date):
        """{"mean", "nm", "plain"} for one game, from games before `date` only (None if not enough)."""
        day = _day(str(date)[:10])
        lg = self._norm(code, day)
        if lg is None:
            return None
        lh, la = float(lg[0].mean()), float(lg[1].mean())
        per = (lh + la) / 2
        ah, ch, nh, ph = self._rate(home, day, per)
        aa, ca, na, pa = self._rate(away, day, per)
        if min(nh, na) < MIN_GAMES:
            return None
        h, a = lh * ah * ca, la * aa * ch
        out = {"mean": {"home_corners": h, "away_corners": a, "total_corners": h + a},
               "nm": {"home_corners": lg[0], "away_corners": lg[1], "total_corners": lg[0] + lg[1]},
               "plain": {}}
        if ph and pa:
            ph_, pa_ = (ph[0] + pa[1]) / 2 * lh / per, (pa[0] + ph[1]) / 2 * la / per
            out["plain"] = {"home_corners": ph_, "away_corners": pa_, "total_corners": ph_ + pa_}
        return out

    def test_preds(self, lines, years=3):
        """Every game of the last `years` years predicted from only the games before it."""
        df = self.df
        if df.empty:
            return []
        first = df.day.max() - 365 * years
        preds = []
        for r in df[df.day >= first].itertuples():
            p = self.predict(r.HomeTeam, r.AwayTeam, r.code, r.Date.date())
            if not p:
                continue
            act = {"home_corners": r.HC, "away_corners": r.AC, "total_corners": r.HC + r.AC}
            preds.append({"id": f"fd|{r.code}|{r.Date.date()}|{r.HomeTeam}", "mean": p["mean"], "act": act,
                          "nm": dict.fromkeys(KEYS), "plain": p["plain"],
                          "bo": {k: (v[:, None] > lines).mean(0) for k, v in p["nm"].items()}})
        return preds


def fit_half_life(rows=None):
    """The half-life whose predictions of total corners were closest, game by game."""
    rows = load_rows() if rows is None else rows
    best = None
    for hl in HALF_LIVES:
        c = Corners(hl, rows)
        first = rows.day.max() - 365 * 3
        err = []
        for r in rows[rows.day >= first].itertuples():
            p = c.predict(r.HomeTeam, r.AwayTeam, r.code, r.Date.date())
            if p:
                err.append((p["mean"]["total_corners"] - r.HC - r.AC) ** 2)
        mse = float(np.mean(err)) if err else np.inf
        print(f"corners half-life {hl:>6} days: error {mse:.3f} over {len(err)} games")
        if best is None or mse < best[1]:
            best = (hl, mse)
    return best[0]


def half(pid):
    return int(pid) % 2 if str(pid).isdigit() else zlib.crc32(str(pid).encode()) % 2


if __name__ == "__main__":
    t0 = dt.datetime.now()
    print("best half-life:", fit_half_life(), "days", dt.datetime.now() - t0)
