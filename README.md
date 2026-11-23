# Betting Desk — Live Leg Tracker

Posts to Discord the moment a leg hits:
- Player overs (points, rebounds, assists, PRA, yards, receptions, TDs) alert as soon as the number is reached.
- Unders, moneylines and spreads alert at the final. A game-total over alerts as soon as it's passed.
- Also posts when a whole slip cashes 💰 or busts 💥, and a final summary.

Data comes from ESPN's public live scoreboards (NBA, NFL, soccer, tennis). No API key needed.

## Files
- `tracker.py` — the tracker (Python 3, standard library only).
- `legs/YYYY-MM-DD-am.json` / `-pm.json` — the slips to track for each window.
- `.github/workflows/live-tracker.yml` — runs the tracker automatically on GitHub Actions.

## Run it on your own computer
1. Install Python 3 if needed (macOS: `python3 --version` to check).
2. In this folder run:
   ```
   DISCORD_LIVE_WEBHOOK="https://discord.com/api/webhooks/..." python3 tracker.py legs/2026-11-23-pm.json
   ```
   (Windows PowerShell: `$env:DISCORD_LIVE_WEBHOOK="https://..."; python tracker.py legs\2026-11-23-pm.json`)
3. Leave the window open. It checks every 60 seconds and stops by itself once every leg is settled.
   If you close it, run the same command again: it remembers what it already posted (state-<date>.json).

## Run it automatically on GitHub Actions
1. Create a GitHub repository and upload these files (keep the folder structure).
2. Repository → Settings → Secrets and variables → Actions → New repository secret:
   name `DISCORD_LIVE_WEBHOOK`, value = your live-alerts webhook URL.
3. Each day, the desk writes that day's legs files in `legs/`:
   - `<date>-am.json`: soccer + tennis (desk at 1:47 AM ET). Tracked from 3:00 AM ET, follow-ons 8:50 AM and 2:40 PM.
   - `<date>-nfl.json`: Sunday NFL (desk at 10:41 AM ET Sundays). Tracked from 12:50 PM ET, follow-on 6:40 PM.
   - `<date>-pm.json`: NBA + prime-time NFL (desk at 4:27 PM ET). Tracked from 6:50 PM ET, follow-on 10:30 PM.
   Follow-on runs wait for the earlier run of the same session and resume from its saved state.
   GitHub schedules run in UTC, so these are one hour later on the clock during daylight saving time.
4. To start a run by hand: Actions → live-tracker → Run workflow → choose am, nfl or pm.

Public repositories get unlimited free Actions minutes. Private repositories get 2,000 free minutes
a month, which the daily windows would exceed.

## Leg format
```json
{"league": "nba", "teams": ["POR", "PHI"], "player": "Donovan Clingan", "stat": "reb", "min": 7}
{"league": "nba", "teams": ["UTAH", "LAL"], "player": "Some Player", "stat": "pts", "max": 19}
{"league": "nfl", "teams": ["CIN", "WSH"], "type": "moneyline", "team": "CIN"}
{"league": "nfl", "teams": ["CIN", "WSH"], "type": "spread", "team": "CIN", "line": -6}
{"league": "nfl", "teams": ["CIN", "WSH"], "type": "total", "dir": "over", "line": 54.5}
```
- `min` = at least this many (an "over 10.5" is `"min": 11`). `max` = at most this many.
- Leagues: nba, nfl, ncaaf, epl, laliga, seriea, bundesliga, ligue1, ucl, mls, atp, wta.
- NBA stats: pts, reb, ast, stl, blk, threes, pra, pr, pa, ra.
- NFL stats: pass_yds, pass_td, pass_cmp, rush_yds, rush_att, rec, rec_yds, rush_rec_yds, td (anytime TD).
- Team abbreviations are ESPN's (e.g. UTAH, SA, NO, WSH).

Settings (environment variables): `POLL_SECONDS` (60), `MAX_MINUTES` (330), `ALERT_MISSES` (1 = also post misses), `DRY_RUN` (1 = print instead of posting).

## Model layer (pricing, edges, CLV)

| Piece | What it does | When (ET) |
|---|---|---|
| `scripts/board.py` | Model board: NBA prop projections (minutes × rate model) and tennis surface-Elo win probabilities, priced against DraftKings/FanDuel with Pinnacle's no-vig line as the fair benchmark. Also flags DK/FD game lines (NBA, NFL, soccer) that pay more than Pinnacle's fair price. Writes `boards/<date>-<session>.json/.md`. | 1:05 AM (am), 3:45 PM (pm), 10:05 AM Sun (nfl) |
| `scripts/close.py` | Closing-line snapshots of every priced event ~30 min before start → `data/snapshots/`. | every 15 min |
| `scripts/grade_board.py` | Grades past boards: model vs market log loss, CLV, flagged-bet P&L → `reports/model_performance.md`. | with each board |
| `scripts/late_news.py` | Re-checks the NBA injury report, re-projects every slip leg and posts what moved. | 6:35 PM, 9:35 PM |
| `scripts/watchdog.py` | Warns in #general if a desk session's board or legs file is missing, or API credits run low. | 3:15 AM, 5:50 PM, 12:15 PM Sun |

Staking (`desk/config.py`): bankroll $2,500, quarter-Kelly, singles capped at 2% ($50), parlays 0.5% ($12.50),
lottos fixed 0.2% ($5), 4% per game, 10% per day.

### Secrets (Settings → Secrets and variables → Actions)
`ODDS_API_KEY`, `DISCORD_LIVE_WEBHOOK`, `DISCORD_GENERAL_WEBHOOK`, `DISCORD_NBA_NFL_WEBHOOK`,
`DISCORD_TENNIS_SOCCER_WEBHOOK`. Never commit keys or webhook URLs — this repo is public.

Without `ODDS_API_KEY` the board still writes projections; edges and stakes appear once the key is set.
Credit use is roughly 8 per NBA game (props), 3 per sport for game lines and 1 per tennis tour — about
250 a day with closing lines, so a 20K-credit plan is needed (the free 500 will not last a week).

Cron times are UTC set for Eastern Standard Time; after the switch to daylight time in March every job runs one
hour later in Eastern terms.

Tennis data: Jeff Sackmann's ATP/WTA match archive (CC BY-NC-SA 4.0, non-commercial use) plus ESPN results.
