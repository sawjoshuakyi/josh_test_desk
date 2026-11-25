"""Official NBA schedule (cdn.nba.com, the league's own feed): game type for each game — regular season or
Emirates NBA Cup (group stage / knockout) — from the schedule's gameLabel / gameSubLabel / gameSubtype fields.
Writes data/nba_bdl/schedule.json: [{date, home, away, label, sublabel, subtype, cup}] for the season."""
from __future__ import annotations

import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PATH = os.path.join(ROOT, "data", "nba_bdl", "schedule.json")
URL = "https://cdn.nba.com/static/json/staticData/scheduleLeagueV2.json"


def update() -> int:
    req = urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0 BettingDesk/1.0", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        js = json.loads(r.read().decode())
    out = []
    for day in js.get("leagueSchedule", {}).get("gameDates", []):
        for g in day.get("games", []):
            label, sub, st = g.get("gameLabel") or "", g.get("gameSubLabel") or "", g.get("gameSubtype") or ""
            text = f"{label} {sub} {st}".lower()
            out.append({"date": (g.get("gameDateEst") or "")[:10], "game_id": g.get("gameId"),
                        "home": (g.get("homeTeam") or {}).get("teamTricode"), "away": (g.get("awayTeam") or {}).get("teamTricode"),
                        "label": label, "sublabel": sub, "subtype": st,
                        "cup": "cup" in text or "in-season" in text})
    os.makedirs(os.path.dirname(PATH), exist_ok=True)
    json.dump(out, open(PATH, "w"))
    sample = [g for g in out if g["cup"]][:5] + out[:3]
    os.makedirs(os.path.join(ROOT, "reports", "bdl_samples"), exist_ok=True)
    json.dump(sample, open(os.path.join(ROOT, "reports", "bdl_samples", "nba_schedule.json"), "w"), indent=1)
    return len(out)


def load() -> list[dict]:
    return json.load(open(PATH)) if os.path.exists(PATH) else []
