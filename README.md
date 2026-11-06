# Football Predictor

## Everyday use
- **On the PC:** double-click **Football Predictor** on the desktop. It downloads the latest results and fixtures (about 30 seconds), then opens the page.
- **Anywhere (phone or PC):** the website https://simpledude1234.github.io/football-predictor/ rebuilds itself every morning and afternoon, even when the PC is off. To update it right now: GitHub → the project → Actions → "Update predictions" → Run workflow.
- Update on Friday morning for weekend games and on Tuesday for midweek. Fixtures appear a few days before each round.

## The page
- **Matches:** tap one to see all 14 markets. Matches that have kicked off are hidden.
- **Check a bookmaker price** (inside each match): choose a market, type the line and the odds, and it shows our chance, the fair odds and whether there is value.
- **Weekend standouts:** matches furthest above or below the league normal for each market.
- **My record:** every prediction is saved before kick-off and scored once results come in.
- **How good is it?:** the honest test on 1,480 past matches.
- ⚠ **little data** badge: a team with fewer than 10 matches in our data (usually newly promoted).
- A yellow banner appears when the predictions are more than 20 hours old.

## Reading a match
- **Expected**: the number the model expects.
- **Main line**: the over/under line nearest 50/50.
- **Safer tips (72%+)**: the highest Over line and lowest Under line with at least a 72% chance.
- **Fair odds** = 100 / chance. Bookmaker odds above fair odds = value according to the model.
- Bookings = yellow + red cards. Goal kicks and free kicks are **estimates** (no free source records them).

## Security
- The page cannot run any code except its own (Content-Security-Policy with a fingerprint), cannot load or send anything over the internet, and shows all text as plain text.
- Downloads: HTTPS, one website only, no redirects, size-capped, checked before replacing the old copy, and never run as code. Impossible numbers are thrown out.
- No server, no open ports, no passwords or API keys, no accounts.
- Library versions are pinned in `requirements.txt`.

## Files
- `fetch_data.py`: downloads free data from football-data.co.uk (3 seasons, 8 leagues).
- `predictor.py`: the model, the honest test and the track record.
- `make_page.py`: builds `predictions.html`. `py -3.13 make_page.py --refit` re-tests the model (this also happens on its own every 14 days).
- `model_params.json`: settings learned from the test. `backtest_results.csv`: every test prediction. `predictions_log.csv`: your saved predictions.

No tool can guarantee wins. Bet only what you can afford to lose. 18+.
