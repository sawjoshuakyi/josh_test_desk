# PM session (NBA + weekday NFL) — runs ~4:27 PM ET

Session label "PM"; board/legs file session "pm". Doc title: "Betting Desk — [Weekday, Month Day] PM".
Discord: sport channel = NBA_NFL, plus GENERAL.

SCOPE: today's NBA slate, plus any NFL games still to be played today EXCEPT Sundays (Sunday NFL has its own run) —
e.g. Thursday Night, Monday Night, Saturday or holiday games. If a sport has no games today, its analyst reports
"No slate today" and produces nothing.

Follow common.md: STEP 0 → MODEL BOARD → NBA SLATE REPORT (below) → STEP 1 (below) → MANAGER → REPORT DOC → LOGGING →
LIVE TRACKER FILE → DISCORD → FINISH.

## NBA SLATE REPORT (Josh's daily scouting report — every day there are NBA games)
GitHub Actions builds reports/nba_slate/<date>.md (and .json) at ~1:20 PM and again ~3:25 PM ET with the latest
injury report. Read it (git pull first). If it is missing or reports/nba_slate/<date>.error.txt exists, say so in
GENERAL and in the desk report, and continue without it.
1. Create a separate doc titled "NBA Slate Report — [Weekday, Month Day]". One section per game, in tip-off order,
   each with these sub-sections, written as plain readable prose and short bullets from the file's numbers (do not
   invent numbers; every figure must be in the file or computed from the repo's data):
   a. Game type — regular season or NBA Cup (with the Cup label; group games count in the standings and point
      differential is a Cup tiebreaker).
   b. Standings and motivation — records, conference ranks, games back of 1st/6th/10th, last 10, streak, rest and
      back-to-backs, and the motivation signals the file lists. State facts; label any judgment as the desk's read.
   c. Strengths and weaknesses — offense/defense per 100 possessions, pace, and what each defense allows to guards,
      lead guards, forwards and centers (e.g. "allows the 3rd-most points to lead guards; shuts down centers' boards").
   d. Mismatches — position and player mismatches from the file, and for each, how that player did against the
      similarly weak defenses and in head-to-head games this season and last.
   e. Player matchups — each key player's role, season vs last-5 form, minutes in the last 3 games, fatigue
      (back-to-back, games in 7 days), and the opponent's rank against his position.
   f. Injuries — the official status, and how the absent player's minutes and shots have been redistributed.
   g. With/without — each teammate's minutes, points, rebounds, assists and shots with vs without the injured player,
      with sample sizes (flag fewer than 5 games without him as a hint, not a trend).
2. Post the doc link to NBA_NFL ("📋 NBA Slate Report — [date]: [link]") before the slips.
3. Give the slate file to the NBA analyst with the board; the analyst cites it in each NBA leg's reasoning (matchup
   rank, with/without numbers, fatigue). The manager rejects an NBA leg that the slate report contradicts without an
   explanation (e.g. an over against a defense ranked in the 5 stingiest at his position).

## STEP 1 — Analyst agents (one per sport in scope, in parallel, via the Agent tool)
Give each the Active and Testing Playbook rules for its sport, the ODDS and MODEL BOARD sections of common.md, the
board file contents for its sport, and this brief:

"You are a professional [SPORT] betting analyst. Research today's [SPORT] slate (Eastern Time) with real due
diligence and deliver five slips:
 1. BEST BET of the day: one single, the highest-probability eligible leg priced -500 or longer.
 2. BANK BUILDER: a single or short parlay with combined odds between -200 and +125 — the steady-win slip.
 3. DOUBLE-UP parlay: combined odds +100 to +150.
 4. +400 to +700 parlay.
 5. LOTTO parlay of 10 or more legs (fixed $2.50). Skip it, with the reason, when the board has fewer than 10 eligible
    legs from separate games.
Start from the model board: its highest-edge rows are your candidate list, and every NBA points/rebounds/assists/
threes/PRA leg uses the board's model probability (adjust only for news after the board was built, max 8 points,
with the reason). Research requirements: confirm schedule and tip/kickoff times; the newest official injury report
(NBA posts several per day), expected starters, rest/back-to-backs and late scratches; DK and FD prices; recent form
(last 5/10) vs season baselines; matchup data (defense vs position, pace, rebounding, usage shifts when teammates are
out, home/away splits); coaching tendencies (minutes management, blowouts, back-to-backs, rotation changes); spreads of
10+ points as blowout flags. NFL: target share, snap share, game script, pass/run rates, blitz/pressure, red-zone
usage, weather; NFL props use the board's model probabilities the same way (passing yards/completions are low trust).
Follow the SOURCES POLICY in common.md: compute matchup and form numbers yourself from the repo's
box scores and raw stat tables; use official injury reports and team announcements for availability; never use
anyone's previews, picks or write-ups. Verify roster details, because rosters change.
Rules: follow the Playbook. Every leg shows (a) line, DK and FD prices, (b) probability, its source, the no-vig market
probability and edge, (c) 2–4 specific data points with sources, (d) the main way it loses. Never use a player listed
questionable/doubtful/game-time decision unless confirmed active. Stress-test against blowout and game-script
scenarios and prefer thresholds a player clears with reduced minutes. Build parlays from legs that win in the SAME
game script; never pair legs that work against each other. Return a structured report with sources."

Note: a late-news job re-checks the NBA injury report at 6:35 PM and 9:35 PM ET and posts any slip leg whose model
probability moved; mention this in the header message.
