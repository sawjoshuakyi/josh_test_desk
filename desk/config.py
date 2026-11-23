"""Desk-wide settings. Change numbers here, not in the code."""

BANKROLL = 2500.0          # dollars
UNIT = BANKROLL * 0.01     # 1 unit = 1% of bankroll ($25)

KELLY_FRACTION = 0.25      # quarter-Kelly
MAX_BET_PCT = 0.02         # no single bet above 2% of bankroll ($50)
MAX_GAME_PCT = 0.04        # no more than 4% of bankroll riding on one game across all bets
MAX_PARLAY_PCT = 0.005     # parlays are capped at 0.5% of bankroll ($12.50)
LOTTO_PCT = 0.002          # lottos are a fixed 0.2% of bankroll ($5) — entertainment budget
DAILY_RISK_PCT = 0.10      # stop adding bets once 10% of bankroll is at risk in one day

EDGE_FLAG = 0.03           # a leg is a "model edge" when model prob beats the no-vig market by 3+ points
MIN_PRICE = -800           # parlay legs priced worse than this add almost no value

# Books. Pinnacle is the sharp benchmark; DraftKings and FanDuel are where Josh bets.
SHARP_BOOK = "pinnacle"
BET_BOOKS = ["draftkings", "fanduel"]
ALL_BOOKS = ["pinnacle", "draftkings", "fanduel"]

ODDS_API_BASE = "https://api.the-odds-api.com/v4"

NBA_PROP_MARKETS = [
    "player_points", "player_rebounds", "player_assists",
    "player_points_rebounds_assists", "player_threes",
]
NBA_ALT_MARKETS = [
    "player_points_alternate", "player_rebounds_alternate", "player_assists_alternate",
]
