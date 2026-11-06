"""Champions League, Europa League and Conference League predictions.

Fixtures and bookmaker odds come from ESPN's free public feed. Teams are
rated from their own domestic league (13 leagues covered). The bookmaker odds
then anchor the numbers, using the same formula as the domestic leagues.
Not yet tested on past European matches, so the page marks these as BETA.
"""
import datetime as dt
import difflib
import json
import re
import unicodedata
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from scipy import optimize

import predictor as P
from fetch_data import ALL_LEAGUES

ESPN = "https://site.api.espn.com/apis/site/v2/sports/soccer/"
CUPS = {"uefa.champions": ("UCL", "Champions League"),
        "uefa.europa": ("UEL", "Europa League"),
        "uefa.europa.conf": ("UECL", "Conference League")}
DOMESTIC_WEIGHT = 0.6     # domestic form counts for less against European opposition
UK = ZoneInfo("Europe/London")

ALIASES = {  # ESPN name -> football-data name, for names too different to match automatically
    "manchester united": "Man United", "manchester city": "Man City", "newcastle united": "Newcastle",
    "tottenham hotspur": "Tottenham", "nottingham forest": "Nott'm Forest", "west ham united": "West Ham",
    "wolverhampton wanderers": "Wolves", "brighton & hove albion": "Brighton", "aston villa": "Aston Villa",
    "paris saint-germain": "Paris SG", "internazionale": "Inter", "inter milan": "Inter", "ac milan": "Milan",
    "atletico madrid": "Ath Madrid", "athletic club": "Ath Bilbao", "real sociedad": "Sociedad",
    "real betis": "Betis", "celta vigo": "Celta", "rayo vallecano": "Vallecano", "sporting cp": "Sp Lisbon",
    "sporting lisbon": "Sp Lisbon", "sc braga": "Sp Braga", "braga": "Sp Braga", "fc porto": "Porto",
    "vitoria guimaraes": "Guimaraes", "bayer leverkusen": "Leverkusen", "borussia dortmund": "Dortmund",
    "borussia monchengladbach": "M'gladbach", "eintracht frankfurt": "Ein Frankfurt", "vfb stuttgart": "Stuttgart",
    "tsg hoffenheim": "Hoffenheim", "sc freiburg": "Freiburg", "rb leipzig": "RB Leipzig", "fc koln": "FC Koln",
    "mainz": "Mainz", "1. fsv mainz 05": "Mainz", "union berlin": "Union Berlin", "stade rennais": "Rennes",
    "olympique lyonnais": "Lyon", "olympique marseille": "Marseille", "marseille": "Marseille", "as monaco": "Monaco",
    "ogc nice": "Nice", "rc lens": "Lens", "stade brestois": "Brest", "strasbourg": "Strasbourg",
    "psv eindhoven": "PSV Eindhoven", "fc twente": "Twente", "az alkmaar": "AZ Alkmaar", "fc utrecht": "Utrecht",
    "club brugge": "Club Brugge", "kaa gent": "Gent", "royal antwerp": "Antwerp", "anderlecht": "Anderlecht",
    "union st.-gilloise": "St. Gilloise", "union saint-gilloise": "St. Gilloise", "krc genk": "Genk",
    "olympiacos": "Olympiakos", "paok salonika": "PAOK", "paok": "PAOK", "aek athens": "AEK",
    "panathinaikos": "Panathinaikos", "besiktas": "Besiktas", "fenerbahce": "Fenerbahce",
    "galatasaray": "Galatasaray", "trabzonspor": "Trabzonspor", "istanbul basaksehir": "Buyuksehyr",
    "as roma": "Roma", "ss lazio": "Lazio", "ssc napoli": "Napoli", "napoli": "Napoli", "atalanta": "Atalanta",
    "fiorentina": "Fiorentina", "bologna": "Bologna", "juventus": "Juventus", "heart of midlothian": "Hearts",
    "ajax amsterdam": "Ajax", "feyenoord rotterdam": "Feyenoord", "nec nijmegen": "Nijmegen", "hibernian": "Hibernian", "aberdeen": "Aberdeen", "rangers": "Rangers", "celtic": "Celtic",
}
DROP = {"fc", "cf", "afc", "sc", "sv", "as", "ac", "cd", "ud", "rc", "sk", "fk", "kaa", "krc", "vfl", "vfb",
        "tsg", "ss", "ssc", "1.", "club", "de", "the", "calcio"}


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return " ".join(w for w in re.split(r"[\s\-]+", s) if w and w not in DROP)


def _get_json(url):
    if not url.startswith(ESPN):
        raise ValueError("blocked: unexpected address")
    r = requests.get(url, timeout=30, allow_redirects=False, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    if len(r.content) > 5_000_000:
        raise ValueError("blocked: reply far bigger than expected")
    return r.json()


def _prob(ml):
    """American odds (e.g. -155 or +240) -> implied probability."""
    try:
        ml = float(str(ml).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if ml == 0:
        return None
    return 100 / (ml + 100) if ml > 0 else -ml / (-ml + 100)


def fetch_fixtures(days=21):
    out = []
    today = dt.date.today()
    for slug, (code, name) in CUPS.items():
        for d in range(days):
            day = (today + dt.timedelta(days=d)).strftime("%Y%m%d")
            try:
                js = _get_json(f"{ESPN}{slug}/scoreboard?dates={day}")
            except Exception as e:
                print(f"{name} {day}: failed ({e})")
                continue
            for e in js.get("events", []):
                c = e["competitions"][0]
                if c.get("status", e.get("status", {})).get("type", {}).get("state") != "pre":
                    continue
                teams = {t["homeAway"]: t["team"]["displayName"] for t in c["competitors"]}
                odds = (c.get("odds") or [{}])[0] or {}
                res = ou = None
                ph = _prob((odds.get("homeTeamOdds") or {}).get("moneyLine"))
                pa = _prob((odds.get("awayTeamOdds") or {}).get("moneyLine"))
                pd_ = _prob((odds.get("drawOdds") or {}).get("moneyLine"))
                if ph and pa and pd_:
                    s = ph + pa + pd_
                    res = {"H": ph / s, "D": pd_ / s, "A": pa / s}
                tot = odds.get("total") or {}
                po = _prob(((tot.get("over") or {}).get("close") or {}).get("odds"))
                pu = _prob(((tot.get("under") or {}).get("close") or {}).get("odds"))
                if odds.get("overUnder") and po and pu:
                    ou = (float(odds["overUnder"]), po / (po + pu))
                ko = pd.Timestamp(e["date"]).tz_convert(UK)
                out.append({"code": code, "league": name, "home": teams.get("home"), "away": teams.get("away"),
                            "ko": ko, "res": res, "ou": ou})
        print(f"{name}: {sum(1 for x in out if x['code'] == code)} upcoming matches")
    return out


def market_lambdas_line(res, line, p_over):
    def err(x):
        lh, la = np.exp(x)
        m = P.score_matrix(lh, la)
        tot = np.add.outer(np.arange(m.shape[0]), np.arange(m.shape[1]))
        return ((np.tril(m, -1).sum() - res["H"]) ** 2 + (np.triu(m, 1).sum() - res["A"]) ** 2
                + (m[tot > line].sum() - p_over) ** 2)
    sol = optimize.minimize(err, np.log([1.4, 1.1]), method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-7})
    return tuple(float(v) for v in np.exp(sol.x))


def team_ratings(df, team, date):
    """How much more/less than average a team does and allows, per stat (1.0 = average)."""
    age = (date - df.Date).dt.days.to_numpy()
    w = 0.5 ** (age / P.HALF_LIFE_DAYS)
    hm, am = (df.HomeTeam == team).to_numpy(), (df.AwayTeam == team).to_numpy()
    out = {}
    for stat, (hc, ac) in P.BASE.items():
        xh, xa = df[hc].to_numpy(float), df[ac].to_numpy(float)
        mu_h, mu_a = np.sum(w * xh) / w.sum(), np.sum(w * xa) / w.sum()
        m = (mu_h + mu_a) / 2 * P.PRIOR_MATCHES
        f = np.sum(w[hm] * xh[hm]) + np.sum(w[am] * xa[am])
        fe = mu_h * w[hm].sum() + mu_a * w[am].sum()
        a = np.sum(w[hm] * xa[hm]) + np.sum(w[am] * xh[am])
        ae = mu_a * w[hm].sum() + mu_h * w[am].sum()
        out[stat] = (((f + m) / (fe + m)) ** DOMESTIC_WEIGHT, ((a + m) / (ae + m)) ** DOMESTIC_WEIGHT)
    return out, int(hm.sum() + am.sum())


def predict(params):
    leagues = {code: P.load_league(code) for code in ALL_LEAGUES}
    # each team's most recent league (a promoted/relegated team's newest one)
    home_of = {}
    for code, df in leagues.items():
        recent = df[df.Date >= df.Date.max() - pd.Timedelta(days=200)]
        for t in set(recent.HomeTeam) | set(recent.AwayTeam):
            home_of[t] = code
    names = list(home_of)
    norm_names = {_norm(n): n for n in names}

    def match_team(espn_name):
        key = unicodedata.normalize("NFKD", espn_name).encode("ascii", "ignore").decode().lower()
        if key in ALIASES and ALIASES[key] in home_of:
            return ALIASES[key]
        n = _norm(espn_name)
        if n in norm_names:
            return norm_names[n]
        best = difflib.get_close_matches(n, list(norm_names), n=1, cutoff=0.82)
        return norm_names[best[0]] if best else None

    # cup baseline = average across the big leagues (home and away)
    pool = pd.concat([leagues[c][leagues[c].Date >= leagues[c].Date.max() - pd.Timedelta(days=365)]
                      for c in ["E0", "SP1", "I1", "D1", "F1"]])
    base_avg = {s: (float(pool[h].mean()), float(pool[a].mean())) for s, (h, a) in P.BASE.items()}
    lg = {k: float(v.mean()) for k, v in P.actual_values(pool).items()}
    lg["home_gk"] = P.GK_BASE + P.GK_PER_MISS * float(pool.AMISS.mean())
    lg["away_gk"] = P.GK_BASE + P.GK_PER_MISS * float(pool.HMISS.mean())
    lg["free_kicks"] = lg["home_fouls"] + lg["away_fouls"] + P.OFFSIDES_PER_MATCH

    out, unmatched = [], set()
    for f in fetch_fixtures():
        if not f["home"] or not f["away"]:
            continue
        date = pd.Timestamp(f["ko"].date())
        prof, counts = {}, []
        for side in ("home", "away"):
            t = match_team(f[side])
            if t:
                r, n = team_ratings(leagues[home_of[t]], t, date)
            else:
                unmatched.add(f[side])
                r, n = {s: (1.0, 1.0) for s in P.BASE}, 0
            prof[side] = r
            counts.append(n)
        rates = {}
        for s in P.BASE:
            mu_h, mu_a = base_avg[s]
            rates[s] = (mu_h * prof["home"][s][0] * prof["away"][s][1], mu_a * prof["away"][s][0] * prof["home"][s][1])
            rates[s + "_avg"] = (mu_h, mu_a)
        bm = P.base_means(rates)
        op = P.outcome_probs(bm["lam_h"], bm["lam_a"])
        mlh = mla = None
        if f["res"] and f["ou"]:
            mlh, mla = market_lambdas_line(f["res"], *f["ou"])
        means = {k: P.final_mean(k, bm, mlh, mla, params["coefs"]) for k in P.MEASURED}
        means.update(P.derived_means(bm, (means["home_sot"], means["away_sot"])))
        means["free_kicks"] = means["home_fouls"] + means["away_fouls"] + P.OFFSIDES_PER_MATCH
        final = f["res"] or {k: op[k] for k in "HDA"}
        btts = P.outcome_probs(mlh, mla)["BTTS"] if mlh else op["BTTS"]
        markets = []
        for k, (label, est, _) in P.MARKETS.items():
            mean, ph = means[k], params["phi"].get(k)
            ml = P.main_line(mean, ph)
            po = P.over_prob(mean, ml, ph)
            markets.append({"key": k, "label": label, "estimate": est, "expected": round(mean, 2),
                            "league_avg": round(lg[k], 1), "phi": ph, "line": ml,
                            "over": round(100 * po), "under": round(100 * (1 - po)),
                            "safe_over": P.safe_over_line(mean, ph), "safe_under": P.safe_under_line(mean, ph)})
        ko = f["ko"]
        out.append({
            "league": f["league"], "code": f["code"], "beta": True,
            "date": ko.strftime("%a %d %b"), "time": ko.strftime("%H:%M"),
            "sort": ko.strftime("%Y%m%d%H:%M"), "kickoff": ko.strftime("%Y-%m-%d %H:%M"),
            "iso": ko.strftime("%Y-%m-%d"), "home": f["home"], "away": f["away"],
            "referee": "", "ref_factor": 1.0,
            "goals_exp": (round(mlh or bm["lam_h"], 2), round(mla or bm["lam_a"], 2)),
            "model": {k: round(100 * op[k]) for k in "HDA"},
            "bookie": {k: round(100 * f["res"][k]) for k in "HDA"} if f["res"] else None,
            "final": {k: round(100 * v) for k, v in final.items()},
            "btts": round(100 * btts), "markets": markets, "data_matches": tuple(counts),
        })
    if unmatched:
        print("European teams without domestic data (rated as average):", ", ".join(sorted(unmatched)))
    return out


if __name__ == "__main__":
    ms = predict(json.loads(P.PARAMS_FILE.read_text()))
    for m in ms[:5]:
        print(m["league"], m["date"], m["home"], "v", m["away"], m["final"], m["btts"], m["data_matches"])
