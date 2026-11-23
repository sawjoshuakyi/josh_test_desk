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
3. Each day, put that day's legs files in `legs/`. The workflow runs at 6:50 AM and 6:50 PM ET
   (one hour later on the clock during daylight saving time, since GitHub schedules run in UTC).
4. To start a run by hand: Actions → live-tracker → Run workflow → choose am or pm.

Public repositories get unlimited free Actions minutes. Private repositories get 2,000 free minutes
a month, which two long daily windows would exceed; on a private repo, run only the pm window or
track from your own computer.

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
