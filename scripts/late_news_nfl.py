"""NFL late news: after inactives (~90 minutes before kickoff), re-project every NFL player leg on today's slips with
the current ESPN injury/inactive report and post what moved to the NBA/NFL Discord channel.

Usage: python3 scripts/late_news_nfl.py [YYYY-MM-DD]
Looks at legs/<date>-nfl.json and legs/<date>-pm.json. Only games that have not kicked off are checked.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from desk import config, discord
from desk.nba.live import norm
from desk.nfl import data as nfl_data
from desk.nfl.model import NFLModel, prob_at_least

spec = importlib.util.spec_from_file_location("board", os.path.join(ROOT, "scripts", "board.py"))
board = importlib.util.module_from_spec(spec)
spec.loader.exec_module(board)


def leg_prob(sims, leg):
    stat = leg.get("stat")
    if "min" in leg:
        return prob_at_least(sims, stat, int(leg["min"]), calibrated=True)
    if "max" in leg:
        p = prob_at_least(sims, stat, int(leg["max"]) + 1, calibrated=True)
        return None if p is None else 1 - p
    return None


def main():
    day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else config.et_today()
    legs = []
    for sess in ("nfl", "pm"):
        path = os.path.join(ROOT, "legs", f"{day}-{sess}.json")
        if os.path.exists(path):
            legs += [(s["name"], leg) for s in json.load(open(path)).get("slips", []) for leg in s.get("legs", [])
                     if leg.get("league") == "nfl" and leg.get("player")]
    games = board.nfl_slate(day)  # only games not started
    if not legs or not games:
        print("nothing to check")
        return
    nfl_data.download()
    pg = nfl_data.player_games()
    model = NFLModel(pg[pg.date < day.isoformat()])
    old = {}
    for sess in ("nfl", "pm"):
        bp = os.path.join(ROOT, "boards", f"{day}-{sess}.json")
        if os.path.exists(bp):
            for g in json.load(open(bp)).get("nfl", {}).get("games", []):
                old[g["event"]] = g.get("injury_report", {})
    changes, moved = [], []
    for g in games:
        prev = old.get(g["event"], {})
        for name in sorted(set(prev) | set(g["injury_report"])):
            a, b = prev.get(name, "active") or "active", g["injury_report"].get(name, "active") or "active"
            if a.lower() != b.lower():
                changes.append(f"• **{name.title()}** ({g['event']}): {a} → **{b}**")
        for espn_team in g["teams"].values():
            team = board.ESPN_TO_NFLVERSE.get(espn_team, espn_team)
            regs = model.team_players(team)
            ids = {norm(p.name): p.player_id for p in regs}
            mine = [(s, l) for s, l in legs if norm(l["player"]) in ids]
            if not mine:
                continue
            avail_now = {p.player_id for p in regs if g["injury_report"].get(norm(p.name), "").lower() not in board.NFL_OUT}
            avail_then = {p.player_id for p in regs if prev.get(norm(p.name), "").lower() not in board.NFL_OUT}
            now = model.project_team(team, avail_now, g["spread"].get(espn_team), g["total"])
            then = model.project_team(team, avail_then, g["spread"].get(espn_team), g["total"])
            for slip, leg in mine:
                pid = ids[norm(leg["player"])]
                status = g["injury_report"].get(norm(leg["player"]), "")
                if pid not in now:
                    moved.append(f"• ⚠️ **{leg['player']}** is listed **{status or 'not active'}** — leg is dead · _{slip}_")
                    continue
                pn = leg_prob(now[pid]["sims"], leg)
                po = leg_prob(then[pid]["sims"], leg) if pid in then else None
                if pn is not None and po is not None and abs(pn - po) >= 0.02:
                    tgt = f"{leg['min']}+" if "min" in leg else f"≤{leg['max']}"
                    moved.append(f"• {leg['player']} {tgt} {leg['stat']}: {po:.0%} → **{pn:.0%}** · _{slip}_")
    if not changes and not moved:
        discord.post("nba_nfl", [{"title": f"🟢 NFL inactives check · {day}", "color": 0x2ECC71,
                                  "description": f"No status changes affecting {len(legs)} NFL legs."}])
        return
    embed = {"title": f"🚨 NFL inactives check · {day}", "color": 0xE67E22, "fields": []}
    if changes:
        embed["fields"].append({"name": "Status changes since the board", "value": "\n".join(changes)[:1024]})
    for i in range(0, len(moved), 8):
        embed["fields"].append({"name": "Legs affected" + (" (cont.)" if i else ""), "value": "\n".join(moved[i:i + 8])})
    discord.post("nba_nfl", [embed])
    print("\n".join(changes + moved))


if __name__ == "__main__":
    main()
