import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desk.soccer.data import same_team
from desk.soccer.model import dixon_coles
from desk.tennis.score import match_dist, p_cover, p_game, p_tiebreak, p_total_over, parse_games


def test_hold_probability_known_values():
    assert abs(p_game(0.5) - 0.5) < 1e-9
    assert abs(p_game(0.64) - 0.813) < 0.002


def test_tiebreak_symmetric():
    assert abs(p_tiebreak(0.65, 0.65) - 0.5) < 1e-9


def test_match_distribution_is_consistent():
    d = match_dist(0.66, 0.62, 3)
    assert abs(sum(d["total_games"].values()) - 1) < 1e-9
    assert abs(sum(d["set_scores"].values()) - 1) < 1e-9
    assert abs(d["p_a"] - (d["set_scores"][(2, 0)] + d["set_scores"][(2, 1)])) < 1e-9
    assert 0 <= p_total_over(d["total_games"], 22.5) <= 1
    assert p_cover(d["margin"], -3.5) < p_cover(d["margin"], -1.5)


def test_parse_games():
    assert parse_games("6-4 3-6 7-6(5)") == (16, 16)
    assert parse_games("6-2 3-1 RET") is None
    assert parse_games("W/O") is None


def test_dixon_coles_sums_to_one():
    m = dixon_coles(1.6, 1.1, -0.06)
    assert abs(m.sum() - 1) < 1e-9 and np.all(m >= 0)


def test_team_name_matching():
    assert same_team("Brighton & Hove Albion", "Brighton and Hove Albion")
    assert same_team("Bayern Munich", "FC Bayern Munich")
    assert not same_team("Manchester United", "Manchester City")


def test_team_name_matching_hard_cases():
    assert same_team("Internazionale", "Inter Milan")
    assert same_team("Paris Saint-Germain", "PSG")
    assert same_team("Wolverhampton Wanderers", "Wolves")
    assert not same_team("Real Madrid", "Real Sociedad")
    assert not same_team("AC Milan", "Inter Milan")
    assert same_team("Borussia Dortmund", "Dortmund")
