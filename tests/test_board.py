import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "scripts", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


board = load("board")
grade = load("grade_board")


def test_best_side_picks_higher_payout():
    books = {"draftkings": {"Over": -120}, "fanduel": {"Over": -105}, "pinnacle": {"Over": +110}}
    assert board.best_side(books, "Over") == ("fanduel", -105)  # Pinnacle is a benchmark, not a bet book


def test_fair_prob_prefers_pinnacle():
    books = {"pinnacle": {"Over": -110, "Under": -110}, "draftkings": {"Over": -150, "Under": 120}}
    p, src = board.fair_prob(books, "Over", "Under")
    assert src == "pinnacle" and abs(p - 0.5) < 1e-9


def test_fair_prob_falls_back_to_dk_fd():
    books = {"draftkings": {"Over": -110, "Under": -110}}
    p, src = board.fair_prob(books, "Over", "Under")
    assert src == "dk/fd" and abs(p - 0.5) < 1e-9


def test_line_outcomes(monkeypatch):
    scores = {(frozenset({"bengals", "cincinnati bengals"}), frozenset({"commanders", "washington commanders"})): (27.0, 20.0)}
    monkeypatch.setattr(grade, "final_scores", lambda sport, day: scores)
    base = {"sport": "americanfootball_nfl", "event": "Cincinnati Bengals @ Washington Commanders"}
    assert grade.line_outcome({**base, "market": "h2h", "side": "Cincinnati Bengals", "line": None}, "2026-11-23") == 1
    assert grade.line_outcome({**base, "market": "spreads", "side": "Washington Commanders", "line": 6.5}, "2026-11-23") == 0
    assert grade.line_outcome({**base, "market": "spreads", "side": "Washington Commanders", "line": 7.0}, "2026-11-23") is None
    assert grade.line_outcome({**base, "market": "totals", "side": "Over", "line": 45.5}, "2026-11-23") == 1
