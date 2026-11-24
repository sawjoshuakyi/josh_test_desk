"""Reasoning bullets + model probability for any NBA or NFL player leg, from the desk's own data.

Usage:
  python3 scripts/leg_facts.py nba "Isaiah Hartenstein" ast 3.5 over [YYYY-MM-DD]
  python3 scripts/leg_facts.py nfl "Ja'Marr Chase" rec 5.5 over [YYYY-MM-DD]
Stats — NBA: pts reb ast threes pra · NFL: rec rec_yds rush_yds rush_att pass_yds pass_att pass_cmp pass_td td
rush_rec_yds. For an "N+" alt line pass N-0.5 (e.g. 4+ assists -> 3.5).
The model probability uses today's ESPN injury report (players listed out/doubtful are removed and their usage
redistributed). Prints markdown bullets the desk pastes under the leg.
"""
from __future__ import annotations

import datetime as dt
import math
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from desk import config, facts


def nba(player, stat, line, side, day):
    from desk.nba import data as nba_data
    from desk.nba.live import norm, slate, team_projections
    from desk.nba.model import Projector
    box = pd.read_csv(nba_data.BOX_CSV, dtype={"game_id": str, "player_id": str})
    hist = box[box.date < day.isoformat()]
    bullets = facts.nba_facts(box, player, stat, line, side, day.isoformat())
    proj = Projector(hist)
    for g in slate(day):
        for team in g["teams"].values():
            for pr, row in team_projections(proj, hist, team, g["injury_report"], g["spread"].get(team), g["total"]):
                if norm(row["player"]) == norm(player):
                    teams = list(g["teams"].values())
                    opp = teams[1] if teams[0] == team else teams[0]
                    bullets += facts.nba_matchup(box, opp, stat, day.isoformat())
                    p_over = proj.prob_at_least(pr, stat, math.floor(line) + 1)
                    p = p_over if side == "over" else 1 - p_over
                    mean = row["pra"] if stat == "pra" else row.get(stat, 0)
                    bullets.append(facts.model_bullet(mean, p, None, None, line, side, stat,
                                                      f"Projected {row['minutes']} minutes; status {row['status']}"))
                    return bullets
    bullets.append("Model: player not in tonight's projected rotation (check status).")
    return bullets


def nfl(player, stat, line, side, day):
    import importlib.util
    from desk.nba.live import norm
    from desk.nfl import data as nfl_data
    from desk.nfl.model import prob_at_least
    spec = importlib.util.spec_from_file_location("board", os.path.join(ROOT, "scripts", "board.py"))
    board = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(board)
    if not os.path.exists(os.path.join(nfl_data.DIR, "games.csv")):
        nfl_data.download()
    pg = nfl_data.player_games()
    match = pg[pg.player_display_name.map(norm) == norm(player)]
    if match.empty:
        return [f"No nflverse history for {player}."]
    pid = match.player_id.iloc[-1]
    bullets = facts.nfl_facts(pg, pid, player, stat, line, side, day.isoformat(), int(pg.season.max()))
    from desk.nfl.model import NFLModel
    model = NFLModel(pg[pg.date < day.isoformat()])
    for g in board.nfl_slate(day):
        for espn_team in g["teams"].values():
            team = board.ESPN_TO_NFLVERSE.get(espn_team, espn_team)
            regs = model.team_players(team)
            if pid not in {p.player_id for p in regs}:
                continue
            avail = {p.player_id for p in regs if g["injury_report"].get(norm(p.name), "").lower() not in board.NFL_OUT}
            pj = model.project_team(team, avail, g["spread"].get(espn_team), g["total"]).get(pid)
            if pj:
                others = [t for t in g["teams"].values() if t != espn_team]
                if others:
                    opp = board.ESPN_TO_NFLVERSE.get(others[0], others[0])
                    bullets += facts.nfl_matchup(pg, opp, pj["state"].position, stat, day.isoformat(), int(pg.season.max()))
                p_over = prob_at_least(pj["sims"], stat, math.floor(line) + 1, calibrated=True)
                p = p_over if side == "over" else 1 - p_over
                bullets.append(facts.model_bullet(pj["means"].get(stat, 0), p, None, None, line, side, stat))
                return bullets
    bullets.append("Model: no game today for this player, or he is listed out.")
    return bullets


def main():
    league, player, stat, line, side = sys.argv[1:6]
    day = dt.date.fromisoformat(sys.argv[6]) if len(sys.argv) > 6 else config.et_today()
    fn = nba if league.lower() == "nba" else nfl
    for b in fn(player, stat, float(line), side.lower(), day):
        print(f"- {b}")


if __name__ == "__main__":
    main()
