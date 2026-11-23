"""NBA box-score ingestion from ESPN's public JSON feeds.

Builds data/nba_boxscores.csv: one row per player per game (season to date), with
minutes, stats, starter/DNP flags, final score, and the pregame DraftKings spread/total
that ESPN records in each game's pickcenter.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
BOX_CSV = os.path.join(ROOT, "data", "nba_boxscores.csv")
SB = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={d}"
SUM = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={e}"
SEASON_START = dt.date(2026, 10, 20)

FIELDS = ["game_id", "date", "team", "opp", "home", "player_id", "player", "starter", "dnp",
          "minutes", "pts", "reb", "ast", "threes", "team_pts", "opp_pts", "spread", "total"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BettingDesk/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def final_games(day: dt.date) -> list[str]:
    data = _get(SB.format(d=day.strftime("%Y%m%d")))
    return [e["id"] for e in data.get("events", []) if e["status"]["type"].get("completed")]


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def parse_game(summary: dict, game_id: str, day: str) -> list[dict]:
    comp = summary["header"]["competitions"][0]
    teams = {}
    for c in comp["competitors"]:
        teams[c["team"]["abbreviation"]] = {"home": c.get("homeAway") == "home", "score": _num(c.get("score"))}
    abbrs = list(teams)
    spread_for, total = {a: None for a in abbrs}, None
    pc = summary.get("pickcenter") or []
    if pc:
        line = pc[0]
        total = line.get("overUnder")
        details = (line.get("details") or "").strip()
        if details.upper() in ("EVEN", "PK"):
            spread_for = {a: 0.0 for a in abbrs}
        elif details:
            fav, _, num = details.partition(" ")
            try:
                n = abs(float(num))
                for a in abbrs:
                    spread_for[a] = -n if a == fav else n
            except ValueError:
                pass
    rows = []
    for team_block in summary.get("boxscore", {}).get("players", []):
        team = team_block["team"]["abbreviation"]
        opp = [a for a in abbrs if a != team][0]
        stat = team_block["statistics"][0]
        keys = stat["keys"]
        for a in stat.get("athletes", []):
            vals = dict(zip(keys, a.get("stats", [])))
            dnp = bool(a.get("didNotPlay")) or not a.get("stats")
            threes = (vals.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted") or "0-0").split("-")[0]
            rows.append({
                "game_id": game_id, "date": day, "team": team, "opp": opp,
                "home": int(teams[team]["home"]), "player_id": a["athlete"].get("id"),
                "player": a["athlete"].get("displayName"), "starter": int(bool(a.get("starter"))),
                "dnp": int(dnp), "minutes": _num(vals.get("minutes")), "pts": _num(vals.get("points")),
                "reb": _num(vals.get("rebounds")), "ast": _num(vals.get("assists")), "threes": _num(threes),
                "team_pts": teams[team]["score"], "opp_pts": teams[opp]["score"],
                "spread": spread_for.get(team), "total": total,
            })
    return rows


def update(until: dt.date | None = None, path: str = BOX_CSV, sleep: float = 0.15) -> int:
    """Append every completed game not yet in the CSV, from season start to `until` (default yesterday)."""
    until = until or (dt.date.today() - dt.timedelta(days=1))
    have = set()
    if os.path.exists(path):
        with open(path) as f:
            have = {r["game_id"] for r in csv.DictReader(f)}
    new_rows = []
    day = SEASON_START
    while day <= until:
        for gid in final_games(day):
            if gid in have:
                continue
            new_rows += parse_game(_get(SUM.format(e=gid)), gid, day.isoformat())
            have.add(gid)
            time.sleep(sleep)
        day += dt.timedelta(days=1)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if write_header:
            w.writeheader()
        w.writerows(new_rows)
    return len(new_rows)


if __name__ == "__main__":
    import sys
    until = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else None
    print("rows added:", update(until))
