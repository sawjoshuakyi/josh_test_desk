"""Smoke test of the API-Football soccer board for tomorrow (no odds, no board files touched).
Writes reports/soccer_af_smoke.json: fixture count per league, validated markets, and any error."""
import datetime as dt, json, os, sys, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "scripts"))
from desk import config

out = {"ran_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
try:
    import board
    day = config.et_today() + dt.timedelta(days=1)
    sc = board.soccer_board(day, None)
    fx = sc["fixtures"]
    out.update(day=day.isoformat(), fixtures=len(fx),
               by_league={k: sum(1 for f in fx if f["league"] == k) for k in sorted({f["league"] for f in fx})},
               sample=[{k: f[k] for k in ("league", "home", "away", "start", "p_home", "p_draw", "p_away", "xg_home",
                                          "xg_away", "exp_corners", "markets_validated", "low_sample")} | {"players": len(f["players"])}
                       for f in fx[:8]])
except Exception:
    out["error"] = traceback.format_exc()
os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
json.dump(out, open(os.path.join(ROOT, "reports", "soccer_af_smoke.json"), "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str)[:4000])
