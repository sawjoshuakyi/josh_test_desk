"""Bet-slip links for the desk's slips, from the model board's DraftKings/FanDuel link data.

Usage: python3 scripts/slip_links.py slips.json [--write legs/<date>-<session>.json]
slips.json: {"date": "YYYY-MM-DD", "session": "am|pm|nfl", "slips": [{"name": "Desk NBA Best Bet", "refs": ["nba:12"]}, ...]}
Each ref is a board row's "ref" (e.g. "nba:12", "soccer:4", "tennis:7", "nfl_lines:3").
Prints, per slip: one DraftKings link and one FanDuel link carrying every leg (when every leg is offered there),
plus per-leg links. With --write, adds a "betslip" object to the matching slip (by name) in the live-tracker file.
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from desk.betslip import slip_links

LISTS = {"nba": ("nba", "props"), "nfl": ("nfl", "props"), "tennis": ("tennis", "priced"), "soccer": ("soccer", "props"),
         "nba_lines": ("nba_lines", None), "nfl_lines": ("nfl_lines", None), "soccer_lines": ("soccer_lines", None)}


def board_row(board: dict, ref: str) -> dict | None:
    key, _, idx = ref.partition(":")
    top, sub = LISTS.get(key, (None, None))
    if top is None:
        return None
    rows = board.get(top, {}).get(sub, []) if sub else board.get(top, [])
    i = int(idx)
    return rows[i] if 0 <= i < len(rows) else None


def label(r: dict) -> str:
    if r.get("label"):
        return r["label"]
    if r.get("stat") and r.get("player"):
        return f"{r['player']} {r['side']} {r['line']} {r['stat']}"
    return f"{r.get('event') or r.get('match', '')} {r.get('market', '')} {r.get('side', '')} {'' if r.get('line') is None else r['line']}".strip()


def main():
    spec = json.load(open(sys.argv[1]))
    write = sys.argv[sys.argv.index("--write") + 1] if "--write" in sys.argv else None
    board = json.load(open(os.path.join(ROOT, "boards", f"{spec['date']}-{spec['session']}.json")))
    result = {}
    for slip in spec["slips"]:
        rows = [board_row(board, r) for r in slip["refs"]]
        missing = [r for r, row in zip(slip["refs"], rows) if row is None]
        if missing:
            print(f"{slip['name']}: unknown refs {missing}")
            continue
        for row in rows:
            row["label"] = label(row)
        links = slip_links(rows)
        result[slip["name"]] = links
        print(f"\n{slip['name']}")
        print(f"  DraftKings: {links['draftkings'] or 'not every leg is on DraftKings — use the per-leg links'}")
        print(f"  FanDuel:    {links['fanduel'] or 'not every leg is on FanDuel — use the per-leg links'}")
        for p in links["per_leg"]:
            print(f"    · {p['leg']}: DK {p['draftkings'] or '–'} | FD {p['fanduel'] or '–'}")
    if write:
        book = json.load(open(write))
        for s in book.get("slips", []):
            if s.get("name") in result:
                s["betslip"] = result[s["name"]]
        json.dump(book, open(write, "w"), indent=1, ensure_ascii=False)
        print(f"\nwrote bet-slip links into {write}")


if __name__ == "__main__":
    main()
