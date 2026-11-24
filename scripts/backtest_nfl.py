"""Walk-forward backtest of the NFL prop model vs a naive baseline.

For every player-game in the test window the model sees only games before that date (plus who actually played,
which matches knowing the inactives ~90 minutes before kickoff). The "line" is the player's prior-8-game median
rounded to a .5 (a stand-in for the book's line). Baseline = the player's own prior hit rate over that line.
Tune window: 2025 weeks 4-18. Test window: 2026 weeks 3 onward (out of sample).
Writes reports/backtest_nfl.json.
"""
from __future__ import annotations

import itertools
import json
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from desk import pricing
from desk.nfl import data
from desk.nfl.model import NFLModel, Params, apply_calibration, prob_at_least

STATS = {"rec": "receptions", "rec_yds": "receiving_yards", "rush_yds": "rushing_yards", "rush_att": "carries",
         "pass_yds": "passing_yards", "pass_att": "attempts", "pass_cmp": "completions", "pass_td": "passing_tds"}
MIN_MEDIAN = {"rec": 1.5, "rec_yds": 15, "rush_yds": 15, "rush_att": 5, "pass_yds": 120, "pass_att": 20, "pass_cmp": 12,
              "pass_td": 0.5}


SNAPS: dict = {}


def run(pg: pd.DataFrame, window: pd.DataFrame, params: Params) -> pd.DataFrame:
    if not SNAPS:
        SNAPS.update(data.snap_keys())
    rows = []
    for date, day_games in window.groupby("date"):
        model = NFLModel(pg[pg.date < date], params)
        for (gid, team), tg in day_games.groupby(["game_id", "team"]):
            played = SNAPS.get((gid, team))
            if played is None:  # no snap data: assume every regular was available
                avail = None
            else:  # regulars who took an offensive snap, plus anyone with stats (= knowing the inactives list)
                avail = {p.player_id for p in model.team_players(team) if data.name_key(p.name) in played} | set(tg.player_id)
            proj = model.project_team(team, avail, tg.spread.iloc[0], tg.total.iloc[0], extra_players=list(tg.player_id))
            for r in tg.itertuples():
                pj = proj.get(r.player_id)
                if pj is None:
                    continue
                prior = pg[(pg.player_id == r.player_id) & (pg.date < date)].tail(16)
                if len(prior) < 4:
                    continue
                for stat, col in STATS.items():
                    if stat not in pj["sims"]:
                        continue
                    hist = prior[col].to_numpy(float)
                    med = float(np.median(hist[-8:]))
                    if med < MIN_MEDIAN[stat]:
                        continue
                    line = math.floor(med) + 0.5
                    k = math.floor(line) + 1
                    pm = prob_at_least(pj["sims"], stat, k)
                    base = (np.sum(hist > line) + 1) / (len(hist) + 2)
                    rows.append({"date": date, "player": r.player_display_name, "pos": r.position, "stat": stat,
                                 "line": line, "p_model": pm, "p_base": base, "y": int(getattr(r, col) > line)})
                # anytime TD
                hist_td = (prior.rushing_tds + prior.receiving_tds).to_numpy(float)
                if r.position != "QB" and (prior.targets.sum() + prior.carries.sum()) / len(prior) >= 3:
                    rows.append({"date": date, "player": r.player_display_name, "pos": r.position, "stat": "anytime_td",
                                 "line": 0.5, "p_model": prob_at_least(pj["sims"], "td", 1),
                                 "p_base": (np.sum(hist_td >= 1) + 1) / (len(hist_td) + 2),
                                 "y": int(r.rushing_tds + r.receiving_tds >= 1)})
    return pd.DataFrame(rows)


def fit_calibration(df: pd.DataFrame) -> dict:
    out = {}
    for stat, g in df.groupby("stat"):
        best, best_ll = 1.0, 9
        for a in np.arange(0.5, 1.31, 0.05):
            ll = pricing.log_loss([apply_calibration(p, stat, {stat: a}) for p in g.p_model], g.y)
            if ll < best_ll:
                best, best_ll = round(float(a), 2), ll
        out[stat] = best
    return out


def score(df: pd.DataFrame) -> dict:
    out = {"n": int(len(df)),
           "logloss_model": pricing.log_loss(df.p_model.clip(0.01, 0.99), df.y),
           "logloss_base": pricing.log_loss(df.p_base, df.y),
           "brier_model": pricing.brier(df.p_model, df.y), "brier_base": pricing.brier(df.p_base, df.y)}
    out["by_stat"] = {s: {"n": int(len(g)), "ll_model": round(pricing.log_loss(g.p_model.clip(0.01, 0.99), g.y), 4),
                          "ll_base": round(pricing.log_loss(g.p_base, g.y), 4)} for s, g in df.groupby("stat")}
    out["calibration"] = pricing.calibration_table(df.p_model.tolist(), df.y.tolist())
    return out


def main():
    pg = data.player_games()
    pg = pg[pg.date.notna()]
    tune = pg[(pg.season == 2025) & (pg.week >= 4)]
    test = pg[(pg.season == 2026) & (pg.week >= 3)]
    grid = {"half_life": [3.0, 5.0], "share_kappa": [10.0, 18.0], "vol_sd": [6.5, 8.5]}
    best, best_ll = None, 9
    tune_sample = tune[tune.week.isin([5, 8, 11, 14, 17])]  # every third week keeps tuning fast
    for combo in itertools.product(*grid.values()):
        prm = Params(**dict(zip(grid, combo)), n_sims=3000)
        df = run(pg, tune_sample, prm)
        ll = pricing.log_loss(df.p_model.clip(0.01, 0.99), df.y)
        print(dict(zip(grid, combo)), round(ll, 4), len(df))
        if ll < best_ll:
            best, best_ll = prm, ll
    best.n_sims = 6000
    # per-stat calibration (logit slope), fitted on the full tune window only
    tune_res = run(pg, tune, best)
    calib = fit_calibration(tune_res)
    json.dump(calib, open(os.path.join(ROOT, "desk", "nfl", "calibration.json"), "w"), indent=1)
    res = run(pg, test, best)
    raw = score(res)
    res["p_model"] = [apply_calibration(p, s, calib) for p, s in zip(res.p_model, res.stat)]
    report = {"tuned": {k: getattr(best, k) for k in grid}, "tune_logloss": best_ll, "calibration_slopes": calib,
              "test": "2026 weeks 3+ (out of sample)", "overall": score(res),
              "overall_uncalibrated": {k: raw[k] for k in ("n", "logloss_model", "logloss_base")}}
    json.dump(report, open(os.path.join(ROOT, "reports", "backtest_nfl.json"), "w"), indent=1, default=float)
    o = report["overall"]
    print(json.dumps({k: o[k] for k in ("n", "logloss_model", "logloss_base", "brier_model", "brier_base")}, default=float))
    for s, v in o["by_stat"].items():
        print(s, v)


if __name__ == "__main__":
    main()
