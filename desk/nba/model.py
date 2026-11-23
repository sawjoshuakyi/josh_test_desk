"""NBA player-prop projection model (v1; dispersion tuned on Nov 3-11, 2026, see reports/backtest_nba.json).

mean(stat) = projected minutes x projected per-minute rate, where
  minutes = recent-weighted minutes, adjusted for a starting-role change, minutes freed by
            absent rotation teammates, and blowout risk from the pregame spread;
  rate    = season per-minute rate shrunk toward the league rate, blended with recent form,
            boosted for usage freed by absent teammates and scaled by the game total (pace).
P(stat >= k) integrates over minutes uncertainty (Gauss-Hermite) with a stat-specific
count distribution: points use a normal approximation (made baskets are worth 2-3), the
others a negative binomial. Dispersion parameters are fit on past games (see backtest).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy import stats as st

STATS = ["pts", "reb", "ast", "threes"]
COMBOS = {"pra": ["pts", "reb", "ast"], "pr": ["pts", "reb"], "pa": ["pts", "ast"], "ra": ["reb", "ast"]}
GH_X, GH_W = np.polynomial.hermite_e.hermegauss(11)
GH_W = GH_W / GH_W.sum()


@dataclass
class Params:
    min_halflife: float = 4.0       # games
    rate_halflife: float = 8.0      # games
    recent_weight: float = 0.4      # weight on recent-form rate vs season rate
    shrink_minutes: float = 60.0    # prior minutes toward the league per-minute rate
    redistribute: float = 0.6       # share of absent teammates' minutes handed to the remaining rotation
    usage_boost: dict = field(default_factory=lambda: {"pts": 0.35, "reb": 0.25, "ast": 0.35, "threes": 0.30})
    blowout_per_pt: float = 0.006   # starters lose this fraction of minutes per spread point beyond 5
    pace_exp: float = 0.5           # mean scales with (game total / league average total) ** pace_exp
    min_sd_frac: float = 0.22       # minutes standard deviation as a fraction of projected minutes
    min_sd_floor: float = 3.0
    pts_var_a: float = 2.8          # points variance = a * mean + (c * mean) ** 2
    pts_var_c: float = 0.14
    nb_r: dict = field(default_factory=lambda: {"reb": 10.8, "ast": 6.0, "threes": 3.6})


def _ewm_last(values: np.ndarray, halflife: float) -> float:
    if len(values) == 0:
        return float("nan")
    alpha = 1 - math.exp(math.log(0.5) / halflife)
    w = (1 - alpha) ** np.arange(len(values))[::-1]
    return float(np.sum(w * values) / np.sum(w))


class Projector:
    def __init__(self, history: pd.DataFrame, params: Params | None = None):
        """history: box-score rows strictly before the games being projected."""
        self.p = params or Params()
        h = history.sort_values("date")
        self.played = h[h.dnp == 0]
        tot_min = self.played.minutes.sum()
        self.league_rate = {s: (self.played[s].sum() / tot_min if tot_min else 0.0) for s in STATS}
        games = h.drop_duplicates(["game_id", "team"])
        self.league_total = float(games.drop_duplicates("game_id").total.dropna().mean() or 225.0)
        self.by_player = {pid: g for pid, g in self.played.groupby("player_id")}
        self.team_games = {t: g.sort_values("date") for t, g in h.groupby("team")}
        self._reg_cache: dict = {}
        self._ewm_cache: dict = {}

    def _team_regulars(self, team: str, n_games: int = 5, min_avg: float = 18.0) -> dict:
        if team in self._reg_cache:
            return self._reg_cache[team]
        self._reg_cache[team] = self._compute_regulars(team, n_games, min_avg)
        return self._reg_cache[team]

    def _recent_minutes(self, pid) -> float:
        if pid not in self._ewm_cache:
            g = self.by_player.get(pid)
            self._ewm_cache[pid] = (_ewm_last(g.minutes.to_numpy(float), self.p.min_halflife)
                                    if g is not None and len(g) >= 3 else 0.0)
        return self._ewm_cache[pid]

    def _compute_regulars(self, team: str, n_games: int, min_avg: float) -> dict:
        tg = self.team_games.get(team)
        if tg is None:
            return {}
        last = tg.drop_duplicates("game_id").game_id.tolist()[-n_games:]
        rec = tg[tg.game_id.isin(last) & (tg.dnp == 0)]
        avg = rec.groupby("player_id").agg(minutes=("minutes", "sum"), pts=("pts", "sum"), reb=("reb", "sum"),
                                            ast=("ast", "sum"), threes=("threes", "sum"))
        avg = avg / max(len(last), 1)
        team_tot = avg[STATS].sum()
        return {"avg": avg[avg.minutes >= min_avg], "team_tot": team_tot}

    def project(self, player_id, team: str, available_ids: set, starter: bool | None,
                spread: float | None, total: float | None) -> dict | None:
        """Project one player's minutes and per-stat means for an upcoming game.

        available_ids: player ids on `team` expected to play (used to detect absent regulars).
        """
        g = self.by_player.get(player_id)
        if g is None or len(g) < 3:
            return None
        p = self.p
        mins = g.minutes.to_numpy(float)
        m = _ewm_last(mins, p.min_halflife)
        start_rate = g.starter.mean()
        if starter is True and start_rate < 0.5:
            m += 6.0
        elif starter is False and start_rate > 0.5:
            m -= 6.0
        reg = self._team_regulars(team)
        out_share = {s: 0.0 for s in STATS}
        if reg and len(reg["avg"]):
            absent = reg["avg"][~reg["avg"].index.isin(available_ids)]
            if len(absent):
                freed = absent.minutes.sum()
                rot_min = sum(self._recent_minutes(pid) for pid in available_ids)
                if rot_min > 0:
                    m += min(8.0, p.redistribute * freed * max(m, 0) / rot_min)
                for s in STATS:
                    tt = reg["team_tot"][s]
                    out_share[s] = float(absent[s].sum() / tt) if tt else 0.0
        if spread is not None and not np.isnan(spread) and (starter or start_rate >= 0.5):
            m *= 1 - p.blowout_per_pt * max(0.0, abs(spread) - 5)
        m = float(np.clip(m, 0, 44))
        pace = 1.0
        if total is not None and not np.isnan(total) and self.league_total:
            pace = (total / self.league_total) ** p.pace_exp
        tot_min = g.minutes.sum()
        means = {}
        for s in STATS:
            season = (g[s].sum() + p.shrink_minutes * self.league_rate[s]) / (tot_min + p.shrink_minutes)
            per_min = np.divide(g[s].to_numpy(float), np.maximum(mins, 1))
            recent = _ewm_last(per_min, p.rate_halflife)
            rate = (1 - p.recent_weight) * season + p.recent_weight * recent
            rate *= 1 + p.usage_boost[s] * out_share[s]
            means[s] = rate * m * (pace if s in ("pts", "ast", "threes") else 1.0)
        sd_m = max(p.min_sd_floor, p.min_sd_frac * m)
        return {"minutes": m, "minutes_sd": sd_m, "means": means, "rates": {s: means[s] / m if m else 0 for s in STATS}}

    # ---------------------------------------------------------------- probabilities
    def prob_at_least(self, proj: dict, stat: str, k: float) -> float:
        """P(stat >= k). For a line of 10.5 pass k=11. stat may be a combo (pra, pr, pa, ra)."""
        p = self.p
        parts = COMBOS.get(stat, [stat])
        mins = np.clip(proj["minutes"] + proj["minutes_sd"] * GH_X, 0, 48)
        prob = 0.0
        for M, w in zip(mins, GH_W):
            mu = sum(proj["rates"][s] * M for s in parts)
            if mu <= 0:
                prob += w * (1.0 if k <= 0 else 0.0)
                continue
            if stat == "pts" or len(parts) > 1:
                var = 0.0
                for s in parts:
                    ms = proj["rates"][s] * M
                    var += p.pts_var_a * ms + (p.pts_var_c * ms) ** 2 if s == "pts" else ms + ms ** 2 / p.nb_r[s]
                prob += w * (1 - st.norm.cdf(k - 0.5, loc=mu, scale=math.sqrt(max(var, 1e-6))))
            else:
                r = p.nb_r[stat]
                prob += w * float(st.nbinom.sf(k - 1, r, r / (r + mu)))
        return float(min(max(prob, 1e-4), 1 - 1e-4))
