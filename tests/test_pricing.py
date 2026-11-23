import math
from desk import pricing as p, odds

def test_conversions():
    assert math.isclose(p.american_to_decimal(-110), 1.9090909, rel_tol=1e-6)
    assert p.american_to_decimal(150) == 2.5
    assert p.decimal_to_american(2.5) == 150
    assert p.decimal_to_american(1.5) == -200
    assert math.isclose(p.implied_prob(-200), 2/3, rel_tol=1e-9)

def test_devig():
    fair = p.devig_multiplicative([-110, -110])
    assert math.isclose(fair[0], 0.5)
    pw = p.devig_power([-150, 130])
    assert math.isclose(sum(pw), 1, abs_tol=1e-6) and pw[0] > 0.5
    assert math.isclose(p.fair_two_way(-110, -110), 0.5, abs_tol=1e-6)

def test_kelly_and_caps():
    assert p.kelly_fraction(0.5, -110) == 0
    f = p.kelly_fraction(0.6, 100)            # b=1 -> f = 0.2
    assert math.isclose(f, 0.2)
    assert p.kelly_stake(0.6, 100) == 50.0    # quarter-Kelly 5% capped at 2% of 2500
    assert p.kelly_stake(0.52, 100) == 25.0   # 0.04*0.25 = 1% -> $25
    assert p.kelly_stake(0.9, 500, kind="parlay") == 12.5
    assert p.kelly_stake(0.01, 5000, kind="lotto") == 5.0

def test_parlay_and_metrics():
    assert p.parlay_american([100, 100]) == 300
    assert math.isclose(p.parlay_prob([0.5, 0.5]), 0.25)
    assert p.clv(-110, -130) > 0
    assert math.isclose(p.brier([1, 0], [1, 0]), 0)
    rows = p.calibration_table([0.55, 0.65, 0.95], [1, 0, 1])
    assert sum(r["n"] for r in rows) == 3

def test_flatten_and_pair():
    payload = {"id": "e1", "commence_time": "2026-11-24T00:00:00Z", "home_team": "A", "away_team": "B",
      "bookmakers": [{"key": "draftkings", "markets": [{"key": "player_points", "outcomes": [
        {"name": "Over", "description": "X Y", "price": -115, "point": 20.5},
        {"name": "Under", "description": "X Y", "price": -105, "point": 20.5}]}]}]}
    rows = odds.flatten(payload, "props", "basketball_nba")
    pairs = odds.pair_two_way(rows)
    assert pairs[("e1", "player_points", "X Y", 20.5)]["draftkings"] == {"Over": -115, "Under": -105}
