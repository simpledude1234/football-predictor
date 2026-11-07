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
"""
import math
from collections import defaultdict

SUB_WEIGHT = 0.35       # a substitute appearance ~ a third of a match
PRIOR_GAMES = 20.0      # strong pull towards average: tested on 4 weeks of replays (promised ~20%, ~20% happened)
MIN_PLAY = 0.8          # only suggest regular players


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

    def candidates(self, team, before, expected_team_cards, lineup=None):
        """Players of `team` with their chance of being booked in the next match.
        lineup: the confirmed starting eleven (names), if already announced."""
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
