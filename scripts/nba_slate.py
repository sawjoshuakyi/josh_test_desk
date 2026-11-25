"""Build today's NBA slate report: reports/nba_slate/<date>.json and .md. Usage: nba_slate.py [YYYY-MM-DD]."""
import datetime as dt, json, os, sys, traceback
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from desk import config
from desk.nba import bdl, schedule, slate

day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else config.et_today()
out_dir = os.path.join(ROOT, "reports", "nba_slate")
os.makedirs(out_dir, exist_ok=True)
try:
    season = bdl.current_season(day)
    rep = slate.build(day, bdl.stats(), bdl.games(), bdl.teams(), bdl.injuries(), schedule.load(), season)
    if not rep["games"]:
        rep["notes"].append("No NBA games on this date.")
    json.dump(rep, open(os.path.join(out_dir, f"{day}.json"), "w"), indent=1, default=float)
    open(os.path.join(out_dir, f"{day}.md"), "w").write(slate.to_markdown(rep))
    print(f"slate report: {len(rep['games'])} games -> reports/nba_slate/{day}.md")
except Exception:
    err = traceback.format_exc()
    open(os.path.join(out_dir, f"{day}.error.txt"), "w").write(err)
    print(err)
    sys.exit(1)
