# AM session (Soccer + Tennis) — runs ~1:47 AM ET

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
Start from the model board. Tennis: every match-winner leg uses the board's surface-Elo probability (adjust only for
news after the board was built — injury, retirement in the previous round, withdrawal — max 8 points, with the reason);
treat players flagged low-sample with extra caution. Soccer: game lines start from the board's Pinnacle no-vig fair
prices; ⭐ rows are where DK/FD pay more than fair. Research requirements: start times (ET); injury and suspension
news, projected lineups and rotation risk; DK and FD prices; recent form (last 5/10) vs season baselines; matchup data
(home/away, possession, surface for tennis); managers' rotation habits around midweek fixtures; motivation/schedule
spots; weather and conditions. Soccer: xG/xGA, set pieces, goals trends, confirmed XIs where available. Tennis: hold/
break %, head-to-head, fatigue from prior rounds, retirement risk.
Rules: follow the Playbook. Every leg shows (a) line, DK and FD prices, (b) probability, its source, the no-vig market
probability and edge, (c) 2–4 specific data points with sources, (d) the main way it loses. Never use a player listed
doubtful or awaiting a late fitness test unless confirmed. Stress-test against game-state scenarios (early red card,
early goal, injury retirement). Build parlays from legs that win in the SAME game script. Verify each player's current
team. Return a structured report with sources."
