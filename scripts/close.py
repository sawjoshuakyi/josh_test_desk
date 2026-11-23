"""Closing-line capture. Run every ~15 minutes: for every event priced on today's boards that starts within the
next CLOSE_WINDOW minutes (or started in the last 5), fetch its odds once and archive them as the closing line.

Costs nothing when no event is about to start (events are found from the archived opening snapshots).
Usage: python3 scripts/close.py
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from desk import config, db
from desk.odds import OddsAPI, OddsAPIError, flatten

WINDOW = int(os.environ.get("CLOSE_WINDOW", "35"))


def main():
    now = dt.datetime.now(dt.timezone.utc)
    days = {f"{(now - dt.timedelta(days=d)):%Y-%m-%d}" for d in (0, 1)}
    wanted = set()  # events we priced: all NBA prop games and tennis matches, plus game lines with a flagged edge
    for path in glob.glob(os.path.join(ROOT, "boards", "*.json")):
        if not any(os.path.basename(path).startswith(d) for d in days):
            continue
        b = json.load(open(path))
        wanted |= {r["event_id"] for r in b.get("nba", {}).get("props", []) if r.get("event_id")}
        wanted |= {r["event_id"] for r in b.get("tennis", {}).get("priced", []) if r.get("event_id")}
        for key in ("nba_lines", "nfl_lines", "soccer_lines"):
            wanted |= {r["event_id"] for r in b.get(key, []) if r.get("flag") and r.get("event_id")}
    opens = [r for d in days for r in db.load_snapshots(f"{d}-open-") if r["event_id"] in wanted]
    closed = {r["event_id"] for d in days for r in db.load_snapshots(f"{d}-close-")}
    due = {}
    for r in opens:
        if r["event_id"] in closed or r["event_id"] in due:
            continue
        start = dt.datetime.fromisoformat(r["commence"].replace("Z", "+00:00"))
        if now - dt.timedelta(minutes=5) <= start <= now + dt.timedelta(minutes=WINDOW):
            due[r["event_id"]] = r
    if not due:
        print("nothing about to start")
        return
    try:
        api = OddsAPI()
    except OddsAPIError:
        print("no ODDS_API_KEY; skipping")
        return
    for eid, r in due.items():
        sport, kind = r["sport"], r["kind"]
        markets = sorted({x["market"] for x in opens if x["event_id"] == eid})
        try:
            payload = api.event_odds(sport, eid, markets)
        except OddsAPIError as err:
            print("odds error", eid, err)
            continue
        rows = flatten(payload, kind, sport)
        tag = "nba-props" if kind == "props" else sport.split("_")[0]
        db.archive(rows, f"close-{tag}")
        print(f"closed {r['away']} @ {r['home']} ({len(markets)} markets, {len(rows)} prices) · credits left {api.remaining}")
        if api.remaining is not None and float(api.remaining) < config.MIN_CREDITS:
            print("credit guard hit")
            break


if __name__ == "__main__":
    main()
