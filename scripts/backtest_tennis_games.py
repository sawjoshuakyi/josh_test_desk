"""Backtest of the tennis score model (total games, games handicap, straight-sets) vs Elo-bucket baselines.

Walk-forward: Elo is updated match by match; serve/return tables are rebuilt monthly from earlier matches only.
Player A = the Elo favourite. Markets per match: total games over the tour/format median line; favourite -3.5 games;
favourite wins in straight sets. Baselines: historical frequency of each outcome among matches with a similar Elo
favourite probability (5-point buckets) and the same tour/format — so the model only wins if serve/return shape adds
information beyond who is favoured. Test window: 2025-01-01 to 2026-05-25. Writes reports/backtest_tennis_games.json.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import numpy as np
import pandas as pd

from desk import pricing
from desk.tennis.elo import Elo, is_completed
from desk.tennis.score import ServeTable, p_cover, p_total_over, parse_games

TEST_START, TEST_END = 20250101, 20260525


def main():
    serve = pd.read_csv(os.path.join(ROOT, "data", "tennis", "serve_stats.csv.gz"), low_memory=False)
    serve = serve.sort_values("tourney_date", kind="stable")
    arch = pd.read_csv(os.path.join(ROOT, "data", "tennis", "matches.csv.gz"))
    arch = arch.sort_values(["tourney_date", "match_num"], kind="stable")
    elos = {t: Elo() for t in ("atp", "wta")}
    rows, hist = [], []
    tables, month = {}, None
    for r in arch.itertuples():
        if not is_completed(r.score) or r.tour not in elos:
            continue
        elo = elos[r.tour]
        bo = int(r.best_of) if r.best_of == r.best_of else 3
        surf = r.surface if isinstance(r.surface, str) else "Hard"
        p_w = elo.predict(r.winner_name, r.loser_name, surf, bo)
        games = parse_games(r.score)
        if games:
            fav_is_w = p_w >= 0.5
            p_fav = max(p_w, 1 - p_w)
            gw, gl = games
            total = gw + gl
            margin_fav = (gw - gl) if fav_is_w else (gl - gw)
            sets_w = len(str(r.score).split())
            straight = int(fav_is_w and sets_w == (2 if bo == 3 else 3))
            rec = {"date": r.tourney_date, "tour": r.tour, "bo": bo, "p_fav": p_fav, "total": total,
                   "margin": margin_fav, "straight": straight}
            if TEST_START <= r.tourney_date <= TEST_END:
                m = r.tourney_date // 100
                if m != month:
                    month = m
                    tables = ServeTable(asof=int(r.tourney_date), df=serve)
                fav, dog = (r.winner_name, r.loser_name) if fav_is_w else (r.loser_name, r.winner_name)
                rec.update(fav=fav, dog=dog, surf=surf, table=tables)
                rows.append(rec)
            hist.append(rec)
        elo.update(r.winner_name, r.loser_name, surf)
    h = pd.DataFrame([{k: v for k, v in x.items() if k != "table"} for x in hist if x["date"] < TEST_START])
    h["bucket"] = (h.p_fav * 20).astype(int)
    lines = h.groupby(["tour", "bo"]).total.median().apply(lambda x: np.floor(x) + 0.5).to_dict()
    def evaluate(subset, sigma):
        res = {"total": ([], [], []), "cover": ([], [], []), "straight": ([], [], [])}
        for x in subset:
            key = (x["tour"], x["bo"])
            if key not in lines:
                continue
            b = int(x["p_fav"] * 20)
            hb = base.get((x["tour"], x["bo"], b))
            if hb is None:
                continue
            t = x["table"]
            t.p.sigma = sigma
            try:
                md = t.match(x["tour"], x["fav"], x["dog"], x["surf"], x["p_fav"], x["bo"])
            except Exception:
                continue
            L = lines[key]
            res["total"][0].append(p_total_over(md["total_games"], L)); res["total"][1].append(hb[0]); res["total"][2].append(int(x["total"] > L))
            res["cover"][0].append(p_cover(md["margin"], -3.5)); res["cover"][1].append(hb[1]); res["cover"][2].append(int(x["margin"] > 3.5))
            res["straight"][0].append(md["set_scores"].get((2, 0) if x["bo"] == 3 else (3, 0), 0.0)); res["straight"][1].append(hb[2]); res["straight"][2].append(x["straight"])
        out = {}
        for k, (pm, pb, y) in res.items():
            pm = list(np.clip(pm, 0.01, 0.99))
            out[k] = {"n": len(y), "ll_model": pricing.log_loss(pm, y), "ll_base": pricing.log_loss(pb, y),
                      "calibration": pricing.calibration_table(pm, y)}
        return out

    h["bucket"] = (h.p_fav * 20).astype(int)
    lines = h.groupby(["tour", "bo"]).total.median().apply(lambda x: np.floor(x) + 0.5).to_dict()
    base = {}
    for (tour, bo, b), g in h.groupby(["tour", "bo", "bucket"]):
        if len(g) >= 30:
            L = lines[(tour, bo)]
            base[(tour, bo, b)] = (float((g.total > L).mean()), float((g.margin > 3.5).mean()), float(g.straight.mean()))
    tune = [x for x in rows if x["date"] < 20250701][::3]
    test = [x for x in rows if x["date"] >= 20250701]
    best, best_ll = None, 9
    for sigma in (0.0, 0.06, 0.10, 0.14, 0.18):
        o = evaluate(tune, sigma)
        ll = sum(o[k]["ll_model"] for k in o)
        print("sigma", sigma, round(ll, 4), {k: round(o[k]["ll_model"] - o[k]["ll_base"], 4) for k in o})
        if ll < best_ll:
            best, best_ll = sigma, ll
    out = {"sigma": best, "test": "2025-07-01 to 2026-05-25", "lines": {f"{k[0]}-bo{k[1]}": v for k, v in lines.items()},
           **evaluate(test, best)}
    json.dump(out, open(os.path.join(ROOT, "reports", "backtest_tennis_games.json"), "w"), indent=1, default=float)
    for k in ("total", "cover", "straight"):
        print(k, out[k]["n"], round(out[k]["ll_model"], 4), round(out[k]["ll_base"], 4))


if __name__ == "__main__":
    main()
