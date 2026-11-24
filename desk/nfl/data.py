"""NFL data: nflverse weekly player stats, snap counts and schedules (with closing spread/total).

Files are downloaded to data/nfl/ (not committed; ~40 MB) and refreshed by `download()`.
`player_games()` returns one row per offensive player-game with team context (dropbacks, rush attempts, spread
and total from the team's perspective) used by the model and the backtest.
"""
from __future__ import annotations

import os
import urllib.request

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, "data", "nfl")
BASE = "https://github.com/nflverse/nflverse-data/releases/download"
SEASONS = [2023, 2024, 2025, 2026]
CURRENT = 2026

STAT_COLS = ["completions", "attempts", "passing_yards", "passing_tds", "passing_interceptions", "sacks_suffered",
             "carries", "rushing_yards", "rushing_tds", "receptions", "targets", "receiving_yards", "receiving_tds",
             "target_share", "air_yards_share", "receiving_air_yards"]


def download(seasons=SEASONS, force_current=True) -> None:
    os.makedirs(DIR, exist_ok=True)
    files = [("schedules/games.csv", "games.csv")]
    for y in seasons:
        files += [(f"stats_player/stats_player_week_{y}.csv", f"stats_player_week_{y}.csv"),
                  (f"snap_counts/snap_counts_{y}.csv", f"snap_counts_{y}.csv")]
    for remote, local in files:
        path = os.path.join(DIR, local)
        if os.path.exists(path) and not (force_current and (str(CURRENT) in local or local == "games.csv")):
            continue
        req = urllib.request.Request(f"{BASE}/{remote}", headers={"User-Agent": "BettingDesk/1.0"})
        with urllib.request.urlopen(req, timeout=120) as r, open(path, "wb") as f:
            f.write(r.read())


def games() -> pd.DataFrame:
    g = pd.read_csv(os.path.join(DIR, "games.csv"), low_memory=False)
    return g[g.season.isin(SEASONS)]


def player_games() -> pd.DataFrame:
    frames = []
    for y in SEASONS:
        p = os.path.join(DIR, f"stats_player_week_{y}.csv")
        if os.path.exists(p):
            frames.append(pd.read_csv(p, low_memory=False))
    st = pd.concat(frames, ignore_index=True)
    st = st[st.season_type == "REG"] if "season_type" in st else st
    st = st[st.position.isin(["QB", "RB", "FB", "WR", "TE"])].copy()
    for c in STAT_COLS:
        st[c] = pd.to_numeric(st[c], errors="coerce").fillna(0.0)
    # team context per game
    team = st.groupby(["game_id", "team"]).agg(team_att=("attempts", "sum"), team_sacks=("sacks_suffered", "sum"),
                                                  team_carries=("carries", "sum"), team_targets=("targets", "sum"),
                                                  team_pass_yds=("passing_yards", "sum")).reset_index()
    team["team_dropbacks"] = team.team_att + team.team_sacks
    st = st.merge(team, on=["game_id", "team"], how="left")
    g = games()[["game_id", "gameday", "home_team", "away_team", "spread_line", "total_line", "home_score",
                 "away_score", "roof", "wind", "temp"]]
    st = st.merge(g, on="game_id", how="left")
    st["home"] = (st.team == st.home_team).astype(int)
    # nflverse spread_line is the home team's expected margin; team perspective: negative = favored
    st["spread"] = np.where(st.home == 1, -st.spread_line, st.spread_line)
    st["total"] = st.total_line
    st["date"] = st.gameday
    snaps = []
    for y in SEASONS:
        p = os.path.join(DIR, f"snap_counts_{y}.csv")
        if os.path.exists(p):
            s = pd.read_csv(p, low_memory=False)
            snaps.append(s[["game_id", "player", "team", "offense_snaps", "offense_pct"]])
    if snaps:
        sn = pd.concat(snaps, ignore_index=True)
        sn["key"] = sn.player.str.lower().str.replace(r"[^a-z]", "", regex=True)
        st["key"] = st.player_display_name.str.lower().str.replace(r"[^a-z]", "", regex=True)
        st = st.merge(sn[["game_id", "team", "key", "offense_snaps", "offense_pct"]].drop_duplicates(["game_id", "team", "key"]),
                      on=["game_id", "team", "key"], how="left")
    st = st.sort_values(["date", "game_id", "team", "player_id"]).reset_index(drop=True)
    return st


def name_key(name: str) -> str:
    import re
    return re.sub(r"[^a-z]", "", str(name).lower())


def snap_keys() -> dict:
    """{(game_id, team): set of name keys with at least one offensive snap} — who actually played."""
    out: dict = {}
    for y in SEASONS:
        p = os.path.join(DIR, f"snap_counts_{y}.csv")
        if not os.path.exists(p):
            continue
        s = pd.read_csv(p, low_memory=False)
        s = s[s.offense_snaps.fillna(0) > 0]
        for (gid, team), g in s.groupby(["game_id", "team"]):
            out[(gid, team)] = {name_key(x) for x in g.player}
    return out
