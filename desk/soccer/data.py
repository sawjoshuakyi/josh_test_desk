"""Soccer data from ESPN's public JSON: team match stats and player stats with minutes.

data/soccer/matches.csv.gz — one row per team per match: goals, shots, shots on target, corners, possession, ...
data/soccer/players.csv.gz — one row per player per match: starter, minutes, shots, shots on target, goals, position.
`update()` appends finished matches since the last stored date (or backfills from START).
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import os
import time
import urllib.request

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, "data", "soccer")
MATCHES = os.path.join(DIR, "matches")   # monthly files matches-YYYY-MM.csv.gz (past months never change)
PLAYERS = os.path.join(DIR, "players")
_DT = {"event_id": str, "player_id": str, "team_id": str, "opp_id": str}


def _read(prefix: str) -> pd.DataFrame:
    import glob
    files = sorted(glob.glob(f"{prefix}-*.csv.gz"))
    return pd.concat([pd.read_csv(f, dtype=_DT) for f in files], ignore_index=True) if files else pd.DataFrame()


def _write(prefix: str, df: pd.DataFrame, key: list[str], months: set[str]) -> None:
    for mth in months:
        part = df[df.date.str[:7] == mth]
        path = f"{prefix}-{mth}.csv.gz"
        if os.path.exists(path):
            part = pd.concat([pd.read_csv(path, dtype=_DT), part], ignore_index=True)
        part.drop_duplicates(key, keep="last").sort_values(["date", "event_id"]).to_csv(path, index=False)
START = dt.date(2024, 7, 1)

LEAGUES = {  # ESPN slug -> (Odds API sport key, tracker league code)
    "eng.1": ("soccer_epl", "epl"), "esp.1": ("soccer_spain_la_liga", "laliga"),
    "ita.1": ("soccer_italy_serie_a", "seriea"), "ger.1": ("soccer_germany_bundesliga", "bundesliga"),
    "fra.1": ("soccer_france_ligue_one", "ligue1"), "uefa.champions": ("soccer_uefa_champs_league", "ucl"),
    "usa.1": ("soccer_usa_mls", "mls"),
}
TEAM_STATS = ["totalShots", "shotsOnTarget", "wonCorners", "possessionPct", "foulsCommitted", "yellowCards",
              "redCards", "offsides", "saves", "accuratePasses", "totalPasses", "totalCrosses", "blockedShots"]


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BettingDesk/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(1 + i)


def month_events(league: str, year: int, month: int) -> list[dict]:
    sb = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={year}{month:02d}&limit=400")
    out = []
    for ev in sb.get("events", []):
        comp = ev["competitions"][0]
        if comp.get("status", {}).get("type", {}).get("completed"):
            out.append({"id": ev["id"], "date": ev["date"][:10]})
    return out


def parse_match(league: str, event_id: str, date: str) -> tuple[list[dict], list[dict]]:
    s = _get(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={event_id}")
    comp = s["header"]["competitions"][0]
    sides = {c["homeAway"]: c for c in comp["competitors"]}
    if len(sides) != 2:
        return [], []
    score = {k: float(v.get("score") or 0) for k, v in sides.items()}
    stats = {}
    for tb in s.get("boxscore", {}).get("teams", []):
        st = {x["name"]: x.get("displayValue") for x in tb.get("statistics", [])}
        stats[tb["team"]["id"]] = st
    rows = []
    for ha, c in sides.items():
        opp = sides["away" if ha == "home" else "home"]
        st = stats.get(c["team"]["id"], {})
        row = {"league": league, "event_id": event_id, "date": date, "team": c["team"]["displayName"],
               "team_id": c["team"]["id"], "opp": opp["team"]["displayName"], "opp_id": opp["team"]["id"],
               "home": int(ha == "home"), "goals": score[ha], "goals_against": score["away" if ha == "home" else "home"]}
        for k in TEAM_STATS:
            try:
                row[k] = float(st.get(k)) if st.get(k) not in (None, "") else None
            except ValueError:
                row[k] = None
        rows.append(row)
    # minutes from substitutions
    sub_in, sub_out = {}, {}
    for k in s.get("keyEvents", []):
        if k.get("type", {}).get("type") != "substitution":
            continue
        minute = (k.get("clock", {}).get("value") or 0) / 60
        parts = k.get("participants", [])
        if len(parts) >= 2:
            sub_in[parts[0]["athlete"]["id"]] = minute
            sub_out[parts[1]["athlete"]["id"]] = minute
    end = 90.0
    players = []
    for r in s.get("rosters", []):
        team_id = r["team"]["id"]
        for p in r.get("roster", []):
            a = p["athlete"]
            st = {x["name"]: x.get("value") for x in p.get("stats", [])}
            starter = bool(p.get("starter"))
            if starter:
                mins = min(sub_out.get(a["id"], end), end)
            elif p.get("subbedIn") or a["id"] in sub_in:
                mins = max(end - sub_in.get(a["id"], end), 1.0)
            else:
                mins = 0.0
            if mins <= 0:
                continue
            players.append({"league": league, "event_id": event_id, "date": date, "team_id": team_id,
                            "player_id": a["id"], "player": a.get("displayName"),
                            "pos": (p.get("position") or {}).get("abbreviation"), "starter": int(starter),
                            "minutes": round(mins, 1), "shots": st.get("totalShots") or 0,
                            "sot": st.get("shotsOnTarget") or 0, "goals": st.get("totalGoals") or 0,
                            "assists": st.get("goalAssists") or 0})
    return rows, players


def update(until: dt.date | None = None, workers: int = 8) -> int:
    os.makedirs(DIR, exist_ok=True)
    until = until or dt.date.today()
    have = set()
    existing = _read(MATCHES)
    if len(existing):
        have = set(existing.event_id)
        start = dt.date.fromisoformat(existing.date.max()) - dt.timedelta(days=10)
    else:
        start = START
    months, d = [], dt.date(start.year, start.month, 1)
    while d <= until:
        months.append((d.year, d.month))
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    todo = []
    for league in LEAGUES:
        for y, mth in months:
            try:
                for ev in month_events(league, y, mth):
                    if ev["id"] not in have and ev["date"] <= until.isoformat():
                        todo.append((league, ev["id"], ev["date"]))
                        have.add(ev["id"])
            except Exception as err:
                print("scoreboard failed", league, y, mth, err)
    match_rows, player_rows = [], []
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(parse_match, *t): t for t in todo}
        for f in cf.as_completed(futs):
            try:
                mr, pr = f.result()
                match_rows += mr
                player_rows += pr
            except Exception as err:
                print("summary failed", futs[f], err)
    for prefix, rows, key in ((MATCHES, match_rows, ["event_id", "team_id"]), (PLAYERS, player_rows, ["event_id", "player_id"])):
        if rows:
            new = pd.DataFrame(rows)
            _write(prefix, new, key, set(new.date.str[:7]))
    return len(todo)


def matches() -> pd.DataFrame:
    return _read(MATCHES)


def players() -> pd.DataFrame:
    return _read(PLAYERS)


_DROP = {"fc", "afc", "cf", "sc", "the", "club", "ac", "as", "ss", "sv", "fsv", "tsg", "rc", "cd", "ud", "sd", "ca",
         "rcd", "de", "1", "and", "calcio", "football", "futbol", "ssc", "acf", "vfl", "vfb", "bc", "if", "fk", "ogc", "losc"}


def team_key(name: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    s = "".join(ch if (ch.isalnum() or ch == " ") else " " for ch in s.replace("&", " "))
    return " ".join(t for t in s.split() if t not in _DROP)


ALIASES = {"milan": "ac milan", "internazionale": "inter milan", "inter": "inter milan", "man utd": "manchester united",
           "man united": "manchester united", "man city": "manchester city", "psg": "paris saint germain",
           "paris sg": "paris saint germain", "spurs": "tottenham hotspur", "tottenham": "tottenham hotspur",
           "wolves": "wolverhampton wanderers", "wolverhampton": "wolverhampton wanderers", "atletico": "atletico madrid",
           "atl madrid": "atletico madrid", "bayern": "bayern munich", "bayern munchen": "bayern munich",
           "gladbach": "borussia monchengladbach", "monchengladbach": "borussia monchengladbach",
           "dortmund": "borussia dortmund", "leverkusen": "bayer leverkusen", "napoli": "napoli", "roma": "roma",
           "newcastle": "newcastle united", "west ham": "west ham united", "brighton": "brighton hove albion",
           "nottm forest": "nottingham forest", "sporting": "sporting cp", "sporting lisbon": "sporting cp",
           "inter miami": "inter miami", "la galaxy": "la galaxy", "lafc": "los angeles fc"}


def _canon(name: str) -> str:
    k = team_key(name)
    return ALIASES.get(k, k)


def same_team(a: str, b: str) -> bool:
    """Conservative team-name match: exact/alias, word containment, or most words shared. 'Manchester United' and
    'Manchester City' do NOT match."""
    import difflib
    x, y = _canon(a), _canon(b)
    if not x or not y:
        return False
    if x == y:
        return True
    tx, ty = set(x.split()), set(y.split())
    if tx <= ty or ty <= tx:
        return True
    if len(tx & ty) / len(tx | ty) >= 0.6:
        return True
    if len(tx) == 1 and len(ty) == 1:
        return difflib.SequenceMatcher(None, x, y).ratio() >= 0.85
    return False
