# Data probe — 2026-11-24T21:01:40+00:00

**API-Football:** HTTP 200 · account {'plan': 'Pro', 'active': True, 'requests': {'current': 0, 'limit_day': 7500}} · after run {'current': 20, 'limit_day': 7500}

| League | API name | Season | Stats flag | Player flag | Sample | Corners | SOT | Player SOT rows | Error |
|---|---|---|---|---|---|---|---|---|---|
| Premier League | Premier League (England) | 2026 | True | True | Brentford v Everton 2026-11-23 | True | True | 40/40 |  |
| La Liga | La Liga (Spain) | 2026 | True | True | Levante v Elche 2026-11-23 | True | True | 46/46 |  |
| Serie A | Serie A (Italy) | 2026 | True | True | Monza v Fiorentina 2026-11-23 | True | True | 47/47 |  |
| Bundesliga | Bundesliga (Germany) | 2026 | True | True | Werder Bremen v Hamburger SV 2026-11-22 | True | True | 40/40 |  |
| Ligue 1 | Ligue 1 (France) | 2026 | True | True | Marseille v Le Mans 2026-11-22 | True | True | 40/40 |  |
| UEFA Champions League | UEFA Champions League (World) | 2026 | True | True |  |  |  | / | no finished fixture returned |
| UEFA Europa League | UEFA Europa League (World) | 2026 | True | True | Torreense v Ararat-Armenia 2026-11-05 | True | True | 45/45 |  |
| UEFA Conference League | UEFA Europa Conference League (World) | 2026 | True | True | Universitatea Craiova v Egnatia Rrogozhinë 2026-11-05 | True | True | 31/42 |  |
| MLS | Major League Soccer (USA) | 2026 | True | True | St. Louis City v Los Angeles FC 2026-11-24 | True | True | 40/40 |  |
| Championship | Championship (England) | 2026 | True | True |  |  |  | / | no finished fixture returned |
| League One | League One (England) | 2026 | True | True |  |  |  | / | no finished fixture returned |
| League Two | League Two (England) | 2026 | True | True | York v Walsall 2026-11-21 | True | True | 36/36 |  |
| 2. Bundesliga | 2. Bundesliga (Germany) | 2026 | True | True | Karlsruher SC v VfL Osnabrück 2026-11-22 | True | True | 40/40 |  |
| Serie B | Serie B (Italy) | 2026 | True | True | Palermo v Sudtirol 2026-11-24 | True | True | 43/43 |  |
| Segunda Division | Segunda División (Spain) | 2026 | True | True | AD Ceuta FC v Almeria 2026-11-23 | True | True | 45/45 |  |
| Ligue 2 | Ligue 2 (France) | 2026 | True | True | Sochaux v Dunkerque 2026-11-23 | True | True | 40/40 |  |
| Eredivisie | Eredivisie (Netherlands) | 2026 | True | True | GO Ahead Eagles v Fortuna Sittard 2026-11-22 | True | True | 41/41 |  |
| Primeira Liga | Primeira Liga (Portugal) | 2026 | True | True | Rio Ave v SC Braga 2026-11-08 | True | True | 46/46 |  |
| Super Lig | Süper Lig (Turkey) | 2026 | True | True | Başakşehir v Çorum FK 2026-11-23 | True | True | 32/42 |  |
| Scottish Premiership | Premiership (Scotland) | 2026 | True | True | Motherwell v Rangers 2026-11-21 | True | True | 40/40 |  |
| Belgian Pro League | Jupiler Pro League (Belgium) | 2026 | True | True | Lommel United v Standard Liege 2026-11-22 | True | True | 31/40 |  |
| Greek Super League | Super League 1 (Greece) | 2026 | True | True | Asteras Tripolis v Aris Thessalonikis 2026-11-23 | True | True | 45/45 |  |
| Austrian Bundesliga | Bundesliga (Austria) | 2026 | True | True | Austria Vienna v Red Bull Salzburg 2026-11-22 | True | True | 40/40 |  |
| Eliteserien | Eliteserien (Norway) | 2026 | True | True | Sarpsborg 08 FF v Lillestrom 2026-11-22 | True | True | 40/40 |  |
| Liga MX | Liga MX (Mexico) | 2026 | True | True | Club Queretaro v Necaxa 2026-11-23 | True | True | 42/42 |  |
| Brasileirao | Serie A (Brazil) | 2026 | True | True | Santos v Gremio 2026-11-24 | True | True | 46/46 |  |
| Argentina Liga Profesional | Liga Profesional Argentina (Argentina) | 2026 | True | True | Gimnasia L.P. v Newells Old Boys 2026-11-23 | True | True | 46/46 |  |

**balldontlie** (tested 2026-11-23):

- teams (free): HTTP 200, rows 89
- games (free): HTTP 200, rows 10
- game player stats (ALL-STAR): HTTP 401, rows None — Unauthorized
- player injuries (ALL-STAR): HTTP 401, rows None — Unauthorized
- box scores (GOAT): HTTP 401, rows None — Unauthorized
- season averages (GOAT): HTTP 401, rows None — Unauthorized
