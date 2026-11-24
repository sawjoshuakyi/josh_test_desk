"""Out-of-sample comparison (2026-08-01..2026-11-22, weekly refits): ESPN vs API-Football data, and the
league-offset and real-xG options. Log loss vs league-frequency baselines. Writes reports/soccer_source_compare.json."""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
import numpy as np
from desk import pricing
from desk.soccer import data, apifootball as af
from desk.soccer.model import SoccerParams
from backtest_soccer import run, ll3

ESPN_TO_CODE = {"eng.1": "epl", "esp.1": "laliga", "ita.1": "seriea", "ger.1": "bundesliga", "fra.1": "ligue1",
                "uefa.champions": "ucl", "usa.1": "mls"}
START, END = "2026-08-01", "2026-11-22"


def summarize(df, sot):
    c = df.dropna(subset=["y_c95"])
    out = {"matches": len(df),
           "result": [ll3(df.p_res, df.y_res), ll3(df.b_res, df.y_res)],
           "over25": [pricing.log_loss(df.p_o25, df.y_o25), pricing.log_loss(df.b_o25, df.y_o25)],
           "corners95": [pricing.log_loss(c.p_c95, c.y_c95), pricing.log_loss(c.b_c95, c.y_c95)],
           "corners105": [pricing.log_loss(c.p_c105, c.y_c105), pricing.log_loss(c.b_c105, c.y_c105)]}
    if sot is not None and len(sot):
        out["sot1"] = [pricing.log_loss(sot.p1, sot.y1), pricing.log_loss(sot.b1, sot.y1)]
        out["sot2"] = [pricing.log_loss(sot.p2, sot.y2), pricing.log_loss(sot.b2, sot.y2)]
        out["sot_players"] = len(sot)
    # favourite calibration (the UCL problem): home-win prob bins
    df = df.assign(ph=[p[0] for p in df.p_res], yh=(df.y_res == 0).astype(int))
    out["fav_calibration"] = pricing.calibration_table(df.ph.tolist(), df.yh.tolist())
    return {k: ([round(x, 4) for x in v] if isinstance(v, list) and v and isinstance(v[0], float) else v) for k, v in out.items()}


def main():
    out_path = os.path.join(ROOT, "reports", "soccer_source_compare.json")
    res = json.load(open(out_path)) if os.path.exists(out_path) else {}
    em, ep = data.matches(), data.players()
    em = em.assign(league=em.league.map(ESPN_TO_CODE)); ep = ep.assign(league=ep.league.map(ESPN_TO_CODE))
    am, ap = af.matches(), af.players()
    seven = set(ESPN_TO_CODE.values())
    variants = [("espn_7_leagues", em, ep, SoccerParams(), True),
                ("af_default", am, ap, SoccerParams(), True),
                ("af_xg", am, ap, SoccerParams(use_xg=True), False),
                ("af_league_offsets", am, ap, SoccerParams(league_offsets=True), False),
                ("af_xg_offsets", am, ap, SoccerParams(use_xg=True, league_offsets=True), True)]
    which = sys.argv[1:] or [v[0] for v in variants]
    for name, m, pl, prm, do_sot in variants:
        if name not in which:
            continue
        t = time.time()
        df, sot = run(m, pl, START, END, prm, sot=do_sot)
        res[name] = {"all": summarize(df, sot if do_sot else None)}
        if name.startswith("af"):
            d7 = df[df.league.isin(seven)]
            res[name]["same_7_leagues"] = summarize(d7, None)
            res[name]["by_league_result_ll"] = {lg: round(ll3(g.p_res, g.y_res), 4) for lg, g in df.groupby("league")}
            res[name]["by_league"] = {}
            for lg, g in df.groupby("league"):
                c = g.dropna(subset=["y_c95"])
                res[name]["by_league"][lg] = {
                    "n": len(g),
                    "result_gain": round(ll3(g.b_res, g.y_res) - ll3(g.p_res, g.y_res), 4),
                    "over25_gain": round(pricing.log_loss(g.b_o25, g.y_o25) - pricing.log_loss(g.p_o25, g.y_o25), 4),
                    "corners95_gain": round(pricing.log_loss(c.b_c95, c.y_c95) - pricing.log_loss(c.p_c95, c.y_c95), 4) if len(c) else None,
                    "corners105_gain": round(pricing.log_loss(c.b_c105, c.y_c105) - pricing.log_loss(c.p_c105, c.y_c105), 4) if len(c) else None}
        res[name]["seconds"] = round(time.time() - t)
        print(name, json.dumps({k: v for k, v in res[name]["all"].items() if k != "fav_calibration"}), flush=True)
        json.dump(res, open(out_path, "w"), indent=1, default=float)


if __name__ == "__main__":
    main()
