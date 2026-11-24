# AM session (Soccer + Tennis) — runs ~1:47 AM ET
Late-news jobs: soccer line-ups are re-checked hourly (posted ~1 hour before kickoff once the XI is out) and tennis
withdrawals hourly — mention this in the header message.

Session label "AM"; board/legs file session "am". Doc title: "Betting Desk — [Weekday, Month Day] AM".
Discord: sport channel = TENNIS_SOCCER, plus GENERAL.

SCOPE: SOCCER and TENNIS matches played today (Eastern date), including overnight/early-morning tennis. NFL is not in
scope. If a sport has no matches, its analyst reports "No slate today". Soccer lineups are not out this early: use
projected XIs, flag rotation risk and say when official team news is due. Step 0 also grades last night's NBA/NFL.

Follow common.md: STEP 0 → MODEL BOARD → STEP 1 (below) → MANAGER → REPORT DOC → LOGGING → LIVE TRACKER FILE →
DISCORD → FINISH.

## STEP 1 — Analyst agents (one per sport in scope, in parallel, via the Agent tool)
Give each the Active and Testing Playbook rules for its sport, the ODDS and MODEL BOARD sections of common.md, the
board file contents for its sport, and this brief:

"You are a professional [SPORT] betting analyst. Research today's [SPORT] slate (Eastern date) with real due diligence
and deliver four slips:
 1. BEST BET of the day (single bet or single prop).
 2. DOUBLE-UP parlay: any number of legs, combined odds at least +100 (aim +100 to +130).
 3. +400 to +700 parlay.
 4. LOTTO parlay of 10 or more legs.
Start from the model board and work through the QUANT CHECKLIST in common.md for every leg.
Tennis: match-winner legs use the board's surface-Elo probability; total games, games handicap and set-score legs use
the score model (medium trust: value needs edge ≥ +5%). Adjust only for news after the board was built (injury,
retirement in the previous round, withdrawal) by at most 8 points, with the reason; treat low-sample players with
extra caution.
Soccer: the desk TARGETS FOUR MARKETS — total goals, match result (1X2), player shots on target and total corners.
Build every soccer slip from these markets (use others only when none of the four offers value, and say so). Each leg
uses the board's model probability for that market; adjust only for confirmed team news, by at most 8 points, with
the reason. Teams flagged low-sample (outside our leagues) need extra caution and a stated reason. Research requirements: start times (ET); injury and suspension
news, projected lineups and rotation risk; DK and FD prices; recent form (last 5/10) vs season baselines; matchup data
(home/away, possession, surface for tennis); managers' rotation habits around midweek fixtures; motivation/schedule
spots; weather and conditions. Soccer: xG/xGA, set pieces, goals trends, confirmed XIs where available. Tennis: hold/
break %, head-to-head, fatigue from prior rounds, retirement risk.
Rules: follow the Playbook. Every leg shows (a) line, DK and FD prices, (b) probability, its source, the no-vig market
probability and edge, (c) 2–4 specific data points with sources, (d) the main way it loses. Never use a player listed
doubtful or awaiting a late fitness test unless confirmed. Stress-test against game-state scenarios (early red card,
early goal, injury retirement). Build parlays from legs that win in the SAME game script. Verify each player's current
team. Follow the SOURCES POLICY in common.md: facts from official and raw-data sources, analysis our own — never previews, picks, articles or social posts. Return a structured report with sources."
