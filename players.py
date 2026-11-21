"""Player to be booked.

For every player we count, this season, how often he is booked per match he
plays (a substitute appearance counts as about a third of a match). Players
with few games are pulled towards the average booking rate. That rate is then
scaled by how likely he is to play (from the team's last 5 games) and by how
card-heavy this particular match is expected to be (from the team model).
Players sent off in their team's last game are left out (likely suspended).
Once the starting line-ups are out (about an hour before kick-off), only the
named starters are considered. In replays this stopped about 1 in 10 picks
going to a player who then did not play.

Model 2 (2026-11-21, `candidates`): bookings and fouls per 90 minutes (pulled
towards the position's average), position and recent minutes, weighed as fitted
on past games; the card-heavy-match factor at half strength. Tested on 5,509
held-out player-games (tools/booked_bt.py): better than model 1, and its top
picks no longer over-promise (model 1 on the site: said 24%, landed 18% when the
match factor was high).
"""
import math
from collections import Counter, defaultdict

SUB_WEIGHT = 0.35       # a substitute appearance ~ a third of a match
PRIOR_GAMES = 20.0      # strong pull towards average: tested on 4 weeks of replays (promised ~20%, ~20% happened)
MIN_PLAY = 0.8          # only suggest regular players
# model 2 (2026-11-21): fitted on this season's games, see tools/booked_bt.py
W = {"const": -1.6, "card": 0.249, "foul": 0.314, "mins": 0.641, "pos_D": 0.195, "pos_M": -0.016, "pos_F": -0.178}
SHRINK_MINS = 900.0     # 10 full matches of his position's average
MIN_MINS = 45           # regulars only: at least 45 minutes a game over the last 5
LINEUP_MINS = 80        # a confirmed starter plays about this long
FACTOR_POWER = 0.5      # how card-heavy the match should be: half strength (full strength over-promised)


class PlayerModel:
    def __init__(self, cache):
        self.team_games = defaultdict(list)       # team -> [match, ...] sorted by date
        for m in cache["matches"].values():
            for side in ("home", "away"):
                if m.get(side):
                    self.team_games[m[side]].append(m)
        for g in self.team_games.values():
            g.sort(key=lambda m: m["date"])
        cards = starts = 0.0
        for m in cache["matches"].values():
            for name, side, starter, y, r, f in m["players"]:
                cards += (y + r) > 0
                starts += 1 if starter else SUB_WEIGHT
        self.prior = cards / starts if starts else 0.15
        fouls = apps = 0
        for m in cache["matches"].values():
            for name, side, starter, y, r, f in m["players"]:
                fouls += f or 0
                apps += 1
        self.foul_prior = fouls / apps if apps else 1.0

    def team_card_avg(self, team, before):
        vals = []
        for m in self.team_games.get(team, []):
            if m["date"] >= before:
                continue
            side = "home" if m["home"] == team else "away"
            s = m["stats"].get(side) or {}
            if s.get("yellowCards") is not None:
                vals.append((s.get("yellowCards") or 0) + (s.get("redCards") or 0))
        return sum(vals) / len(vals) if vals else None

    def match_factor(self, team, before, expected_team_cards):
        """How card-heavy this match should be for `team` versus its usual games
        (the expected team bookings already include the referee)."""
        avg = self.team_card_avg(team, before)
        factor = (expected_team_cards / avg) if (avg and expected_team_cards) else 1.0
        return max(0.6, min(1.6, factor))

    def squad_rates(self, team, before, expected_team_cards):
        """For the Live tab: every player who played in the team's last 5 games, with
        his booking rate for a full match (as -log(1 - chance)), adjusted for this match.
        The live model scales it by the minutes left, his fouls so far and the game's pace.
        "": the rate for a player we have no record of (a new signing or youngster)."""
        games = [m for m in self.team_games.get(team, []) if m["date"] < before]
        if not games:
            return {}
        factor = self.match_factor(team, before, expected_team_cards)
        st = defaultdict(lambda: [0.0, 0])
        recent = set()
        for m in games:
            side = "home" if m["home"] == team else "away"
            for name, s, starter, y, r, f in m["players"]:
                if s == side:
                    st[name][0] += 1 if starter else SUB_WEIGHT
                    st[name][1] += (y + r) > 0
                    if m in games[-5:]:
                        recent.add(name)
        lam = lambda b, eq: round(-math.log(1 - min((b + PRIOR_GAMES * self.prior) / (eq + PRIOR_GAMES), 0.9)) * factor, 4)
        out = {n: lam(st[n][1], st[n][0]) for n in sorted(recent)}
        out[""] = lam(0, 0)
        return out

    def foul_habit(self, team, before):
        """For the Live tab: fouls per appearance over each player's last 15 games for the team
        (pulled towards the average for players with few games). A player who fouls a lot is
        booked more often: tested on 548 past games (tools/live_players_bt.js).
        "": the average, for a player we have no record of."""
        games = [m for m in self.team_games.get(team, []) if m["date"] < before]
        if not games:
            return {}
        st = defaultdict(list)
        recent = set()
        for m in games:
            side = "home" if m["home"] == team else "away"
            for name, s, starter, y, r, f in m["players"]:
                if s == side:
                    st[name].append(f or 0)
                    if m in games[-5:]:
                        recent.add(name)
        k = 3.0
        out = {n: round((sum(st[n][-15:]) + k * self.foul_prior) / (len(st[n][-15:]) + k), 3) for n in sorted(recent)}
        out[""] = round(self.foul_prior, 3)
        return out

    def _pos_avgs(self):
        """Bookings and fouls per 90 minutes by position (G/D/M/F), the targets players are pulled towards."""
        if not hasattr(self, "_avg"):
            t = defaultdict(lambda: [0, 0, 0])
            for g in self.team_games.values():
                for m in g:
                    booked = {(n, s) for n, s, st, y, r, f in m["players"] if y + r > 0}
                    for key, v in (m.get("pstats") or {}).items():
                        s, n = key.split("|", 1)
                        if v[4]:
                            p = t[v[5]]; p[0] += v[4]; p[1] += (n, s) in booked; p[2] += v[2]
            mins = sum(v[0] for v in t.values()) or 1
            self._all = (sum(v[1] for v in t.values()) / mins * 90 or 0.17, sum(v[2] for v in t.values()) / mins * 90 or 1.1)
            self._avg = {k: (v[1] / v[0] * 90, v[2] / v[0] * 90) for k, v in t.items() if v[0] > 2000}
        return self._avg, self._all

    def candidates(self, team, before, expected_team_cards, lineup=None):
        """Players of `team` with their chance of being booked in the next match: his bookings and
        fouls per 90 minutes this season (pulled towards his position's average), his position and
        his recent minutes, weighed as fitted on past games (W). lineup: the confirmed starting
        eleven (names), if already announced."""
        games = [m for m in self.team_games.get(team, []) if m["date"] < before]
        if not games or not all(m.get("pstats") for m in games[-5:]):
            return self.candidates_v1(team, before, expected_team_cards, lineup)
        avg, (c_all, f_all) = self._pos_avgs()
        H = defaultdict(lambda: {"mins": 0, "cards": 0, "fouls": 0, "pos": Counter(), "m5": 0.0, "red": False})
        n5 = min(5, len(games))
        for i, m in enumerate(games):
            side = "home" if m["home"] == team else "away"
            booked = {n for n, s, st, y, r, f in m["players"] if s == side and y + r > 0}
            for key, v in (m.get("pstats") or {}).items():
                s, n = key.split("|", 1)
                if s != side or not v[4]:
                    continue
                h = H[n]
                h["mins"] += v[4]; h["fouls"] += v[2]; h["cards"] += n in booked; h["pos"][v[5]] += 1
                if i >= len(games) - 5:
                    h["m5"] += v[4] / n5
        for n, s, st, y, r, f in games[-1]["players"]:
            if s == ("home" if games[-1]["home"] == team else "away") and r > 0:
                H[n]["red"] = True                        # sent off last time: likely suspended
        if lineup:                                        # confirmed starters: they will play
            H = {n: {**H[n], "m5": max(H[n]["m5"], LINEUP_MINS), "red": False} for n in lineup}
        factor = self.match_factor(team, before, expected_team_cards) ** FACTOR_POWER
        out = []
        for name, h in H.items():
            if h["m5"] < MIN_MINS or h["red"]:
                continue
            pos = h["pos"].most_common(1)[0][0] if h["pos"] else "?"
            c90, f90 = avg.get(pos, (c_all, f_all)) if pos != "?" else (c_all, f_all)
            card = (h["cards"] + SHRINK_MINS / 90 * c90) / (h["mins"] + SHRINK_MINS) * 90
            foul = (h["fouls"] + SHRINK_MINS / 90 * f90) / (h["mins"] + SHRINK_MINS) * 90
            z = W["const"] + W["card"] * math.log(card / c_all) + W["foul"] * math.log(foul / f_all) \
                + W["mins"] * math.log(max(h["m5"], 1) / 90) + W.get("pos_" + pos, 0.0)
            lam = -math.log(1 - 1 / (1 + math.exp(-z))) * factor
            out.append({"player": name, "chance": round(100 * (1 - math.exp(-lam))),
                        "booked": h["cards"], "games": round(h["mins"] / 90, 1)})
        return sorted(out, key=lambda x: -x["chance"])

    def candidates_v1(self, team, before, expected_team_cards, lineup=None):
        """The first model (bookings per match only); used when per-player minutes are missing."""
        games = [m for m in self.team_games.get(team, []) if m["date"] < before]
        if not games:
            return []
        stats = defaultdict(lambda: {"eq": 0.0, "booked": 0, "recent": 0.0, "last_red": False})
        last5 = games[-5:]
        for m in games:
            side = "home" if m["home"] == team else "away"
            for name, s, starter, y, r, f in m["players"]:
                if s != side:
                    continue
                p = stats[name]
                p["eq"] += 1 if starter else SUB_WEIGHT
                p["booked"] += (y + r) > 0
                if m in last5:
                    p["recent"] += (1 if starter else SUB_WEIGHT) / len(last5)
        last = games[-1]
        side = "home" if last["home"] == team else "away"
        for name, s, starter, y, r, f in last["players"]:
            if s == side and r > 0:
                stats[name]["last_red"] = True
        factor = self.match_factor(team, before, expected_team_cards)
        if lineup:                       # confirmed starters: they will play
            for name in lineup:
                stats[name]["recent"] = 1.0
                stats[name]["last_red"] = False
            stats = {n: stats[n] for n in lineup}
        out = []
        for name, p in stats.items():
            if p["recent"] < MIN_PLAY or p["last_red"]:
                continue
            rate = (p["booked"] + PRIOR_GAMES * self.prior) / (p["eq"] + PRIOR_GAMES)
            lam = -math.log(1 - min(rate, 0.9)) * min(p["recent"], 1.0) * factor
            out.append({"player": name, "chance": round(100 * (1 - math.exp(-lam))),
                        "booked": p["booked"], "games": round(p["eq"], 1)})
        return sorted(out, key=lambda x: -x["chance"])


def top_picks(model, home_espn, away_espn, date, exp_home_cards, exp_away_cards, n=3, lineup=None):
    """The n players most likely to be booked in this match (both teams).
    lineup: {"home": [names], "away": [names]} once announced, else None."""
    rows = []
    for team, side, exp in ((home_espn, "home", exp_home_cards), (away_espn, "away", exp_away_cards)):
        if team:
            for c in model.candidates(team, date, exp, (lineup or {}).get(side)):
                rows.append({**c, "team": side, "confirmed": bool(lineup)})
    return sorted(rows, key=lambda x: -x["chance"])[:n]
