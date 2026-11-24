"""Per-leg reasoning bullets computed from the desk's own data (box scores / nflverse), never from outside write-ups.

facts_for_leg(...) returns plain-English bullets like:
  • Hartenstein is averaging 3.9 assists per game this season while playing about 25 minutes per game.
  • He's averaging 5.0 assists over his last 10 games and 4.4 over his last five.
  • He's gone over 3.5 assists in 9 of his last 10 games.
  • His recent game log: 7 vs Memphis, 6 vs Washington, 6 vs Atlanta, 6 vs LA Clippers.
  • He has at least 4 assists in 10 of his 17 games this season.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

NBA_TEAMS = {"ATL": "Atlanta", "BOS": "Boston", "BKN": "Brooklyn", "CHA": "Charlotte", "CHI": "Chicago",
             "CLE": "Cleveland", "DAL": "Dallas", "DEN": "Denver", "DET": "Detroit", "GS": "Golden State",
             "HOU": "Houston", "IND": "Indiana", "LAC": "the Clippers", "LAL": "the Lakers", "MEM": "Memphis",
             "MIA": "Miami", "MIL": "Milwaukee", "MIN": "Minnesota", "NO": "New Orleans", "NY": "New York",
             "OKC": "Oklahoma City", "ORL": "Orlando", "PHI": "Philadelphia", "PHX": "Phoenix", "POR": "Portland",
             "SAC": "Sacramento", "SA": "San Antonio", "TOR": "Toronto", "UTAH": "Utah", "WSH": "Washington"}
NFL_TEAMS = {"ARI": "Arizona", "ATL": "Atlanta", "BAL": "Baltimore", "BUF": "Buffalo", "CAR": "Carolina",
             "CHI": "Chicago", "CIN": "Cincinnati", "CLE": "Cleveland", "DAL": "Dallas", "DEN": "Denver",
             "DET": "Detroit", "GB": "Green Bay", "HOU": "Houston", "IND": "Indianapolis", "JAX": "Jacksonville",
             "KC": "Kansas City", "LA": "the Rams", "LAR": "the Rams", "LAC": "the Chargers", "LV": "Las Vegas",
             "MIA": "Miami", "MIN": "Minnesota", "NE": "New England", "NO": "New Orleans", "NYG": "the Giants",
             "NYJ": "the Jets", "PHI": "Philadelphia", "PIT": "Pittsburgh", "SEA": "Seattle", "SF": "San Francisco",
             "TB": "Tampa Bay", "TEN": "Tennessee", "WAS": "Washington", "WSH": "Washington"}

LABEL = {"pts": "points", "reb": "rebounds", "ast": "assists", "threes": "threes", "pra": "points + rebounds + assists",
         "rec": "receptions", "rec_yds": "receiving yards", "rush_yds": "rushing yards", "rush_att": "rushing attempts",
         "pass_yds": "passing yards", "pass_att": "pass attempts", "pass_cmp": "completions", "pass_td": "passing TDs",
         "td": "touchdowns", "rush_rec_yds": "rushing + receiving yards"}


def _fmt(x: float) -> str:
    return f"{x:.1f}" if abs(x - round(x)) > 1e-9 else f"{int(round(x))}"


def _last(name: str) -> str:
    parts = name.split()
    return parts[-1] if parts[-1].lower().rstrip(".") not in ("jr", "sr", "ii", "iii", "iv") else parts[-2]


def facts_for_leg(name: str, games: pd.DataFrame, values: np.ndarray, opps: list[str], line: float, side: str,
                  stat: str, teams: dict, workload: str, season_mask: np.ndarray) -> list[str]:
    """games/values/opps are the player's prior games, oldest first. workload: phrase like 'playing about 25 minutes'."""
    who, lab = _last(name), LABEL.get(stat, stat)
    out = []
    season_vals = values[season_mask]
    n_season = len(season_vals)
    if n_season:
        out.append(f"{who} is averaging {_fmt(round(season_vals.mean(), 1))} {lab} per game this season while {workload}.")
    l10, l5 = values[-10:], values[-5:]
    if len(l10) >= 5:
        out.append(f"He's averaging {_fmt(round(l10.mean(), 1))} {lab} over his last {len(l10)} games and "
                   f"{_fmt(round(l5.mean(), 1))} over his last five.")
    over = side.lower() == "over"
    hits = int(np.sum(l10 > line)) if over else int(np.sum(l10 < line))
    verb = "gone over" if over else "stayed under"
    out.append(f"He's {verb} {_fmt(line)} {lab} in {hits} of his last {len(l10)} games.")
    log = ", ".join(f"{_fmt(v)} vs {teams.get(o, o)}" for v, o in list(zip(values[-5:], opps[-5:]))[::-1])
    out.append(f"His recent game log (newest first): {log}.")
    if n_season:
        k = math.floor(line) + 1
        if over:
            out.append(f"He has at least {k} {lab} in {int(np.sum(season_vals >= k))} of his {n_season} games this season.")
        else:
            out.append(f"He has {k - 1} or fewer {lab} in {int(np.sum(season_vals <= k - 1))} of his {n_season} games this season.")
    return out


def model_bullet(mean: float, p: float, fair: float | None, edge: float | None, line: float, side: str, stat: str,
                 extra: str = "") -> str:
    s = f"Model: projects {_fmt(round(mean, 1))} {LABEL.get(stat, stat)}; P({side.lower()} {_fmt(line)}) = {p:.0%}"
    if fair is not None:
        s += f" vs {fair:.0%} no-vig market"
    if edge is not None:
        s += f" → edge {edge:+.1%} at the best price"
    return s + (f". {extra}" if extra else ".")


# ------------------------------------------------------------------ NBA
NBA_COLS = {"pts": ["pts"], "reb": ["reb"], "ast": ["ast"], "threes": ["threes"], "pra": ["pts", "reb", "ast"]}


def nba_facts(box: pd.DataFrame, player: str, stat: str, line: float, side: str, before: str, season_start: str = "2026-10-01"):
    from desk.nba.live import norm
    g = box[(box.player.map(norm) == norm(player)) & (box.date < before) & (box.dnp == 0) & (box.minutes > 0)].sort_values("date")
    if g.empty or stat not in NBA_COLS:
        return []
    vals = g[NBA_COLS[stat]].sum(axis=1).to_numpy(float)
    season = (g.date >= season_start).to_numpy()
    mins = g.minutes[season].mean() if season.any() else g.minutes.mean()
    return facts_for_leg(player, g, vals, g.opp.tolist(), line, side, stat, NBA_TEAMS,
                         f"playing about {mins:.0f} minutes per game", season)


# ------------------------------------------------------------------ NFL
NFL_COLS = {"rec": ["receptions"], "rec_yds": ["receiving_yards"], "rush_yds": ["rushing_yards"], "rush_att": ["carries"],
            "pass_yds": ["passing_yards"], "pass_att": ["attempts"], "pass_cmp": ["completions"],
            "pass_td": ["passing_tds"], "td": ["rushing_tds", "receiving_tds"],
            "rush_rec_yds": ["rushing_yards", "receiving_yards"]}


def nfl_facts(pg: pd.DataFrame, player_id: str, name: str, stat: str, line: float, side: str, before: str, season: int):
    g = pg[(pg.player_id == player_id) & (pg.date < before)].sort_values("date")
    if g.empty or stat not in NFL_COLS:
        return []
    vals = g[NFL_COLS[stat]].sum(axis=1).to_numpy(float)
    mask = (g.season == season).to_numpy()
    cur = g[mask] if mask.any() else g
    if stat in ("rec", "rec_yds"):
        work = f"seeing {cur.targets.mean():.1f} targets per game ({cur.target_share.mean():.0%} target share)"
    elif stat in ("rush_yds", "rush_att"):
        work = f"handling {cur.carries.mean():.1f} carries per game"
    elif stat.startswith("pass"):
        work = f"throwing {cur.attempts.mean():.1f} passes per game"
    else:
        work = f"averaging {(cur.targets + cur.carries).mean():.1f} touches+targets per game"
    if "offense_pct" in cur and cur.offense_pct.notna().any():
        work += f" on {cur.offense_pct.mean():.0%} of offensive snaps"
    return facts_for_leg(name, g, vals, g.opponent_team.tolist(), line, side, stat, NFL_TEAMS, work, mask)
