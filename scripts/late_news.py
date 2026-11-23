"""Late NBA news check (~30 minutes before the first tip).

Compares the current ESPN injury report with the one the model board used, re-projects every NBA prop leg in
today's slips (legs/<date>-pm.json) and posts what changed to the NBA/NFL Discord channel: status changes,
the legs they touch, and each leg's model hit probability before -> now.
Usage: python3 scripts/late_news.py [YYYY-MM-DD]
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from desk import config, discord
from desk.nba import data as nba_data
from desk.nba.live import norm, slate, team_projections
from desk.nba.model import Projector

STAT_ALIAS = {"pts": "pts", "reb": "reb", "ast": "ast", "threes": "threes", "pra": "pra"}


def leg_prob(proj, pr, leg):
    stat = STAT_ALIAS.get(leg.get("stat"))
    if not stat:
        return None
    if "min" in leg:
        return proj.prob_at_least(pr, stat, int(leg["min"]))
    if "max" in leg:
        return 1 - proj.prob_at_least(pr, stat, int(leg["max"]) + 1)
    return None


def main():
    day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else config.et_today()
    board_path = os.path.join(ROOT, "boards", f"{day}-pm.json")
    legs_path = os.path.join(ROOT, "legs", f"{day}-pm.json")
    before = json.load(open(board_path)) if os.path.exists(board_path) else {}
    old_inj = {g["event"]: g.get("injury_report", {}) for g in before.get("nba", {}).get("games", [])}
    old_proj = {norm(r["player"]): r for r in before.get("nba", {}).get("projections", [])}
    slips = json.load(open(legs_path)).get("slips", []) if os.path.exists(legs_path) else []
    nba_legs = [(s["name"], leg) for s in slips for leg in s.get("legs", [])
                if leg.get("league") == "nba" and leg.get("player")]

    box = pd.read_csv(nba_data.BOX_CSV, dtype={"game_id": str, "player_id": str})
    hist = box[box.date < day.isoformat()]
    proj = Projector(hist)
    games = [g for g in slate(day) if g["state"] == "pre"]
    changes, now_proj = [], {}
    for g in games:
        prev = old_inj.get(g["event"], {})
        for name in sorted(set(prev) | set(g["injury_report"])):
            a, b = prev.get(name, "active") or "active", g["injury_report"].get(name, "active") or "active"
            if a.lower() != b.lower():
                mins = old_proj.get(name, {}).get("minutes")
                changes.append({"event": g["event"], "player": name, "was": a, "now": b, "minutes": mins})
        for team in g["teams"].values():
            for pr, row in team_projections(proj, hist, team, g["injury_report"], g["spread"].get(team), g["total"]):
                now_proj[norm(row["player"])] = (pr, row, g["event"], team)

    flagged = []
    for slip, leg in nba_legs:
        key = norm(leg["player"])
        status = next((g["injury_report"].get(key) for g in games if key in g["injury_report"]), None)
        hit = now_proj.get(key)
        if hit is None:
            flagged.append((slip, leg, None, None, status or "not in tonight's projected rotation"))
            continue
        pr, row, event, team = hit
        p_now = leg_prob(proj, pr, leg)
        old = old_proj.get(key)
        p_old = None
        if old:
            # rebuild the board-time projection for the probability comparison
            g = next(x for x in games if x["event"] == event)
            for opr, orow in team_projections(proj, hist, team, old_inj.get(event, {}), g["spread"].get(team), g["total"]):
                if norm(orow["player"]) == key:
                    p_old = leg_prob(proj, opr, leg)
        moved = p_old is not None and p_now is not None and abs(p_now - p_old) >= 0.02
        own_flag = bool(status) and status.lower() not in ("active", "available")
        if own_flag or moved:
            flagged.append((slip, leg, p_old, p_now, status))

    lines = []
    for c in changes:
        mins = f" (model had {c['minutes']} min)" if c["minutes"] else " (not in recent rotation)"
        lines.append(f"• **{c['player'].title()}** {c['event']}: {c['was']} → **{c['now']}**{mins}")
    leg_lines = []
    for slip, leg, p_old, p_now, status in flagged:
        target = f"{leg.get('min', '')}+ " if "min" in leg else f"≤{leg.get('max')} "
        probs = (f"{p_old:.0%} → **{p_now:.0%}**" if p_old is not None and p_now is not None else
                 (f"now {p_now:.0%}" if p_now is not None else "⚠️ check"))
        leg_lines.append(f"• {leg['player']} {target}{leg['stat']} — {probs}{f' · {status}' if status else ''} · _{slip}_")
    if not changes and not flagged:
        discord.post("nba_nfl", [{"title": f"🟢 Late news check · {day}", "color": 0x2ECC71,
                                  "description": f"No injury-status changes since the board ({before.get('generated_at', 'n/a')}). "
                                                 f"{len(nba_legs)} NBA legs re-checked."}])
        print("no changes")
        return
    embed = {"title": f"🚨 Late news check · {day}", "color": 0xE67E22,
             "description": "Status changes since the model board, and slip legs whose model probability moved.",
             "fields": []}
    if lines:
        embed["fields"].append({"name": "Status changes", "value": "\n".join(lines)[:1024]})
    if leg_lines:
        for i in range(0, len(leg_lines), 8):
            embed["fields"].append({"name": "Legs affected" + (" (cont.)" if i else ""), "value": "\n".join(leg_lines[i:i + 8])})
    embed["footer"] = {"text": "Model probability = minutes × rate model with current availability. Re-check before tip."}
    discord.post("nba_nfl", [embed])
    print("\n".join(lines + leg_lines))


if __name__ == "__main__":
    main()
