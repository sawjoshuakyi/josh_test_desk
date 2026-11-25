"""Load balldontlie NBA data (+ the official NBA schedule). Usage: nba_bdl_update.py [--backfill]."""
import json, os, sys, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from desk.nba import bdl, schedule

rep = {}
try:
    rep.update(bdl.update(backfill="--backfill" in sys.argv))
except Exception:
    rep["bdl_error"] = traceback.format_exc()[-2000:]
try:
    rep["schedule_games"] = schedule.update()
except Exception:
    rep["schedule_error"] = traceback.format_exc()[-1500:]
os.makedirs("reports", exist_ok=True)
json.dump(rep, open("reports/nba_bdl_update.json", "w"), indent=1, default=str)
print(json.dumps(rep, indent=1, default=str))
sys.exit(1 if "bdl_error" in rep else 0)
