# PM session (NBA + weekday NFL) — runs ~4:27 PM ET

Session label "PM"; board/legs file session "pm". Doc title: "Betting Desk — [Weekday, Month Day] PM".
Discord: sport channel = NBA_NFL, plus GENERAL.

SCOPE: today's NBA slate, plus any NFL games still to be played today EXCEPT Sundays (Sunday NFL has its own run) —
e.g. Thursday Night, Monday Night, Saturday or holiday games. If a sport has no games today, its analyst reports
"No slate today" and produces nothing.

Follow common.md: STEP 0 → MODEL BOARD → STEP 1 (below) → MANAGER → REPORT DOC → LOGGING → LIVE TRACKER FILE →
DISCORD → FINISH.

## STEP 1 — Analyst agents (one per sport in scope, in parallel, via the Agent tool)
Give each the Active and Testing Playbook rules for its sport, the ODDS and MODEL BOARD sections of common.md, the
board file contents for its sport, and this brief:

"You are a professional [SPORT] betting analyst. Research today's [SPORT] slate (Eastern Time) with real due
diligence and deliver four slips:
 1. BEST BET of the day (single bet or single prop).
 2. DOUBLE-UP parlay: any number of legs, combined odds at least +100 (aim +100 to +130).
 3. +400 to +700 parlay.
 4. LOTTO parlay of 10 or more legs.
Start from the model board: its highest-edge rows are your candidate list, and every NBA points/rebounds/assists/
threes/PRA leg uses the board's model probability (adjust only for news after the board was built, max 8 points,
with the reason). Research requirements: confirm schedule and tip/kickoff times; the newest official injury report
(NBA posts several per day), expected starters, rest/back-to-backs and late scratches; DK and FD prices; recent form
(last 5/10) vs season baselines; matchup data (defense vs position, pace, rebounding, usage shifts when teammates are
out, home/away splits); coaching tendencies (minutes management, blowouts, back-to-backs, rotation changes); spreads of
10+ points as blowout flags. NFL: target share, snap share, game script, pass/run rates, blitz/pressure, red-zone
usage, weather. Follow the SOURCES POLICY in common.md: compute matchup and form numbers yourself from the repo's
box scores and raw stat tables; use official injury reports and team announcements for availability; never use
anyone's previews, picks or write-ups. Verify roster details, because rosters change.
Rules: follow the Playbook. Every leg shows (a) line, DK and FD prices, (b) probability, its source, the no-vig market
probability and edge, (c) 2–4 specific data points with sources, (d) the main way it loses. Never use a player listed
questionable/doubtful/game-time decision unless confirmed active. Stress-test against blowout and game-script
scenarios and prefer thresholds a player clears with reduced minutes. Build parlays from legs that win in the SAME
game script; never pair legs that work against each other. Return a structured report with sources."

Note: a late-news job re-checks the NBA injury report at 6:35 PM and 9:35 PM ET and posts any slip leg whose model
probability moved; mention this in the header message.
