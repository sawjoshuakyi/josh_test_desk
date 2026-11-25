"""Slip exposure check: which single legs and which single games can kill several of the desk's slips at once.

Usage: python3 scripts/exposure.py legs.json   (the live-tracker format; only slips named "Desk ..." are checked)
Exit code 1 when a hard rule is broken, so the manager must fix the slips before publishing:
  - the same leg appears in more than 1 slip of one sport (one leg, one slip: a miss may only ever cost one slip)
  - one game carries legs of 3 or more of a sport's slips (one game may touch at most 2 slips)
  - one game carries a leg of 3 or more slips AND those slips all need the same side of that game
Warnings (reported, not blocking): every slip of a sport comes from a single game; lotto filler moneylines.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict


def leg_id(leg: dict) -> str:
    keys = ("league", "teams", "type", "player", "stat", "min", "max", "team", "line", "dir")
    return json.dumps({k: leg.get(k) for k in keys}, sort_keys=True)


def label(leg: dict) -> str:
    if leg.get("player"):
        tgt = f"{leg['min']}+" if "min" in leg else f"<={leg.get('max')}"
        return f"{leg['player']} {tgt} {leg.get('stat')}"
    t = leg.get("type")
    if t in ("moneyline", "spread", "games_spread"):
        return f"{leg['team']} {t}{'' if leg.get('line') is None else ' ' + str(leg['line'])}"
    return f"{'/'.join(leg['teams'])} {t} {leg.get('dir', '')} {leg.get('line', '')}".strip()


def side(leg: dict) -> str | None:
    """The game-level outcome a leg leans on (team win/cover, total direction); player overs lean 'over'."""
    t = leg.get("type")
    if t in ("moneyline", "spread", "games_spread"):
        return f"team:{leg['team']}"
    if t in ("total", "corners", "total_games"):
        return f"total:{leg['dir']}"
    if leg.get("player"):
        return "total:over" if "min" in leg else "total:under"
    return None


def sport_of(name: str) -> str:
    parts = name.split()
    return parts[1] if len(parts) > 1 else "?"


def main(path: str) -> int:
    slips = [s for s in json.load(open(path)).get("slips", []) if s.get("name", "").startswith("Desk")]
    errors, warnings = [], []
    by_sport = defaultdict(list)
    for s in slips:
        by_sport[sport_of(s["name"])].append(s)
    for sport, ss in by_sport.items():
        uses = defaultdict(list)
        games = defaultdict(lambda: defaultdict(set))
        for s in ss:
            for leg in s["legs"]:
                uses[leg_id(leg)].append((s["name"], label(leg)))
                g = "/".join(sorted(leg.get("teams", [])))
                if side(leg):
                    games[g][s["name"]].add(side(leg))
        for lid, u in uses.items():
            if len(u) > 1:
                errors.append(f"{sport}: '{u[0][1]}' is in {len(u)} slips ({', '.join(n for n, _ in u)}) — one leg, one slip.")
        game_slips = defaultdict(set)
        for s in ss:
            for leg in s["legs"]:
                game_slips["/".join(sorted(leg.get("teams", [])))].add(s["name"])
        for g, names in game_slips.items():
            if len(names) >= 3 and not any("Lotto" in n for n in names):
                errors.append(f"{sport}: {g} is in {len(names)} slips ({', '.join(sorted(names))}) — max 2 slips per game.")
        for g, per_slip in games.items():
            counts = defaultdict(list)
            for name, sides in per_slip.items():
                for x in sides:
                    counts[x].append(name)
            for x, names in counts.items():
                if len(names) >= 3 and x.startswith("team:"):
                    errors.append(f"{sport}: {len(names)} slips need {x[5:]} to win/cover in {g} "
                                  f"({', '.join(names)}) — one result busts most of the card.")
                elif len(names) >= 3:
                    warnings.append(f"{sport}: {len(names)} slips all lean {x[6:]} in {g} — same game script.")
        if len(ss) >= 2 and len({"/".join(sorted(l.get('teams', []))) for s in ss for l in s['legs']}) == 1:
            warnings.append(f"{sport}: every slip comes from one game — the whole card rides on one game script.")
        print(f"\n{sport}: {len(ss)} slips")
        for lid, u in sorted(uses.items(), key=lambda kv: -len(kv[1])):
            if len(u) > 1:
                print(f"  {len(u)} slips · {u[0][1]}")
    for w in warnings:
        print("WARN ", w)
    for e in errors:
        print("ERROR", e)
    print("\nOK" if not errors else f"\n{len(errors)} rule violation(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
