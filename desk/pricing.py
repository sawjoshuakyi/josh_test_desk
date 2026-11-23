"""Odds math: conversions, no-vig fair prices, edge, Kelly staking, parlays."""
from __future__ import annotations

import math
from typing import Iterable, Sequence

from . import config


def american_to_decimal(odds: float) -> float:
    if odds >= 100:
        return 1 + odds / 100
    if odds <= -100:
        return 1 + 100 / abs(odds)
    raise ValueError(f"not an American price: {odds}")


def decimal_to_american(dec: float) -> float:
    if dec <= 1:
        raise ValueError("decimal odds must be above 1")
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))


def implied_prob(odds: float) -> float:
    """Probability implied by a price, vig included."""
    return 1 / american_to_decimal(odds)


def prob_to_american(p: float) -> float:
    if not 0 < p < 1:
        raise ValueError("probability must be between 0 and 1")
    return decimal_to_american(1 / p)


def devig_multiplicative(prices: Sequence[float]) -> list[float]:
    """Remove the margin by scaling implied probabilities to sum to 1."""
    raw = [implied_prob(p) for p in prices]
    total = sum(raw)
    return [r / total for r in raw]


def devig_power(prices: Sequence[float], tol: float = 1e-10) -> list[float]:
    """Power method: find k with sum(p_i ** k) = 1. Handles favourite-longshot bias better."""
    raw = [implied_prob(p) for p in prices]
    lo, hi = 0.5, 3.0
    for _ in range(200):
        k = (lo + hi) / 2
        s = sum(r ** k for r in raw)
        if abs(s - 1) < tol:
            break
        if s > 1:
            lo = k
        else:
            hi = k
    return [r ** k for r in raw]


def fair_two_way(over_price: float, under_price: float, method: str = "power") -> float:
    """No-vig probability of the first side of a two-way market."""
    fn = devig_power if method == "power" else devig_multiplicative
    return fn([over_price, under_price])[0]


def overround(prices: Iterable[float]) -> float:
    return sum(implied_prob(p) for p in prices) - 1


def edge(model_prob: float, price: float) -> float:
    """Expected value per $1 staked at this price."""
    return model_prob * american_to_decimal(price) - 1


def kelly_fraction(model_prob: float, price: float) -> float:
    """Full-Kelly fraction of bankroll (0 when there is no edge)."""
    b = american_to_decimal(price) - 1
    f = (b * model_prob - (1 - model_prob)) / b
    return max(0.0, f)


def kelly_stake(model_prob: float, price: float, kind: str = "single",
                bankroll: float = config.BANKROLL) -> float:
    """Dollar stake under the desk's staking rules.

    kind: "single" (quarter-Kelly, capped at MAX_BET_PCT), "parlay" (quarter-Kelly,
    capped at MAX_PARLAY_PCT), "lotto" (fixed LOTTO_PCT).
    """
    if kind == "lotto":
        return round(bankroll * config.LOTTO_PCT, 2)
    cap = config.MAX_PARLAY_PCT if kind == "parlay" else config.MAX_BET_PCT
    f = kelly_fraction(model_prob, price) * config.KELLY_FRACTION
    return round(bankroll * min(f, cap), 2)


def parlay_decimal(prices: Sequence[float]) -> float:
    out = 1.0
    for p in prices:
        out *= american_to_decimal(p)
    return out


def parlay_american(prices: Sequence[float]) -> float:
    return decimal_to_american(parlay_decimal(prices))


def parlay_prob(probs: Sequence[float]) -> float:
    """Joint probability assuming independent legs (same-game legs are NOT independent)."""
    return math.prod(probs)


def clv(bet_price: float, closing_price: float) -> float:
    """Closing line value in probability points: positive means we beat the close."""
    return implied_prob(closing_price) - implied_prob(bet_price)


def brier(probs: Sequence[float], outcomes: Sequence[int]) -> float:
    return sum((p - o) ** 2 for p, o in zip(probs, outcomes)) / len(probs)


def log_loss(probs: Sequence[float], outcomes: Sequence[int], eps: float = 1e-6) -> float:
    total = 0.0
    for p, o in zip(probs, outcomes):
        p = min(max(p, eps), 1 - eps)
        total += -(o * math.log(p) + (1 - o) * math.log(1 - p))
    return total / len(probs)


def calibration_table(probs: Sequence[float], outcomes: Sequence[int],
                      edges: Sequence[float] = (0, .5, .6, .7, .8, .9, 1.0001)) -> list[dict]:
    rows = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        idx = [i for i, p in enumerate(probs) if lo <= p < hi]
        if not idx:
            continue
        rows.append({
            "bucket": f"{lo:.0%}-{min(hi, 1):.0%}",
            "n": len(idx),
            "avg_pred": sum(probs[i] for i in idx) / len(idx),
            "hit_rate": sum(outcomes[i] for i in idx) / len(idx),
        })
    return rows
