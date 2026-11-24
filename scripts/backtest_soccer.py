"""Walk-forward backtest of the soccer models vs naive baselines (refit weekly; only past data is used).

Markets: match result (3-way), total goals over 2.5, total corners over 9.5 / 10.5, player shots on target 1+ / 2+
(starters, i.e. as if the XI were confirmed). Baselines: league frequencies (result, goals, corners) and the player's
own past rate (SOT). Tune window 2025-08..2026-05 (every third week), test window 2026-08 onward.
Writes reports/backtest_soccer.json.
"""
from __future__ import annotations

import itertools
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from desk import pricing
from desk.soccer import data
from desk.soccer.model import SoccerModel, SoccerParams


def ll3(p, y):
    return float(np.mean([-np.log(max(pi[yi], 1e-6)) for pi, yi in zip(p, y)]))


def run(m, pl, start, end, prm, week_step=1, sot=True):
    rows, sot_rows = [], []
    weeks = pd.date_range(start, end, freq="7D")[::week_step]
    for wk in weeks:
        asof = wk.strftime("%Y-%m-%d")
        nxt = (wk + pd.Timedelta(days=7)).strftime("%Y-%m-%d")
        games = m[(m.date >= asof) & (m.date < nxt) & (m.home == 1)]
        if games.empty:
            continue
        model = SoccerModel(m, pl, asof, prm)
        hist = m[m.date < asof]
        lg = hist[hist.home == 1].groupby("league")
        base_res = lg.apply(lambda g: [np.mean(g.goals > g.goals_against), np.mean(g.goals == g.goals_against),
                                       np.mean(g.goals < g.goals_against)], include_groups=False).to_dict()
        tot = hist.groupby(["league", "event_id"]).agg(g=("goals", "sum"), c=("wonCorners", "sum")).reset_index()
        base_o25 = tot.groupby("league").g.apply(lambda x: (x > 2.5).mean()).to_dict()
        base_c = {k: tot[tot.league == k].c for k in tot.league.unique()}
        for g in games.itertuples():
            if g.team_id not in model.goals["att"] or g.opp_id not in model.goals["att"]:
                continue
            r = model.match(g.team_id, g.opp_id)
            y = 0 if g.goals > g.goals_against else (1 if g.goals == g.goals_against else 2)
            cpmf = model.corners_total_pmf(r["corners_home"], r["corners_away"])
            opp_row = m[(m.event_id == g.event_id) & (m.team_id == g.opp_id)]
            corners = g.wonCorners + (opp_row.wonCorners.iloc[0] if len(opp_row) else np.nan)
            bc = base_c.get(g.league, pd.Series([10]))
            rows.append({"date": g.date, "league": g.league, "p_res": [r["p_home"], r["p_draw"], r["p_away"]],
                         "b_res": base_res.get(g.league, [0.45, 0.25, 0.30]), "y_res": y,
                         "p_o25": model.p_total_over(r["goals_pmf"], 2.5), "b_o25": base_o25.get(g.league, 0.5),
                         "y_o25": int(g.goals + g.goals_against > 2.5),
                         "p_c95": model.p_total_over(cpmf, 9.5), "b_c95": float((bc > 9.5).mean()),
                         "p_c105": model.p_total_over(cpmf, 10.5), "b_c105": float((bc > 10.5).mean()),
                         "y_c95": int(corners > 9.5) if corners == corners else None,
                         "y_c105": int(corners > 10.5) if corners == corners else None})
        if not sot:
            continue
        # player shots on target (starters)
        week_pl = pl[(pl.date >= asof) & (pl.date < nxt) & (pl.starter == 1)]
        prior = pl[pl.date < asof]
        cnt = prior.groupby("player_id").agg(n=("sot", "size"), s1=("sot", lambda x: (x >= 1).sum()),
                                             s2=("sot", lambda x: (x >= 2).sum()))
        side = m[(m.date >= asof) & (m.date < nxt)].set_index(["event_id", "team_id"])
        for r in week_pl.itertuples():
            if r.player_id not in cnt.index or cnt.loc[r.player_id, "n"] < 5:
                continue
            try:
                info = side.loc[(r.event_id, r.team_id)]
            except KeyError:
                continue
            pr = model.player_sot(r.player_id, r.team_id, info.opp_id, int(info.home), starter=True)
            if pr is None or pr["group"] == "GK":
                continue
            c = cnt.loc[r.player_id]
            sot_rows.append({"p1": model.p_sot_at_least(pr["mean"], 1), "p2": model.p_sot_at_least(pr["mean"], 2),
                             "b1": (c.s1 + 1) / (c.n + 2), "b2": (c.s2 + 1) / (c.n + 2),
                             "y1": int(r.sot >= 1), "y2": int(r.sot >= 2), "group": pr["group"]})
    return pd.DataFrame(rows), pd.DataFrame(sot_rows)


def score(df, sot):
    out = {"matches": int(len(df)),
           "result_ll": {"model": ll3(df.p_res, df.y_res), "base": ll3(df.b_res, df.y_res)},
           "over25_ll": {"model": pricing.log_loss(df.p_o25, df.y_o25), "base": pricing.log_loss(df.b_o25, df.y_o25)}}
    c = df.dropna(subset=["y_c95"])
    out["corners95_ll"] = {"model": pricing.log_loss(c.p_c95, c.y_c95), "base": pricing.log_loss(c.b_c95, c.y_c95)}
    out["corners105_ll"] = {"model": pricing.log_loss(c.p_c105, c.y_c105), "base": pricing.log_loss(c.b_c105, c.y_c105)}
    out["sot_players"] = int(len(sot))
    out["sot1_ll"] = {"model": pricing.log_loss(sot.p1, sot.y1), "base": pricing.log_loss(sot.b1, sot.y1)}
    out["sot2_ll"] = {"model": pricing.log_loss(sot.p2, sot.y2), "base": pricing.log_loss(sot.b2, sot.y2)}
    out["calibration_over25"] = pricing.calibration_table(df.p_o25.tolist(), df.y_o25.tolist())
    out["calibration_sot1"] = pricing.calibration_table(sot.p1.tolist(), sot.y1.tolist())
    return out


def total_ll(s):
    return sum(s[k]["model"] for k in ("result_ll", "over25_ll", "corners95_ll", "sot1_ll"))


def main():
    m, pl = data.matches(), data.players()
    grid = {"half_life_days": [180.0, 365.0], "xg_weight": [0.3, 0.6], "ridge": [2.0, 6.0]}
    best, best_s = None, 9e9
    for combo in itertools.product(*grid.values()):
        prm = SoccerParams(**dict(zip(grid, combo)))
        df, _ = run(m, pl, "2025-08-15", "2026-05-20", prm, week_step=3, sot=False)
        s = sum([ll3(df.p_res, df.y_res), pricing.log_loss(df.p_o25, df.y_o25),
                 pricing.log_loss(df.dropna(subset=["y_c95"]).p_c95, df.dropna(subset=["y_c95"]).y_c95)])
        print(dict(zip(grid, combo)), round(s, 4))
        if s < best_s:
            best, best_s = prm, s
    df, sot = run(m, pl, "2026-08-01", "2026-11-22", best)
    rep = {"tuned": {k: getattr(best, k) for k in grid}, "test": "2026-08-01 to 2026-11-22 (out of sample)",
           **score(df, sot)}
    json.dump(rep, open(os.path.join(ROOT, "reports", "backtest_soccer.json"), "w"), indent=1, default=float)
    for k, v in rep.items():
        if k.endswith("_ll") or k in ("matches", "sot_players", "tuned"):
            print(k, v)


if __name__ == "__main__":
    main()
