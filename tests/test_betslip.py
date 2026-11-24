import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from desk.betslip import draftkings, fanduel, slip_links


def test_fanduel_single_and_parlay():
    one = fanduel([{"sid": "29165", "market_sid": "42.448600011"}])
    assert one == "https://sportsbook.fanduel.com/addToBetslip?marketId=42.448600011&selectionId=29165"
    two = fanduel([{"sid": "1", "market_sid": "42.1"}, {"sid": "2", "market_sid": "42.2"}])
    assert two == ("https://sportsbook.fanduel.com/addToBetslip?marketId[0]=42.1&selectionId[0]=1"
                   "&marketId[1]=42.2&selectionId[1]=2")
    assert fanduel([{"sid": "1"}]) is None


def test_draftkings_joins_outcomes():
    a = {"link": "https://sportsbook.draftkings.com/event/123?outcomes=0QA1"}
    b = {"link": "https://sportsbook.draftkings.com/event/456?outcomes=0QA2"}
    assert draftkings([a, b]) == "https://sportsbook.draftkings.com/event/123?outcomes=0QA1+0QA2"


def test_slip_links_needs_every_leg():
    rows = [{"label": "A", "links": {"fanduel": {"sid": "1", "market_sid": "42.1", "link": "x"}}},
            {"label": "B", "links": {}}]
    out = slip_links(rows)
    assert out["fanduel"] is None and out["per_leg"][0]["fanduel"] == "x"


def test_fanduel_ids_from_link():
    leg = {"link": "https://sportsbook.fanduel.com/addToBetslip?marketId=42.6&selectionId=7"}
    assert fanduel([leg, leg]).endswith("marketId[0]=42.6&selectionId[0]=7&marketId[1]=42.6&selectionId[1]=7")
