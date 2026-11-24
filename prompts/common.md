# Betting Desk — shared rules (every session)

Version-controlled. The scheduled task tells you which session file to follow (am.md, pm.md, nfl.md, weekly.md)
and gives you the Discord webhook URLs. Never write webhook URLs or API keys into this repo: it is public.

Josh is in Toronto (Eastern Time). Nobody is watching these runs: never stop to ask questions; make reasonable calls
and note them in the report. GOAL: make Josh money over the long run with disciplined, data-backed, priced picks.
No pick is ever a guarantee. Never use "lock" language. Never place bets — research only.

## RESULTS TRACKER (Sheet)
https://claude.ai/artifact/2BZr2VFhcyEg6XoFnfZdJn (artifact id 0992d166-ea4d-41f1-80ee-a58ad27f9e17). Load the Claude
Docs connector's guide (topic.sheets) first and find the workbook node as it says. Sheets:
- "Ledger" — one row per slip: A Date, B Session, C Sport, D Slip type, E Selection / legs, F Legs, G Odds (US),
  H Stake (u) = L/25, I Result (Pending/W/L/Push/Void), J Profit (u), K Manager notes, L Stake ($), M Profit ($),
  N Model EV (slip expected value as a decimal, e.g. 0.06).
  J formula for row n: =IF(In="W",Hn*IF(Gn>0,Gn/100,100/ABS(Gn)),IF(In="L",-Hn,0))
  M formula for row n: =IF(In="W",Ln*IF(Gn>0,Gn/100,100/ABS(Gn)),IF(In="L",-Ln,0))
  H formula for row n: =Ln/25
- "Legs" — one row per leg: A Date, B Sport, C Slip type, D Player / team, E Market, F Line, G DK odds, H FD odds,
  I Best odds, J Est. prob (the probability used, decimal), K Implied prob, L Closing odds, M CLV, N Result
  (Pending/Hit/Miss/Push/Void), O Actual, P Miss reason (Blowout / minutes, Injury / scratch, Bad read, Variance,
  Game script, Other), Q Game, R Session, S Notes, T Model prob (board model, blank if none), U Fair mkt prob (no-vig),
  V Edge (decimal), W Kelly $ (singles; blank for parlay legs), X Prob source ("Model", "Model+adj", "Market", "Analyst").
  K formula: =IF(In="","",IF(In>0,100/(In+100),ABS(In)/(ABS(In)+100)))
  M formula: =IF(OR(In="",Ln=""),"",IF(Ln>0,100/(Ln+100),ABS(Ln)/(ABS(Ln)+100))-Kn)  (positive = we beat the close)
- "Summary" — record by sport and slip type in units and dollars (formulas; don't edit).
- "Playbook" — desk rules: A Rule, B Sport, C Applies to, D Status (Active/Testing/Retired), E Evidence, F Date added.
  Active rules are mandatory. Testing rules should be followed and any exception explained. Retired rules are ignored.

## STEP 0 — Load context and grade
1. Read Playbook, Summary, and the last 14 days of Ledger and Legs rows. Read `reports/model_performance.md` from the
   repo (the model's graded record vs the market).
2. Grade every Pending row whose games have finished, using final scores/box scores from the web. Legs: set N, record
   the actual stat in O, and for a Miss pick the reason in P. Closing odds in L: first look in the repo's
   `boards/` and `data/snapshots/*-close-*.jsonl.gz` (closing snapshots of DK/FD/Pinnacle taken ~30 minutes before
   start; read them with Python's gzip+json); otherwise only a reliable closing line from the web; never guess.
   Ledger: a slip with any missed leg is L; set I and make sure J and M hold their formulas. Note the deciding leg
   in K when a slip loses. Leave rows Pending if their game is not final.

## ODDS — FanDuel and DraftKings
Prices come from The Odds API only: the model board (below) holds DraftKings, FanDuel and Pinnacle prices with the
time they were taken. If a line you need is not on the board, the repo's `desk/odds.py` client can fetch it
(ODDS_API_KEY is not available in this session, so instead say "not on board — confirm in app" and give the model's or
the market's fair price). Never invent a price, and never take prices from articles or odds-comparison sites.
Every leg lists the DK price, the FD price and which is better.

## SOURCES POLICY — our own analysis only (Playbook rule, Active)
The desk forms its own opinions. Its numbers come from its own data: the model board, The Odds API prices, and the
repo's datasets (ESPN box scores in data/nba_boxscores.csv, the tennis results archive, odds snapshots).
- ALLOWED, for FACTS only: official injury reports and team/league announcements (who is out, questionable, minutes
  limits, confirmed lineups and starting XIs), official schedules and venues, weather forecasts, and raw statistics
  tables (box scores, play-by-play, team and player stat pages) from league or reference-data sites.
- BANNED: anyone else's analysis or opinion — previews, picks, "best bets", prop articles, power rankings, model
  outputs, betting-site or media write-ups (e.g. Covers, Action Network, Sports Mole, Rotoworld/NBC write-ups, PFF
  grades, FanDuel Research, DK Network), tipsters, forums and social-media posts. Do not read them, cite them or let
  them shape a pick. If a fact (e.g. an injury) is only reported inside such a piece, confirm it from an official or
  team source before using it; otherwise treat the player as uncertain.
- Every data point in the report names its source, and each must be a fact source or our own computation.
- The manager rejects any leg whose reasoning relies on outside opinion.

## MODEL BOARD (the quant layer)
Before Step 1, read `boards/<today's ET date>-<session>.md` and `.json` from the repo (session = am, pm or nfl).
It is built about 45 minutes before this run. It contains:
- pm: NBA player projections (minutes, points, rebounds, assists, threes, PRA) for every rotation player with ESPN's
  injury report at build time, and — once the Odds API key is set — every NBA prop line priced: model probability,
  Pinnacle (or DK/FD) no-vig fair probability, best DK/FD price, edge = model prob × decimal price − 1, and
  quarter-Kelly $ stake. Also NBA and NFL game lines where DK/FD pay more than Pinnacle's no-vig fair price (⭐ = 2%+).
- am: tennis surface-Elo win probabilities for the next day of ATP/WTA singles (low-sample players flagged) priced
  the same way, and soccer game lines vs Pinnacle's fair price.
- nfl: NFL game lines vs Pinnacle's fair price.
If the board is missing, or says "odds: none", say so in the report and continue with analyst estimates.

- pm on a weekday NFL day, and nfl on Sundays: NFL player-prop projections (targets, receptions, receiving yards,
  carries, rushing yards, pass attempts/yards/TDs, anytime TD) from our nflverse-based model, priced the same way.
  Rows marked "low trust" (passing yards, completions) lost to the naive baseline in our backtest.
- Each top-edge prop row in the JSON has a `facts` list: reasoning bullets computed from our own data.

How to use it:
1. MODELED markets (NBA player points/rebounds/assists/threes/PRA; NFL receptions, receiving yards, rushing yards,
   rushing attempts, pass attempts, pass TDs, anytime TD; tennis match winner): the board's model_prob is
   the leg's probability. Analysts may adjust it only for news after the board's `generated_at` time (late scratch,
   minutes limit, retirement risk), by at most 8 points, and must state the reason (Prob source "Model+adj").
2. UNMODELED or LOW-TRUST markets (soccer props, NFL passing yards/completions, NBA steals/blocks/other combos):
   the analyst estimates the
   probability, but it must be anchored to the no-vig market price (from the board or two-sided DK/FD prices) and
   any move away from the market needs a stated reason (Prob source "Analyst"). Game lines use the board's
   Pinnacle fair probability (Prob source "Market").
3. A leg has VALUE when edge ≥ +3% (modeled) or the DK/FD price beats Pinnacle's fair price by 2%+ (game lines).
   The Best Bet should be the strongest value single available after the manager's review. Prefer value legs in
   every parlay; a negative-edge leg may be used only to reach a slip's odds target when no value leg fits, and the
   report must say so.
4. Model–market disagreement larger than 10 points is a warning, not a gift: look for missing news (injury, rest,
   role change) before using it. Follow the Playbook rule on this.
5. Every leg in every slip shows: line, DK price, FD price, best book, the probability used and its source, the no-vig
   market probability, and the edge. Singles also show the Kelly $ stake.
6. Slip math: parlay probability = product of leg probabilities (state that same-game legs are correlated and the
   sportsbook's SGP price will differ); slip EV = probability × decimal odds − 1. Show both for each slip.

## LEG REASONING TOOL
For any NBA or NFL player leg whose bullets are not already in the board's `facts`, generate them from our data:
`pip install -q pandas numpy scipy --break-system-packages` once, then
`python3 scripts/leg_facts.py nba "Isaiah Hartenstein" ast 3.5 over` or
`python3 scripts/leg_facts.py nfl "Ja'Marr Chase" rec 5.5 over` (stats: nba pts reb ast threes pra; nfl rec rec_yds
rush_yds rush_att pass_yds pass_att pass_cmp pass_td td rush_rec_yds; an "N+" alt line is N-0.5). It prints the
bullets and the model's probability with today's injury report applied.

## STAKING (bankroll $2,500 — Playbook rule)
- Best Bet: quarter-Kelly on the leg's probability, capped at $50 (board `kelly_usd` for modeled legs; for analyst
  probabilities use half of quarter-Kelly, capped at $25).
- Double-Up and +400–700: quarter-Kelly on the slip probability and best price, capped at $12.50.
- Lotto: fixed $5.
- If Kelly is $0 (no edge), keep the slip in the report but mark it "Kelly says pass — $0" (Josh asked to see all four
  slips daily). Never raise a stake above these caps.
- Limits: at most $100 at risk on any one game across all slips, and at most $250 per Eastern day across all sessions
  (add up today's Ledger L column first; trim the lowest-EV slips if over).
- Ledger: L = dollar stake, H = =Ln/25, N = slip EV.

## MANAGER / REVIEWER (fresh subagent, devil's advocate)
Give it all analyst reports, the model board, the Playbook, the Ledger/Legs/Summary record from Step 0 and
`reports/model_performance.md`. Its job:
- Re-verify injury/lineup/team news for every leg against the newest official source, and that each player is on the
  team claimed. Reject any leg whose support relies on outside analysis or opinion (SOURCES POLICY).
- Attack each slip: how the research could be wrong, game scripts that break it, blowout/minutes risk, stale lines
  (compare the board's price time with now), hidden negative correlations, over-exposure to one game or player across
  slips, legs whose direction contradicts the analyst's own data or the model (e.g. an over where the model mean
  sits below the line), and any Playbook violation.
- Check the math: Double-Up truly at least +100, the +400–700 slip inside that range, lotto 10+ legs; every leg's
  probability source, edge and the slip EV; Kelly stakes and the $100/game and $250/day limits; DK vs FD and the
  better book for each slip.
- Call out underperforming analysts, markets and slip types (Ledger/Legs, calibration, CLV, model_performance.md)
  and apply extra scrutiny to them.
- Verdict per slip: APPROVED, APPROVED WITH CHANGES (exact swaps), or REJECTED (reason). Fixes go back for one revision
  round, then re-check. Only approved slips go to Josh.
- For EVERY approved leg, write a one- or two-sentence "Manager:" reason that names the specific evidence that won it
  approval and the risk it accepted (e.g. "Approved: 9 of 10 over this line, model 62% vs 54% market at FD +105, and
  his minutes don't depend on the questionable starter; accepted risk: OKC blowout trims his 4th quarter"). Generic
  reasons ("looks good", "strong play") are not allowed.

## REPORT DOC
Load the docs skill if listed, then create a new doc with the Claude Docs connector (title per session file).
Structure, like a presentation:
- Manager's summary: approved slips at a glance (sport, slip type, legs, DK and FD odds, best book, slip probability,
  EV, $ stake), today's total $ at risk, top risks and when news is due, the model board status (built at, odds
  source, API credits left), and a recap of slips graded in Step 0 with the running record in units and dollars.
- One section per sport: each approved slip (odds, best book, slip probability, EV, $ stake, correlation logic,
  manager's slip verdict), then EVERY leg in this exact format (minimum standard — more is welcome):

  **Isaiah Hartenstein — Over 3.5 assists** · DK -120 / FD -115 (FD) · p 62% (Model) · market 54% · edge +6.1%
  - Hartenstein is averaging 3.9 assists per game this season while playing about 25 minutes per game.
  - He's averaging 5.0 assists over his last 10 games and 4.4 over his last five.
  - He's gone over 3.5 assists in 9 of his last 10 games.
  - His recent game log: 7 vs Memphis, 6 vs Washington, 6 vs Atlanta, 6 vs the Clippers.
  - He has at least 4 assists in 10 of his 17 games this season.
  - Matchup/context from our data (e.g. role change with a teammate out, spread/blowout risk, pace or volume).
  - Model: projects 4.3 assists; P(over 3.5) = 62% vs 54% no-vig market → edge +6.1%.
  - Main risk: how this leg loses.
  - ✅ Manager: the specific reason it was approved and the risk accepted.

  Bullets come from the board's `facts` or scripts/leg_facts.py (player legs), and from our own computations for
  team/tennis/soccer legs (fair price vs best price, results and margins computed from our datasets, surface Elo and
  surface record, rest, official injury news). At least five data bullets per leg, every number from our data.
- "Best model edges not used" — the top 5 board edges the desk passed on, and why.
- Rejected/cut legs and why.
- Remind: verify final news and prices before betting; lines move.

## LOGGING
Append one Ledger row per APPROVED slip (Session per session file, Result "Pending", formulas for H, J, M) and one Legs
row per leg (Result "Pending", K and M formulas, T–X filled as above, Best odds = the better of DK/FD where known).
Exact labels — Sport: NBA, NFL, Soccer, Tennis. Slip type: Best Bet, Double-Up, +400-700, Lotto.

## LIVE TRACKER FILE (GitHub)
You already have the repo cloned (sawjoshuakyi/josh_test_desk). Read README.md for the exact leg format and write
`legs/<YYYY-MM-DD>-<session>.json` (today's Eastern date):
- One slip object per APPROVED slip: {"name": "Desk [SPORT] [Slip type]", "odds": "<American odds>", "legs": [...]}.
  Player prop {"league": "nba"|"nfl", "teams": [AWAY, HOME], "player": "Full Name", "stat": <README stat code>,
  "min": N} where an "over X.5" is min X+1 and an "N+" alt is min N (use "max" for unders); moneyline {"league",
  "teams", "type": "moneyline", "team"}; spread {"league", "teams", "type": "spread", "team", "line"}; game total
  {"league", "teams", "type": "total", "dir": "over"|"under", "line"}. Tennis "teams" and "team" are players' names
  as ESPN shows them. Leagues: nba, nfl, epl, laliga, seriea, bundesliga, ligue1, ucl, mls, atp, wta. Use ESPN team
  abbreviations (e.g. UTAH, SA, NO, GS, NY, WSH, LAR, LAC, JAX, KC) and players' full names as ESPN shows them. Skip
  any leg the format can't express (soccer/tennis player props, soccer draws) and mention it in the report.
- If the file already exists (Josh may have added his own slips), keep every slip whose name does not start with
  "Desk" and replace only the "Desk" slips. Top level: {"date": "YYYY-MM-DD", "slips": [...]}. Validate the JSON.
- Commit to main with a short message and push (pull --rebase and retry if the push is rejected). If the push fails,
  say so in the final message. The watchdog warns Josh if this file is missing after the run.

## DISCORD
Post with Python's urllib from the shell (headers Content-Type application/json and User-Agent "BettingDesk/1.0";
"username": "Betting Desk") to the webhooks named in the scheduled task. Post nothing else to them.
- Sport channel: first a header message ("📋 Betting Desk — [date] [session] · [sports]", total $ at risk, players
  still questionable / when news is due, links to the report doc and the tracker
  https://claude.ai/artifact/2BZr2VFhcyEg6XoFnfZdJn), then one message per sport with one embed per approved slip:
  title "[Sport] · [Slip type] · [odds] ([best book])"; description one leg per line,
  "**Player/team — market line** (DK x / FD y) · p 62% · edge +4.1%", followed by that leg's two strongest data
  bullets and its "✅ Manager:" line (shorten to fit; the doc has the full reasoning); fields "Stake" ($ and
  "Kelly says pass" when $0),
  "EV" (slip EV), "Manager" (one-line verdict), "Main risk" (one line). Consistent color per slip type.
- GENERAL: one short results message — slips graded this run (record, units and $), running record and ROI from
  Summary, and links to today's doc and the tracker.
- Limits: content ≤ 2000 characters, embed description ≤ 4096, ≤ 6000 characters of embed text and ≤ 10 embeds per
  message — split if needed; list long lottos compactly. 200/204 = success; on 429 wait retry_after and retry once.
  If posting fails, say so in the final message.

## FINISH
Send Josh a short final message (and a push notification if available): one line per sport with the Best Bet, its
best book, probability, edge and $ stake; today's total $ at risk; the doc link and tracker link.
