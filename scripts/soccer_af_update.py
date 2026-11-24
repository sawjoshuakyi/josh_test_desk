"""Load API-Football soccer data. Usage: soccer_af_update.py [--backfill] [--max N]. Writes reports/soccer_af_update.json."""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from desk.soccer import apifootball as af

if __name__ == "__main__":
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 6000
    rep = af.update(dt.date.today(), backfill="--backfill" in sys.argv, max_requests=mx)
    m, p = af.matches(), af.players()
    rep["stored"] = {"team_rows": len(m), "player_rows": len(p), "first": m.date.min() if len(m) else None,
                     "last": m.date.max() if len(m) else None,
                     "by_league": m.groupby("league").event_id.nunique().to_dict() if len(m) else {},
                     "missing_corners_pct": round(float(m.wonCorners.isna().mean()) * 100, 2) if len(m) else None,
                     "missing_sot_pct": round(float(m.shotsOnTarget.isna().mean()) * 100, 2) if len(m) else None,
                     "missing_xg_pct": round(float(m.xg.isna().mean()) * 100, 2) if len(m) else None}
    os.makedirs("reports", exist_ok=True)
    json.dump(rep, open("reports/soccer_af_update.json", "w"), indent=1, default=str)
    print(json.dumps(rep, indent=1, default=str))
