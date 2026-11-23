"""Walk-forward backtest of the tennis Elo model.

Ratings are built from 2010 onward; every match from 2023 on is predicted before its result is
used to update the ratings. Reports Brier score, log loss, accuracy and calibration against a
ranking-based baseline. (A market comparison against Pinnacle closing odds runs on GitHub Actions:
scripts/backtest_tennis_market.py.)
"""
import json, math, os, sys
import numpy as np, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from desk.tennis.elo import Elo, EloParams, is_completed, norm_surface
from desk import pricing

def run(df, params, start=20230101):
    out = []
    df = df.sort_values(["tourney_date", "match_num"], kind="stable")
    for tour, g in df.groupby("tour"):
        elo = Elo(params)
        for r in g.itertuples():
            if not is_completed(r.score):
                continue
            if r.tourney_date >= start and elo.n[r.winner_name] >= 10 and elo.n[r.loser_name] >= 10:
                # predict from the alphabetically-first player's side so the label isn't always 1
                a, b, y = (r.winner_name, r.loser_name, 1) if r.winner_name < r.loser_name else (r.loser_name, r.winner_name, 0)
                p = elo.predict(a, b, r.surface, r.best_of)
                ra = r.winner_rank if y == 1 else r.loser_rank
                rb = r.loser_rank if y == 1 else r.winner_rank
                pb = 1 / (1 + (ra / rb) ** 0.9) if ra == ra and rb == rb and ra > 0 and rb > 0 else 0.5
                out.append({"tour": tour, "date": r.tourney_date, "level": r.tourney_level,
                            "surface": norm_surface(r.surface), "p_elo": p, "p_rank": pb, "y": y})
            elo.update(r.winner_name, r.loser_name, r.surface)
    return pd.DataFrame(out)

def summarize(res):
    def sc(d):
        return {"n": len(d), "brier_elo": pricing.brier(d.p_elo, d.y), "brier_rank": pricing.brier(d.p_rank, d.y),
                "logloss_elo": pricing.log_loss(d.p_elo, d.y), "logloss_rank": pricing.log_loss(d.p_rank, d.y),
                "acc_elo": float(((d.p_elo > .5) == (d.y == 1)).mean()), "acc_rank": float(((d.p_rank > .5) == (d.y == 1)).mean())}
    return sc(res)

if __name__ == "__main__":
    df = pd.read_csv("data/tennis/matches.csv.gz")
    best = None
    for sw in (0.3, 0.5):
        for k0 in (150, 175, 200):
            for shrink in (0.85, 0.9, 1.0):
                prm = EloParams(k0=k0, surface_weight=sw, shrink=shrink)
                res = run(df[df.tourney_date < 20250101], prm, start=20230101)   # tune on 2023-2024
                ll = pricing.log_loss(res.p_elo, res.y)
                print(f"surface_weight={sw} k0={k0} shrink={shrink} tune logloss={ll:.4f}", flush=True)
                if best is None or ll < best[0]:
                    best = (ll, sw, k0, shrink)
    _, sw, k0, shrink = best
    prm = EloParams(k0=k0, surface_weight=sw, shrink=shrink)
    res = run(df, prm, start=20250101)                                      # test on 2025-2026
    out = {"tuned": {"k0": k0, "surface_weight": sw, "shrink": shrink}, "test": "2025-01-01 onward", "overall": summarize(res),
           "by_tour": {t: summarize(g) for t, g in res.groupby("tour")},
           "by_surface": {s: summarize(g) for s, g in res.groupby("surface")},
           "calibration_elo": pricing.calibration_table(res.p_elo.tolist(), res.y.tolist())}
    os.makedirs("reports", exist_ok=True)
    json.dump(out, open("reports/backtest_tennis.json", "w"), indent=1, default=float)
    print(json.dumps(out, indent=1, default=float))
