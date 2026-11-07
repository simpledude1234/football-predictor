# Football Predictor

## Everyday use
- **On the PC:** double-click **Football Predictor** on the desktop. It downloads the latest results and fixtures (about 30 seconds), then opens the page.
- The shortcut opens **predictions.html**: the simple tips page (one pick per market, by league and date, ★ = strongest picks). "Detailed view" at the bottom opens **details.html** with all the numbers.
- Leagues: Premier League, Championship, Serie A, Serie B, La Liga, Ligue 1, Bundesliga, Scottish Premiership, plus Champions League, Europa League and Conference League (marked "new, not yet tested").
- European cup fixtures and odds come from ESPN's free public feed. Teams are rated from their own league (13 leagues covered). Teams from other leagues lean on bookmaker odds.
- Code backup: private GitHub project simpledude1234/football-predictor.
- Website: https://ftips-2eb50e.pages.dev (Cloudflare Pages). Rebuilt about 06:17 and 15:47 UK time every day, even with the PC off. On match days it also rebuilds shortly before kick-offs, so player picks use the confirmed line-ups. To update it right now: GitHub → the project → Actions → "Update predictions" → Run workflow.
- Update on Friday morning for weekend games and on Tuesday for midweek. Fixtures appear a few days before each round.

## The page
- **Matches:** tap one to see all 14 markets. Matches that have kicked off are hidden.
- **Check a bookmaker price** (inside each match): choose a market, type the line and the odds, and it shows our chance, the fair odds and whether there is value.
- **Weekend standouts:** matches furthest above or below the league normal for each market.
- **My record:** every prediction is saved before kick-off and scored once results come in.
- **How good is it?:** the honest test on 1,480 past matches.
- ⚠ **little data** badge: a team with fewer than 10 matches in our data (usually newly promoted).
- A yellow banner appears when the predictions are more than 20 hours old.

## Live tab (games in play)
- Shows each game in play with the minute, score and stats, and a live pick per market (result, both teams to score, shots, shots on target, bookings, fouls). Updates every minute while the tab is open.
- How it works: what has happened so far + what the pre-match model still expects for the time left. A pick needs at least a 72% chance on a line that isn't already decided. Picks only between 20 and 75 minutes (the window that was tested).
- Tested on 308 past games, not used to set it up, at 20, 30, 45, 60 and 75 minutes: about 79 in 100 picks landed (78 at half-time, 79 at 60 minutes). These are mostly safe lines at short odds, so check the bookmaker price.
- Privacy: your browser only talks to this site. A small Cloudflare program on the site (`functions/api/live.js`) fetches ESPN's free scores, so ESPN never sees you. It only answers for our 11 competitions and keeps replies 30 seconds.
- Re-test: `py -3.13 tools/fetch_events.py`, `py -3.13 tools/live_prematch.py`, `py -3.13 tools/live_backtest_data.py`, then `node tools/live_backtest.js --write` (updates `live_params.json`).

## Reading a match
- **Expected**: the number the model expects.
- **Main line**: the over/under line nearest 50/50.
- **Safer tips (72%+)**: the highest Over line and lowest Under line with at least a 72% chance.
- **Tips page lines**: for shots, shots on target, fouls and bookings, the tip is the line where this game stands out most from a normal game in that league (at least a 72% chance, and at least 5 points more likely than that line normally is). If the game looks normal, it says "No tip".
- **Fair odds** = 100 / chance. Bookmaker odds above fair odds = value according to the model.
- Bookings = yellow + red cards. Goal kicks are **estimates** (no free source records them). Offsides, corners and tackles come from ESPN match stats (`team_stats.py`); free kicks = both teams' fouls + offsides.

## Security
- The page cannot run any code except its own (Content-Security-Policy with a fingerprint), cannot load anything from other websites, and shows all text as plain text. The tips page may ask its own site for live scores (`/api/live`); nothing else.
- Downloads: HTTPS, one website only, no redirects, size-capped, checked before replacing the old copy, and never run as code. Impossible numbers are thrown out.
- No server of our own, no open ports, no passwords or API keys, no accounts. The only code that runs on Cloudflare is the live-scores reader, which takes no input except a competition name from a fixed list.
- Library versions are pinned in `requirements.txt`.

## Files
- `fetch_data.py`: downloads free data from football-data.co.uk (3 seasons, 8 leagues).
- `predictor.py`: the model, the honest test and the track record.
- `make_page.py`: builds `predictions.html`. `py -3.13 make_page.py --refit` re-tests the model (this also happens on its own every 14 days).
- `model_params.json`: settings learned from the test. `backtest_results.csv`: every test prediction. `predictions_log.csv`: your saved predictions.

No tool can guarantee wins. Bet only what you can afford to lose. 18+.
