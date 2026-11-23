"""Surface-blended Elo for ATP and WTA singles (k0, surface weight and shrink tuned on 2023-2024; see reports/backtest_tennis.json).

Ratings follow the common tennis Elo recipe: K = K0 / (matches_played + offset) ** shape, with a
separate rating per surface. A match prediction blends overall and surface Elo. Best-of-five
probabilities are derived from the best-of-three probability through the implied set-win rate.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass

import pandas as pd

SURFACES = ("Hard", "Clay", "Grass")


@dataclass
class EloParams:
    k0: float = 200.0
    offset: float = 5.0
    shape: float = 0.4
    surface_weight: float = 0.3   # blend: (1 - w) * overall + w * surface
    shrink: float = 0.85          # pull probabilities toward 50% (raw Elo is overconfident at the extremes)
    start: float = 1500.0


def norm_surface(s) -> str:
    s = str(s or "").strip().capitalize()
    return "Hard" if s in ("Carpet", "", "Nan", "None") else s


def win_prob(r_a: float, r_b: float) -> float:
    return 1 / (1 + 10 ** ((r_b - r_a) / 400))


def best_of_five(p3: float) -> float:
    """Convert a best-of-3 match probability into best-of-5 via the implied set probability."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        s = (lo + hi) / 2
        if s * s * (3 - 2 * s) < p3:
            lo = s
        else:
            hi = s
    s = (lo + hi) / 2
    return s ** 3 * (10 - 15 * s + 6 * s * s)


class Elo:
    def __init__(self, params: EloParams | None = None):
        self.p = params or EloParams()
        self.overall = defaultdict(lambda: self.p.start)
        self.surface = {s: defaultdict(lambda: self.p.start) for s in SURFACES}
        self.n = defaultdict(int)
        self.n_surface = {s: defaultdict(int) for s in SURFACES}

    def _k(self, n: int) -> float:
        return self.p.k0 / (n + self.p.offset) ** self.p.shape

    def rating(self, player: str, surface: str) -> float:
        surface = norm_surface(surface)
        w = self.p.surface_weight
        return (1 - w) * self.overall[player] + w * self.surface[surface][player]

    def predict(self, a: str, b: str, surface: str, best_of: int = 3) -> float:
        p3 = win_prob(self.rating(a, surface), self.rating(b, surface))
        p = best_of_five(p3) if int(best_of or 3) == 5 else p3
        return 0.5 + (p - 0.5) * self.p.shrink

    def update(self, winner: str, loser: str, surface: str) -> None:
        surface = norm_surface(surface)
        e = win_prob(self.overall[winner], self.overall[loser])
        kw, kl = self._k(self.n[winner]), self._k(self.n[loser])
        self.overall[winner] += kw * (1 - e)
        self.overall[loser] -= kl * (1 - e)
        es = win_prob(self.surface[surface][winner], self.surface[surface][loser])
        kws, kls = self._k(self.n_surface[surface][winner]), self._k(self.n_surface[surface][loser])
        self.surface[surface][winner] += kws * (1 - es)
        self.surface[surface][loser] -= kls * (1 - es)
        self.n[winner] += 1
        self.n[loser] += 1
        self.n_surface[surface][winner] += 1
        self.n_surface[surface][loser] += 1


def is_completed(score) -> bool:
    s = str(score or "").upper()
    return bool(s) and "W/O" not in s and "WALKOVER" not in s and "DEF" not in s and s != "NAN"


def build(matches: pd.DataFrame, params: EloParams | None = None) -> dict[str, Elo]:
    """Fit one Elo per tour from a chronologically sorted results table."""
    tours = {}
    df = matches.sort_values(["tourney_date", "match_num"], kind="stable")
    for tour, g in df.groupby("tour"):
        elo = Elo(params)
        for r in g.itertuples():
            if is_completed(r.score):
                elo.update(r.winner_name, r.loser_name, r.surface)
        tours[tour] = elo
    return tours
