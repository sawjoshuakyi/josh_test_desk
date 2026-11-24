"""Soccer models: team ratings for goals, shots on target and corners, and a player shots-on-target model.

Team ratings: log(rate) = base + home + attack[team] - defence[opponent], fitted by time-decayed, ridge-penalised
Poisson likelihood across all leagues at once (Champions League games link the leagues). The goals target blends
actual goals with shots on target x league conversion (a shot-quality-free xG proxy) to cut noise.
Match outcome: Dixon-Coles corrected Poisson for home/draw/away and total goals.
Corners: same rating structure on corners won; totals simulated with a negative binomial (corners are overdispersed).
Player SOT: decayed SOT per 90 shrunk to a position prior x expected minutes x (team's expected SOT today / its usual).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import optimize
from scipy.stats import nbinom, poisson

POS_GROUP = {"G": "GK"}
for c in ("CD", "CD-L", "CD-R", "LB", "RB", "SW", "D", "LWB", "RWB"):
    POS_GROUP[c] = "DEF"
for c in ("CM", "CM-L", "CM-R", "DM", "LM", "RM", "M", "RCM", "LCM"):
    POS_GROUP[c] = "MID"
for c in ("AM", "AM-L", "AM-R"):
    POS_GROUP[c] = "AM"
for c in ("F", "CF", "CF-L", "CF-R", "LF", "RF", "RCF", "LCF", "ST"):
    POS_GROUP[c] = "FWD"
SOT_PRIOR = {"GK": 0.0, "DEF": 0.13, "MID": 0.28, "AM": 0.55, "FWD": 0.95}  # SOT per 90 by position group


@dataclass
class SoccerParams:
    half_life_days: float = 365.0
    ridge: float = 6.0
    xg_weight: float = 0.6          # weight on the shots-on-target proxy in the goals target
    rho: float = -0.06              # Dixon-Coles low-score correlation
    corner_disp: float = 18.0       # negative binomial size for each team's corners
    sot_k_minutes: float = 900.0    # minutes at which a player's own SOT rate gets half weight
    sot_half_life_days: float = 300.0
    sot_disp: float = 6.0           # negative binomial size for player SOT


def fit_ratings(m: pd.DataFrame, target: pd.Series, asof: str, p: SoccerParams) -> dict:
    """Fit attack/defence ratings on rows before `asof`. Returns dict with base, home, att, dfn (by team_id)."""
    d = m[m.date < asof].copy()
    d["y"] = target.loc[d.index]
    d = d.dropna(subset=["y"])
    age = (pd.Timestamp(asof) - pd.to_datetime(d.date)).dt.days.to_numpy(float)
    w = 0.5 ** (age / p.half_life_days)
    teams = pd.Index(sorted(set(d.team_id) | set(d.opp_id)))
    ti, oi = teams.get_indexer(d.team_id), teams.get_indexer(d.opp_id)
    home, y, n = d.home.to_numpy(float), d.y.to_numpy(float), len(teams)

    def nll(theta):
        base, h, att, dfn = theta[0], theta[1], theta[2:2 + n], theta[2 + n:]
        eta = base + h * home + att[ti] - dfn[oi]
        mu = np.exp(eta)
        ll = w * (y * eta - mu)
        reg = p.ridge * (att @ att + dfn @ dfn) / 2
        g = w * (y - mu)
        grad = np.zeros_like(theta)
        grad[0], grad[1] = g.sum(), (g * home).sum()
        grad[2:2 + n] = np.bincount(ti, g, n) - p.ridge * att
        grad[2 + n:] = -np.bincount(oi, g, n) - p.ridge * dfn
        return -(ll.sum() - reg), -grad

    x0 = np.zeros(2 + 2 * n)
    x0[0] = np.log(max(np.average(y, weights=w), 1e-3))
    res = optimize.minimize(nll, x0, jac=True, method="L-BFGS-B", options={"maxiter": 500})
    th = res.x
    return {"base": th[0], "home": th[1], "att": dict(zip(teams, th[2:2 + n])), "dfn": dict(zip(teams, th[2 + n:]))}


def rate(r: dict, team: str, opp: str, home: int) -> float:
    return float(np.exp(r["base"] + r["home"] * home + r["att"].get(team, 0.0) - r["dfn"].get(opp, 0.0)))


def dixon_coles(lh: float, la: float, rho: float, max_g: int = 10) -> np.ndarray:
    g = np.arange(max_g + 1)
    mat = np.outer(poisson.pmf(g, lh), poisson.pmf(g, la))
    tau = np.ones_like(mat)
    tau[0, 0] = 1 - lh * la * rho
    tau[0, 1] = 1 + lh * rho
    tau[1, 0] = 1 + la * rho
    tau[1, 1] = 1 - rho
    mat = mat * np.clip(tau, 0, None)
    return mat / mat.sum()


class SoccerModel:
    def __init__(self, matches: pd.DataFrame, players: pd.DataFrame, asof: str, params: SoccerParams | None = None):
        self.p = params or SoccerParams()
        self.m, self.pl, self.asof = matches, players, asof
        hist = matches[matches.date < asof]
        self.conv = hist.goals.sum() / max(hist.shotsOnTarget.sum(), 1)
        goal_target = (1 - self.p.xg_weight) * matches.goals + self.p.xg_weight * matches.shotsOnTarget * self.conv
        self.goals = fit_ratings(matches, goal_target, asof, self.p)
        self.sot = fit_ratings(matches, matches.shotsOnTarget, asof, self.p)
        self.corners = fit_ratings(matches, matches.wonCorners, asof, self.p)
        self._by_player = {pid: g for pid, g in players[players.date < asof].groupby("player_id")}
        self._team_avg_sot = hist.groupby("team_id").apply(
            lambda g: np.average(g.shotsOnTarget, weights=0.5 ** ((pd.Timestamp(asof) - pd.to_datetime(g.date)).dt.days
                                                                    / self.p.half_life_days)),
            include_groups=False).to_dict()

    # ---------------------------------------------------------------- match markets
    def match(self, home_id: str, away_id: str, neutral: bool = False) -> dict:
        h = 0 if neutral else 1
        lh, la = rate(self.goals, home_id, away_id, h), rate(self.goals, away_id, home_id, 0)
        mat = dixon_coles(lh, la, self.p.rho)
        tot = np.array([sum(mat[i, j] for i in range(mat.shape[0]) for j in range(mat.shape[1]) if i + j == k)
                        for k in range(2 * mat.shape[0] - 1)])
        ch, ca = rate(self.corners, home_id, away_id, h), rate(self.corners, away_id, home_id, 0)
        return {"lambda_home": lh, "lambda_away": la,
                "p_home": float(np.tril(mat, -1).sum()), "p_draw": float(np.trace(mat)), "p_away": float(np.triu(mat, 1).sum()),
                "goals_pmf": tot, "btts": float(mat[1:, 1:].sum()),
                "sot_home": rate(self.sot, home_id, away_id, h), "sot_away": rate(self.sot, away_id, home_id, 0),
                "corners_home": ch, "corners_away": ca}

    @staticmethod
    def p_total_over(pmf: np.ndarray, line: float) -> float:
        return float(pmf[int(np.floor(line)) + 1:].sum())

    def corners_total_pmf(self, ch: float, ca: float, max_c: int = 40) -> np.ndarray:
        k = np.arange(max_c + 1)
        r = self.p.corner_disp
        a = nbinom.pmf(k, r, r / (r + ch))
        b = nbinom.pmf(k, r, r / (r + ca))
        return np.convolve(a, b)[: max_c + 1]

    # ---------------------------------------------------------------- players
    def player_rows(self, team_id: str) -> pd.DataFrame:
        pl = self.pl[(self.pl.team_id == team_id) & (self.pl.date < self.asof)]
        return pl

    def player_sot(self, player_id: str, team_id: str, opp_id: str, home: int, starter: bool | None = None,
                   minutes: float | None = None) -> dict | None:
        g = self._by_player.get(player_id)
        if g is None or g.empty:
            return None
        pos_rows = g[(g.pos != "SUB") & g.pos.notna()]
        modes = pos_rows.pos.mode()
        group = POS_GROUP.get(modes.iloc[0] if len(modes) else "M", "MID")
        age = (pd.Timestamp(self.asof) - pd.to_datetime(g.date)).dt.days.to_numpy(float)
        w = 0.5 ** (age / self.p.sot_half_life_days)
        mins_w, sot_w = float((w * g.minutes).sum()), float((w * g.sot).sum())
        k = self.p.sot_k_minutes
        per90 = (sot_w + SOT_PRIOR[group] * k / 90) / (mins_w + k) * 90
        recent = g.tail(6)
        if starter is None:
            starter = recent.starter.mean() >= 0.5
        if minutes is None:
            pool = g[g.starter == int(starter)].tail(8)
            minutes = float(pool.minutes.mean()) if len(pool) else (80.0 if starter else 20.0)
        exp_team = rate(self.sot, team_id, opp_id, home)
        usual = self._team_avg_sot.get(team_id, exp_team)
        factor = float(np.clip(exp_team / usual, 0.6, 1.6)) if usual else 1.0
        mu = per90 * minutes / 90 * factor
        return {"mean": mu, "per90": per90, "minutes": minutes, "starter": bool(starter), "team_factor": factor,
                "group": group, "n": len(g)}

    def p_sot_at_least(self, mu: float, k: int) -> float:
        r = self.p.sot_disp
        return float(1 - nbinom.cdf(k - 1, r, r / (r + mu))) if k > 0 else 1.0
