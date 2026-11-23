"""Walk-forward backtest of the NBA prop model on this season's box scores.

For every player-game, the model is built only from games before that date. It scores
P(stat >= k) at two thresholds per stat: a "main" line near the player's season average and a
"safe alt" near 70% of it, then reports Brier score, log loss and calibration against a naive
baseline (season average, no adjustments). Dispersion settings are tuned on the first half of
the window and evaluated on the second half (out of sample).
"""
import itertools, json, math, sys, os
import numpy as np, pandas as pd
from scipy import stats as st
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from desk.nba.model import Projector, Params, COMBOS
from desk import pricing

EVAL = ["pts", "reb", "ast", "threes", "pra"]

def baseline_prob(avg, stat, k):
    if avg <= 0:
        return 1e-4 if k > 0 else 1 - 1e-4
    if stat in ("pts", "pra"):
        return float(min(max(1 - st.norm.cdf(k - 0.5, avg, math.sqrt(2.3 * avg)), 1e-4), 1 - 1e-4))
    return float(min(max(st.poisson.sf(k - 1, avg), 1e-4), 1 - 1e-4))

def collect(df, start, end, params):
    rows = []
    dates = sorted(d for d in df.date.unique() if start <= d <= end)
    for D in dates:
        proj = Projector(df[df.date < D], params)
        today = df[df.date == D]
        for (gid, team), g in today.groupby(["game_id", "team"]):
            available = set(g[g.dnp == 0].player_id)
            for r in g[(g.dnp == 0) & (g.minutes > 0)].itertuples():
                pr = proj.project(r.player_id, team, available, bool(r.starter), r.spread, r.total)
                if pr is None:
                    continue
                hist = proj.by_player[r.player_id]
                for stat in EVAL:
                    parts = COMBOS.get(stat, [stat])
                    actual = sum(getattr(r, s) for s in parts)
                    avg = float(sum(hist[s].mean() for s in parts))
                    if avg < (1.0 if stat == "threes" else 2.0):
                        continue
                    for kind, k in (("main", math.floor(avg) + 1 if avg % 1 >= .5 else math.floor(avg)), ("alt70", max(1, round(0.7 * avg)))):
                        k = max(1, int(k))
                        rows.append({"date": D, "stat": stat, "kind": kind, "k": k, "y": int(actual >= k),
                                     "p_model": proj.prob_at_least(pr, stat, k), "p_base": baseline_prob(avg, stat, k)})
    return pd.DataFrame(rows)

def score(df_):
    return {"n": len(df_), "brier_model": pricing.brier(df_.p_model, df_.y), "brier_base": pricing.brier(df_.p_base, df_.y),
            "logloss_model": pricing.log_loss(df_.p_model, df_.y), "logloss_base": pricing.log_loss(df_.p_base, df_.y)}

if __name__ == "__main__":
    df = pd.read_csv("data/nba_boxscores.csv", dtype={"game_id": str, "player_id": str})
    train = ("2026-11-03", "2026-11-11"); test = ("2026-11-12", "2026-11-22")
    grid = {"pts_var_a": [1.8, 2.3, 2.8], "pts_var_c": [0.08, 0.14], "nb_mult": [0.6, 1.0, 1.6], "min_sd_frac": [0.15, 0.22]}
    best = None
    base = Params()
    for a, c, mult, sdf in itertools.product(*grid.values()):
        prm = Params(pts_var_a=a, pts_var_c=c, min_sd_frac=sdf, nb_r={k: v * mult for k, v in base.nb_r.items()})
        res = collect(df, *train, prm)
        ll = pricing.log_loss(res.p_model, res.y)
        if best is None or ll < best[0]:
            best = (ll, a, c, mult, sdf)
        print(f"a={a} c={c} nb_mult={mult} sd={sdf}  train logloss={ll:.4f}", flush=True)
    _, a, c, mult, sdf = best
    tuned = Params(pts_var_a=a, pts_var_c=c, min_sd_frac=sdf, nb_r={k: v * mult for k, v in base.nb_r.items()})
    test_res = collect(df, *test, tuned)
    out = {"tuned": {"pts_var_a": a, "pts_var_c": c, "nb_r": tuned.nb_r, "min_sd_frac": sdf},
           "test_window": test, "overall": score(test_res),
           "by_stat": {s: score(g) for s, g in test_res.groupby("stat")},
           "by_kind": {k: score(g) for k, g in test_res.groupby("kind")},
           "calibration_model": pricing.calibration_table(test_res.p_model.tolist(), test_res.y.tolist()),
           "calibration_base": pricing.calibration_table(test_res.p_base.tolist(), test_res.y.tolist())}
    os.makedirs("reports", exist_ok=True)
    json.dump(out, open("reports/backtest_nba.json", "w"), indent=1, default=float)
    test_res.to_csv("reports/backtest_nba_rows.csv", index=False)
    print(json.dumps(out, indent=1, default=float))
