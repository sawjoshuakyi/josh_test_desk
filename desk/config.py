"""Desk-wide settings. Change numbers here, not in the code."""
import datetime as _dt
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/Toronto")   # Josh's time zone; handles daylight saving


def et_today() -> _dt.date:
    return _dt.datetime.now(ET).date()


BANKROLL = 2500.0          # dollars
UNIT = BANKROLL * 0.01     # 1 unit = 1% of bankroll ($25)

KELLY_FRACTION = 0.25      # quarter-Kelly
MAX_BET_PCT = 0.02         # no single bet above 2% of bankroll ($50)
MAX_GAME_PCT = 0.04        # no more than 4% of bankroll riding on one game across all bets
MAX_PARLAY_PCT = 0.005     # parlays are capped at 0.5% of bankroll ($12.50)
LOTTO_PCT = 0.002          # lottos are a fixed 0.2% of bankroll ($5) — entertainment budget
DAILY_RISK_PCT = 0.10      # stop adding bets once 10% of bankroll is at risk in one day ($250)

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

# Game-line markets (cheap: 1 credit per market per sport call). Used for "beat the sharp price" edges.
GAME_MARKETS = ["h2h", "spreads", "totals"]
SOCCER_SPORTS = ["soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a", "soccer_germany_bundesliga",
                 "soccer_france_ligue_one", "soccer_uefa_champs_league", "soccer_usa_mls"]
MARKET_EDGE_FLAG = 0.02    # DK/FD price beats Pinnacle's no-vig fair price by 2%+ in expected value
MIN_CREDITS = 60           # stop making Odds API calls once fewer credits than this remain

NFL_PROP_MARKETS = [
    "player_receptions", "player_reception_yds", "player_rush_yds", "player_rush_attempts",
    "player_pass_yds", "player_pass_attempts", "player_pass_completions", "player_pass_tds", "player_anytime_td",
]
NFL_ALT_MARKETS = [
    "player_receptions_alternate", "player_reception_yds_alternate", "player_rush_yds_alternate",
    "player_pass_yds_alternate",
]
FACTS_ROWS = 60            # reasoning bullets are written for the top-N positive-edge props per sport
NFL_LOW_TRUST = {"pass_yds", "pass_cmp"}  # model lost to the naive baseline out of sample: treat as advisory only
# Markets whose model is calibrated but not yet better than a strong baseline: require a bigger edge
MEDIUM_TRUST_EDGE = 0.05
TENNIS_MEDIUM_TRUST = {"totals", "spreads", "set_betting"}
SOCCER_MARKETS = ["h2h", "totals", "alternate_totals", "alternate_totals_corners", "player_shots_on_target"]
