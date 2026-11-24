"""Watchdog: after each desk session, check that its outputs exist and warn in the general Discord channel if not.

Checks: the model board for the session, the desk's live-tracker legs file (written at the end of every desk run),
and The Odds API credit balance seen by the last board.
Usage: python3 scripts/watchdog.py am|pm|nfl
"""
from __future__ import annotations

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from desk import config, discord

LOW_CREDITS = 1500
NAMES = {"am": "AM (Soccer & Tennis)", "pm": "PM (NBA + NFL)", "nfl": "Sunday NFL"}


def main():
    session = sys.argv[1]
    day = config.et_today()
    problems, notes = [], []
    board = os.path.join(ROOT, "boards", f"{day}-{session}.json")
    legs = os.path.join(ROOT, "legs", f"{day}-{session}.json")
    if not os.path.exists(board):
        problems.append(f"Model board `boards/{day}-{session}.json` is missing — the board workflow did not run or failed.")
    else:
        b = json.load(open(board))
        if b.get("odds_source", "").startswith("none"):
            err = b.get("odds_error") or "ODDS_API_KEY secret not set or invalid"
            problems.append(f"Board ran **without odds** — The Odds API said: `{err[:160]}`. No edges or Kelly stakes "
                            "until the ODDS_API_KEY secret is fixed.")
        credits = b.get("credits_remaining")
        if credits is not None and float(credits) < LOW_CREDITS:
            problems.append(f"The Odds API credits are low: **{credits}** left this month.")
    if not os.path.exists(legs):
        problems.append(f"The {NAMES[session]} desk has not written `legs/{day}-{session}.json` — the desk run may have "
                        "failed or found no slate. Check the scheduled task's last run and the Discord report channel.")
    else:
        desk = [s for s in json.load(open(legs)).get("slips", []) if s.get("name", "").startswith("Desk")]
        if not desk:
            notes.append("Legs file exists but holds no Desk slips (no approved slips today, or the desk skipped the file).")
    if not problems and not notes:
        print("all good")
        return
    discord.post("general", [{"title": f"{'⚠️' if problems else 'ℹ️'} Desk watchdog · {day} {NAMES[session]}",
                              "color": 0xE74C3C if problems else 0x3498DB,
                              "description": "\n".join(f"• {p}" for p in problems + notes)}])
    print("\n".join(problems + notes))


if __name__ == "__main__":
    main()
