"""Tennis score model: serve/return point strengths -> exact distributions of games, sets and total games.

Each player's serve points won (spw) and return points won (rpw) are decayed, surface-weighted and shrunk to the tour
average. For a match, A's chance of winning a point on serve = tour_spw + (spw_A - tour_spw) - (rpw_B - tour_rpw),
and likewise for B. Those two numbers are then shifted together until the exact match-win probability equals the
surface Elo's (Elo is the stronger predictor of who wins; serve/return shape decides HOW: tiebreaks, game counts).
Exact dynamic programming over games, tiebreaks and sets gives: P(win), set-score probabilities, total-games pmf and
game-margin pmf (for game handicaps).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SERVE = os.path.join(ROOT, "data", "tennis", "serve_stats.csv.gz")
TOUR_AVG = {"atp": (0.640, 0.360), "wta": (0.565, 0.435)}  # serve points won, return points won


def p_game(p: float) -> float:
    """Server holds, given probability p of winning each point (deuce handled exactly)."""
    q = 1 - p
    deuce = p * p / (1 - 2 * p * q)
    return p ** 4 * (1 + 4 * q + 10 * q * q) + 20 * p ** 3 * q ** 3 * deuce


@lru_cache(maxsize=4096)
def p_tiebreak(pa: float, pb: float) -> float:
    """A wins a 7-point tiebreak; A serves point 1, then servers alternate every two points."""
    def server(n):  # n = points played so far
        return "A" if (n % 4 in (0, 3)) else "B"
    dp = {(0, 0): 1.0}
    win = 0.0
    for _ in range(12):
        nxt = {}
        for (a, b), pr in dp.items():
            n = a + b
            pw = pa if server(n) == "A" else 1 - pb
            for da, db, x in ((1, 0, pw), (0, 1, 1 - pw)):
                na, nb = a + da, b + db
                if na == 7 and nb <= 5:
                    win += pr * x
                elif nb == 7 and na <= 5:
                    continue
                else:
                    nxt[(na, nb)] = nxt.get((na, nb), 0) + pr * x
        dp = nxt
    # from 6-6: each pair of points has one A serve and one B serve
    p66 = dp.get((6, 6), 0.0)
    a2 = pa * (1 - pb)
    b2 = (1 - pa) * pb
    win += p66 * a2 / (a2 + b2) if a2 + b2 > 0 else 0
    return win


def set_dist(pa: float, pb: float, a_serves_first: bool) -> dict:
    """{(games_A, games_B): prob} for one set."""
    ha, hb = p_game(pa), p_game(pb)
    dp = {(0, 0): 1.0}
    out = {}
    while dp:
        nxt = {}
        for (a, b), pr in dp.items():
            a_serving = ((a + b) % 2 == 0) == a_serves_first
            pw = ha if a_serving else 1 - hb
            for da, db, x in ((1, 0, pw), (0, 1, 1 - pw)):
                na, nb = a + da, b + db
                if (na == 6 and nb <= 4) or (nb == 6 and na <= 4) or (na == 7 and nb == 5) or (nb == 7 and na == 5):
                    out[(na, nb)] = out.get((na, nb), 0) + pr * x
                elif na == 6 and nb == 6:
                    # tiebreak: whoever would serve game 13 serves first in the tiebreak
                    tb_a_first = ((12 % 2 == 0) == a_serves_first)
                    t = p_tiebreak(pa, pb) if tb_a_first else 1 - p_tiebreak(pb, pa)
                    out[(7, 6)] = out.get((7, 6), 0) + pr * x * t
                    out[(6, 7)] = out.get((6, 7), 0) + pr * x * (1 - t)
                else:
                    nxt[(na, nb)] = nxt.get((na, nb), 0) + pr * x
        dp = nxt
    return out


def match_dist(pa: float, pb: float, best_of: int = 3) -> dict:
    """Exact match distribution. Returns p_a, set_scores {(sa, sb): p}, total_games pmf, margin pmf (A minus B)."""
    need = 2 if best_of == 3 else 3
    sets = {True: set_dist(pa, pb, True), False: set_dist(pa, pb, False)}
    # state: (sets_a, sets_b, a_serves_first_next_set, games_a, games_b) -> prob; start with A serving (coin toss
    # averaged below)
    finals = {}
    for start in (True, False):
        dp = {(0, 0, start, 0, 0): 0.5}
        while dp:
            nxt = {}
            for (sa, sb, first, ga, gb), pr in dp.items():
                for (x, y), q in sets[first].items():
                    nsa, nsb = sa + (x > y), sb + (y > x)
                    ng_a, ng_b = ga + x, gb + y
                    nfirst = first if (x + y) % 2 == 0 else not first
                    key = (nsa, nsb, nfirst, ng_a, ng_b)
                    if nsa == need or nsb == need:
                        k2 = (nsa, nsb, ng_a, ng_b)
                        finals[k2] = finals.get(k2, 0) + pr * q
                    else:
                        nxt[key] = nxt.get(key, 0) + pr * q
            dp = nxt
    p_a = sum(v for (sa, sb, _, _), v in finals.items() if sa == need)
    set_scores, total, margin = {}, {}, {}
    for (sa, sb, ga, gb), v in finals.items():
        set_scores[(sa, sb)] = set_scores.get((sa, sb), 0) + v
        total[ga + gb] = total.get(ga + gb, 0) + v
        margin[ga - gb] = margin.get(ga - gb, 0) + v
    return {"p_a": p_a, "set_scores": set_scores, "total_games": total, "margin": margin}


def solve_shift(pa: float, pb: float, target: float, best_of: int) -> tuple[float, float]:
    """Shift A's serve prob up and B's down by the same delta until P(A wins) == target."""
    lo, hi = -0.25, 0.25
    for _ in range(30):
        mid = (lo + hi) / 2
        p = match_dist(np.clip(pa + mid, 0.3, 0.95), np.clip(pb - mid, 0.3, 0.95), best_of)["p_a"]
        if p < target:
            lo = mid
        else:
            hi = mid
    d = (lo + hi) / 2
    return float(np.clip(pa + d, 0.3, 0.95)), float(np.clip(pb - d, 0.3, 0.95))


def solve_shift_fast(pa, pb, target, best_of):
    # match win probability is monotone in delta; 18 bisection steps on a 0.5 range is < 0.002 precision
    lo, hi = -0.25, 0.25
    for _ in range(18):
        mid = (lo + hi) / 2
        a, b = float(np.clip(pa + mid, 0.3, 0.95)), float(np.clip(pb - mid, 0.3, 0.95))
        if _p_match_fast(a, b, best_of) < target:
            lo = mid
        else:
            hi = mid
    d = (lo + hi) / 2
    return float(np.clip(pa + d, 0.3, 0.95)), float(np.clip(pb - d, 0.3, 0.95))


def _p_match_fast(pa, pb, best_of):
    s1 = sum(v for (x, y), v in set_dist(pa, pb, True).items() if x > y)
    s2 = sum(v for (x, y), v in set_dist(pa, pb, False).items() if x > y)
    s = (s1 + s2) / 2  # set win prob, averaging who serves first
    if best_of == 3:
        return s * s * (3 - 2 * s)
    return s ** 3 * (10 - 15 * s + 6 * s * s)


GH_X, GH_W = np.polynomial.hermite_e.hermegauss(7)
GH_W = GH_W / GH_W.sum()


def mixture_dist(pa: float, pb: float, sigma: float, best_of: int) -> dict:
    """Match distribution averaged over a per-match swing e ~ N(0, sigma) in A's serve-minus-B's-serve edge."""
    acc = {"p_a": 0.0, "set_scores": {}, "total_games": {}, "margin": {}}
    nodes = zip(GH_X, GH_W) if sigma > 0 else [(0.0, 1.0)]
    for x, w in nodes:
        e = sigma * x / 2
        d = match_dist(float(np.clip(pa + e, 0.3, 0.95)), float(np.clip(pb - e, 0.3, 0.95)), best_of)
        acc["p_a"] += w * d["p_a"]
        for key in ("set_scores", "total_games", "margin"):
            for k, v in d[key].items():
                acc[key][k] = acc[key].get(k, 0) + w * v
    return acc


def solve_shift_mixture(pa, pb, target, best_of, sigma):
    lo, hi = -0.25, 0.25
    for _ in range(16):
        mid = (lo + hi) / 2
        a, b = float(np.clip(pa + mid, 0.3, 0.95)), float(np.clip(pb - mid, 0.3, 0.95))
        p = sum(w * _p_match_fast(float(np.clip(a + sigma * x / 2, 0.3, 0.95)), float(np.clip(b - sigma * x / 2, 0.3, 0.95)),
                                  best_of) for x, w in zip(GH_X, GH_W)) if sigma > 0 else _p_match_fast(a, b, best_of)
        if p < target:
            lo = mid
        else:
            hi = mid
    d = (lo + hi) / 2
    return float(np.clip(pa + d, 0.3, 0.95)), float(np.clip(pb - d, 0.3, 0.95))


@dataclass
class ServeParams:
    sigma: float = 0.10          # per-match swing in serve edge (fitted in scripts/backtest_tennis_games.py)
    half_life_days: float = 365.0
    k_points: float = 500.0      # serve points at which own data gets half weight
    surface_weight: float = 2.0  # same-surface matches count this many times more


class ServeTable:
    """Per-player decayed serve/return point stats, built from data/tennis/serve_stats.csv.gz."""

    def __init__(self, asof: int | None = None, params: ServeParams | None = None, df: pd.DataFrame | None = None):
        self.p = params or ServeParams()
        d = df if df is not None else pd.read_csv(SERVE, low_memory=False)
        if asof is not None:
            d = d[d.tourney_date < asof]
        self.asof = asof or int(d.tourney_date.max()) + 1
        ref = pd.to_datetime(str(self.asof), format="%Y%m%d")
        age = (ref - pd.to_datetime(d.tourney_date.astype(int).astype(str), format="%Y%m%d")).dt.days
        d = d.assign(w=0.5 ** (age / self.p.half_life_days))
        rows = []
        for side, opp in (("w", "l"), ("l", "w")):
            name = "winner_name" if side == "w" else "loser_name"
            r = pd.DataFrame({"tour": d.tour, "player": d[name], "surface": d.surface.fillna("Hard"), "w": d.w,
                              "sv_pts": d[f"{side}_svpt"], "sv_won": d[f"{side}_1stWon"] + d[f"{side}_2ndWon"],
                              "rt_pts": d[f"{opp}_svpt"], "rt_won": d[f"{opp}_svpt"] - d[f"{opp}_1stWon"] - d[f"{opp}_2ndWon"]})
            rows.append(r)
        self.rows = pd.concat(rows, ignore_index=True).dropna()
        self._cache = {}

    def strengths(self, tour: str, player: str, surface: str) -> tuple[float, float, float]:
        key = (tour, player, surface)
        if key in self._cache:
            return self._cache[key]
        r = self.rows[(self.rows.tour == tour) & (self.rows.player == player)]
        sp, rp = TOUR_AVG[tour]
        if r.empty:
            out = (sp, rp, 0.0)
        else:
            w = r.w * np.where(r.surface == surface, self.p.surface_weight, 1.0)
            k = self.p.k_points
            spw = ((w * r.sv_won).sum() + sp * k) / ((w * r.sv_pts).sum() + k)
            rpw = ((w * r.rt_won).sum() + rp * k) / ((w * r.rt_pts).sum() + k)
            out = (float(spw), float(rpw), float(r.sv_pts.sum()))
        self._cache[key] = out
        return out

    def match(self, tour: str, a: str, b: str, surface: str, p_elo: float, best_of: int = 3) -> dict:
        sa, ra, na = self.strengths(tour, a, surface)
        sb, rb, nb = self.strengths(tour, b, surface)
        sp, rp = TOUR_AVG[tour]
        pa = sp + (sa - sp) - (rb - rp)
        pb = sp + (sb - sp) - (ra - rp)
        pa, pb = solve_shift_mixture(pa, pb, p_elo, best_of, self.p.sigma)
        out = mixture_dist(pa, pb, self.p.sigma, best_of)
        out.update(pa_serve=pa, pb_serve=pb, hold_a=p_game(pa), hold_b=p_game(pb), serve_pts_a=na, serve_pts_b=nb)
        return out


def p_total_over(total: dict, line: float) -> float:
    return float(sum(v for g, v in total.items() if g > line))


def p_cover(margin: dict, line: float) -> float:
    """P(A covers a games handicap `line` (e.g. -3.5 means A must win by 4+ games))."""
    return float(sum(v for m, v in margin.items() if m + line > 0))


def parse_games(score: str) -> tuple[int, int] | None:
    """'6-4 3-6 7-6(5)' -> (16, 16) games for winner, loser. None for retirements/walkovers."""
    s = str(score)
    if any(x in s.upper() for x in ("RET", "W/O", "DEF", "ABD", "WALKOVER")):
        return None
    gw = gl = 0
    for part in s.split():
        part = part.split("(")[0]
        if "-" not in part:
            return None
        try:
            x, y = (int(v) for v in part.split("-"))
        except ValueError:
            return None
        gw, gl = gw + x, gl + y
    return (gw, gl) if gw + gl else None
