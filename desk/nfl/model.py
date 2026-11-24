"""NFL player-prop model: team volume × player share × efficiency, simulated.

For one player-game:
  team dropbacks / rush attempts = team's game-script-adjusted recent volume (EWMA, shrunk to league)
                                   + spread and total effects fitted on 2023-25 team games
  player targets  ~ Binomial(dropbacks, share)      share ~ Beta around the EWMA target share (redistributed
  player carries  ~ Binomial(rush att, share)        when regular teammates are out)
  receptions      ~ Binomial(targets, catch rate)    catch rate, yards per catch, yards per carry, completion %,
  rec yards       ~ Gamma(receptions × yds/catch)    yards per completion and TD rates are shrunk toward position
  rush yards      ~ Normal(carries × ypc)            priors by sample size
  pass att / cmp / yds / TD for QBs; anytime TD ~ Poisson(opportunities × TD rate × implied-points factor)
Returns simulated distributions, so P(stat >= k) works for any main or alt line.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

LEAGUE = {"dropbacks": 35.3, "carries": 26.9}
SCRIPT = {"dropbacks": (0.117, 0.135), "carries": (-0.292, -0.074)}  # (per spread point, per total point above 44)

PRIORS = {  # position priors and the sample size (k) at which own data gets half weight
    "catch": ({"WR": 0.64, "TE": 0.72, "RB": 0.78, "FB": 0.78, "QB": 0.5}, 40),
    "ypr": ({"WR": 12.7, "TE": 10.6, "RB": 7.6, "FB": 7.0, "QB": 8.0}, 30),
    "ypc": ({"RB": 4.3, "FB": 3.5, "QB": 5.3, "WR": 7.0, "TE": 4.0}, 60),
    "rec_td": ({"WR": 0.045, "TE": 0.055, "RB": 0.03, "FB": 0.04, "QB": 0.0}, 80),
    "rush_td": ({"RB": 0.032, "FB": 0.05, "QB": 0.04, "WR": 0.03, "TE": 0.05}, 100),
    "cmp": ({"QB": 0.645}, 150),
    "ypcmp": ({"QB": 10.9}, 120),
    "pass_td": ({"QB": 0.045}, 300),
}


@dataclass
class Params:
    half_life: float = 5.0          # games, for usage shares and team volume
    team_k: float = 4.0             # team volume shrink (games)
    share_kappa: float = 18.0       # Beta concentration for game-to-game share noise
    vol_sd: float = 8.5             # residual sd of team volume after script adjustment
    ypr_cv: float = 1.05            # per-catch yards coefficient of variation
    ypc_sd: float = 5.8             # per-carry yards sd
    ypcmp_cv: float = 0.85
    lookback: int = 16              # max prior games used
    n_sims: int = 6000
    seed: int = 7


def _ewma_weights(n: int, half_life: float) -> np.ndarray:
    w = 0.5 ** (np.arange(n)[::-1] / half_life)
    return w / w.sum()


def _shrink(num: float, den: float, prior: float, k: float) -> float:
    return (num + prior * k) / (den + k) if den + k > 0 else prior


@dataclass
class TeamState:
    dropbacks: float
    carries: float


@dataclass
class PlayerState:
    player_id: str
    name: str
    position: str
    team: str
    n: int
    tgt_share: float
    car_share: float
    att_share: float
    rates: dict = field(default_factory=dict)


class NFLModel:
    def __init__(self, history: pd.DataFrame, params: Params | None = None):
        self.p = params or Params()
        self.h = history.sort_values("date")
        self.rng = np.random.default_rng(self.p.seed)

    # ------------------------------------------------------------ team volume
    def team_state(self, team: str) -> TeamState:
        tg = self.h[self.h.team == team].drop_duplicates("game_id").tail(self.p.lookback)
        out = {}
        for key, col in (("dropbacks", "team_dropbacks"), ("carries", "team_carries")):
            b_s, b_t = SCRIPT[key]
            if len(tg):
                adj = (tg[col] - b_s * tg.spread.fillna(0) - b_t * (tg.total.fillna(44) - 44)).to_numpy(float)
                w = _ewma_weights(len(adj), self.p.half_life)
                n_eff = len(adj)
                val = (np.dot(w, adj) * n_eff + LEAGUE[key] * self.p.team_k) / (n_eff + self.p.team_k)
            else:
                val = LEAGUE[key]
            out[key] = val
        return TeamState(**out)

    # ------------------------------------------------------------ player usage and efficiency
    def player_state(self, player_id: str, team: str) -> PlayerState | None:
        g = self.h[self.h.player_id == player_id].tail(self.p.lookback)
        if g.empty:
            return None
        pos = g.position.iloc[-1]
        w = _ewma_weights(len(g), self.p.half_life)
        db = g.team_dropbacks.replace(0, np.nan).to_numpy(float)
        tc = g.team_carries.replace(0, np.nan).to_numpy(float)
        tgt_share = float(np.nansum(w * np.nan_to_num(g.targets.to_numpy(float) / db)))
        car_share = float(np.nansum(w * np.nan_to_num(g.carries.to_numpy(float) / tc)))
        att_share = float(np.nansum(w * np.nan_to_num(g.attempts.to_numpy(float) / db)))
        s = g.sum(numeric_only=True)
        r = {}
        pr = lambda key: (PRIORS[key][0].get(pos, list(PRIORS[key][0].values())[0]), PRIORS[key][1])
        r["catch"] = _shrink(s.receptions, s.targets, *pr("catch"))
        r["ypr"] = _shrink(s.receiving_yards, s.receptions, *pr("ypr"))
        r["ypc"] = _shrink(s.rushing_yards, s.carries, *pr("ypc"))
        r["rec_td"] = _shrink(s.receiving_tds, s.targets, *pr("rec_td"))
        r["rush_td"] = _shrink(s.rushing_tds, s.carries, *pr("rush_td"))
        r["cmp"] = _shrink(s.completions, s.attempts, *pr("cmp"))
        r["ypcmp"] = _shrink(s.passing_yards, s.completions, *pr("ypcmp"))
        r["pass_td"] = _shrink(s.passing_tds, s.attempts, *pr("pass_td"))
        return PlayerState(player_id, g.player_display_name.iloc[-1], pos, team, len(g), tgt_share, car_share,
                           att_share, r)

    def team_players(self, team: str, recent_games: int = 4) -> list[PlayerState]:
        tg = self.h[self.h.team == team]
        ids = tg[tg.game_id.isin(tg.game_id.drop_duplicates().tail(recent_games))].player_id.unique()
        out = [self.player_state(pid, team) for pid in ids]
        return [x for x in out if x is not None]

    # ------------------------------------------------------------ projection
    def project_team(self, team: str, available_ids: set | None, spread: float | None, total: float | None,
                     extra_players: list[str] | None = None) -> dict:
        """Simulate every available regular. Returns {player_id: {"state": PlayerState, "sims": {stat: array}}}."""
        ts = self.team_state(team)
        spread = 0.0 if spread is None or pd.isna(spread) else float(spread)
        total = 44.0 if total is None or pd.isna(total) else float(total)
        db_mu = ts.dropbacks + SCRIPT["dropbacks"][0] * spread + SCRIPT["dropbacks"][1] * (total - 44)
        ca_mu = ts.carries + SCRIPT["carries"][0] * spread + SCRIPT["carries"][1] * (total - 44)
        implied = max(total / 2 - spread / 2, 6.0)
        td_factor = implied / 22.5
        players = self.team_players(team)
        known = {p.player_id for p in players}
        for pid in extra_players or []:
            if pid not in known:
                st = self.player_state(pid, team)
                if st:
                    players.append(st)
        avail = [p for p in players if available_ids is None or p.player_id in available_ids]
        if not avail:
            return {}
        # Usage shares come from each player's own games, so they can sum past the team total (a backup's share from
        # games he started). Redistribute the shares of regulars who are out, then cap each team's sum at the share
        # one game can actually hold.
        out_players = [p for p in players if p not in avail]
        caps = {"tgt_share": 0.95, "car_share": 1.0, "att_share": 0.97}
        for attr, cap in caps.items():
            missing = sum(getattr(p, attr) for p in out_players)
            have = sum(getattr(p, attr) for p in avail)
            if have <= 0:
                continue
            target = min(have + missing, cap) if missing > 0 else min(have, cap)
            factor = min(target / have, 1.6)
            for p in avail:
                setattr(p, attr, getattr(p, attr) * factor)
        # one passer: the available QB with the largest attempt share throws; others keep rushing only
        qbs = sorted([p for p in avail if p.position == "QB"], key=lambda p: -p.att_share)
        for i, q in enumerate(qbs):
            if i == 0:
                q.att_share = max(q.att_share, 0.9)
            else:
                q.att_share, q.car_share = 0.0, q.car_share * 0.2
        n = self.p.n_sims
        rng = self.rng
        dropbacks = np.clip(rng.normal(db_mu, self.p.vol_sd, n), 12, 70).round().astype(int)
        carries_t = np.clip(rng.normal(ca_mu, self.p.vol_sd * 0.85, n), 8, 55).round().astype(int)
        out = {}
        for p in avail:
            k = self.p.share_kappa
            def beta(mean):
                mean = float(np.clip(mean, 1e-4, 0.97))
                return rng.beta(mean * k, (1 - mean) * k, n)
            sims = {}
            tg = rng.binomial(dropbacks, beta(p.tgt_share)) if p.tgt_share > 0.002 else np.zeros(n, int)
            rec = rng.binomial(tg, p.rates["catch"])
            cv = self.p.ypr_cv
            shape = np.maximum(rec, 1e-9) / cv ** 2
            ryds = np.where(rec > 0, rng.gamma(shape, p.rates["ypr"] * cv ** 2), 0.0)
            car = rng.binomial(carries_t, beta(p.car_share)) if p.car_share > 0.002 else np.zeros(n, int)
            rush = car * p.rates["ypc"] + rng.normal(0, 1, n) * np.sqrt(np.maximum(car, 0)) * self.p.ypc_sd
            sims.update(targets=tg, rec=rec, rec_yds=ryds, rush_att=car, rush_yds=rush)
            lam_td = (tg * p.rates["rec_td"] + car * p.rates["rush_td"]) * td_factor
            sims["td"] = rng.poisson(lam_td)
            sims["rush_rec_yds"] = ryds + rush
            if p.position == "QB" and p.att_share > 0.3:
                att = rng.binomial(dropbacks, np.clip(p.att_share, 0, 0.97))
                cmp_ = rng.binomial(att, p.rates["cmp"])
                cvp = self.p.ypcmp_cv
                pyds = np.where(cmp_ > 0, rng.gamma(np.maximum(cmp_, 1e-9) / cvp ** 2, p.rates["ypcmp"] * cvp ** 2), 0.0)
                sims.update(pass_att=att, pass_cmp=cmp_, pass_yds=pyds, pass_td=rng.poisson(att * p.rates["pass_td"] * td_factor))
            out[p.player_id] = {"state": p, "sims": sims,
                                "means": {s: float(np.mean(v)) for s, v in sims.items()}}
        return out


def prob_at_least(sims: dict, stat: str, k: float, calibrated: bool = False) -> float | None:
    if stat not in sims:
        return None
    p = float(np.mean(sims[stat] >= k))
    return apply_calibration(p, stat) if calibrated else p


_CALIB = None


def apply_calibration(p: float, stat: str, calib: dict | None = None) -> float:
    """Logit-slope calibration fitted out of sample (desk/nfl/calibration.json); slope < 1 tempers overconfidence."""
    global _CALIB
    if calib is None:
        if _CALIB is None:
            import json
            import os
            path = os.path.join(os.path.dirname(__file__), "calibration.json")
            _CALIB = json.load(open(path)) if os.path.exists(path) else {}
        calib = _CALIB
    a = calib.get("anytime_td" if stat == "td" else stat, 1.0)
    p = min(max(p, 1e-4), 1 - 1e-4)
    z = np.log(p / (1 - p)) * a
    return float(1 / (1 + np.exp(-z)))
