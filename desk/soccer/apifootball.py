"""Soccer data from API-Football (api-sports.io v3, Pro plan): team match stats, player stats, fixtures, lineups.

Writes the same layout the soccer models read (desk/soccer/data.py), under data/soccer_af/:
  matches-YYYY-MM.csv.gz — one row per team per match: goals, shots, shots on target, corners, possession, xG, ...
  players-YYYY-MM.csv.gz — one row per player per match: starter, minutes, shots, shots on target, goals, position.
`league` is the desk's tracker code (epl, ucl, efl_champ, ...). Team and player ids are API-Football ids.
Key: API_FOOTBALL_KEY (GitHub secret). Pro plan: 7,500 requests/day, 300/minute.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIR = os.path.join(ROOT, "data", "soccer_af")
MATCHES = os.path.join(DIR, "matches")
PLAYERS = os.path.join(DIR, "players")
BASE = "https://v3.football.api-sports.io"
_DT = {"event_id": str, "player_id": str, "team_id": str, "opp_id": str}
FIRST_SEASON = 2024          # backfill from the 2024/25 season (calendar leagues: 2024)
GAP = 0.25                   # seconds between calls (Pro: 300/min)

# API-Football league id -> (Odds API sport key, tracker code). Probe of 2026-11-24 confirmed corners, shots on
# target and per-player shots on target for every league here (UCL/Championship/League One had games in play).
LEAGUES = {
    39: ("soccer_epl", "epl"), 140: ("soccer_spain_la_liga", "laliga"), 135: ("soccer_italy_serie_a", "seriea"),
    78: ("soccer_germany_bundesliga", "bundesliga"), 61: ("soccer_france_ligue_one", "ligue1"),
    2: ("soccer_uefa_champs_league", "ucl"), 3: ("soccer_uefa_europa_league", "uel"),
    848: ("soccer_uefa_europa_conference_league", "uecl"), 253: ("soccer_usa_mls", "mls"),
    40: ("soccer_efl_champ", "efl_champ"), 41: ("soccer_england_league1", "efl_l1"),
    42: ("soccer_england_league2", "efl_l2"), 79: ("soccer_germany_bundesliga2", "bundesliga2"),
    136: ("soccer_italy_serie_b", "serieb"), 141: ("soccer_spain_segunda_division", "laliga2"),
    62: ("soccer_france_ligue_two", "ligue2"), 88: ("soccer_netherlands_eredivisie", "eredivisie"),
    94: ("soccer_portugal_primeira_liga", "primeira"), 203: ("soccer_turkey_super_league", "superlig"),
    179: ("soccer_spl", "spl"), 144: ("soccer_belgium_first_div", "belgium"),
    197: ("soccer_greece_super_league", "greece"), 218: ("soccer_austria_bundesliga", "austria"),
    103: ("soccer_norway_eliteserien", "eliteserien"), 262: ("soccer_mexico_ligamx", "ligamx"),
    71: ("soccer_brazil_campeonato", "brasileirao"), 128: ("soccer_argentina_primera_division", "argentina"),
}
CODE_TO_ID = {code: lid for lid, (_k, code) in LEAGUES.items()}
DONE = {"FT", "AET", "PEN"}
STAT = {"Total Shots": "totalShots", "Shots on Goal": "shotsOnTarget", "Corner Kicks": "wonCorners",
        "Ball Possession": "possessionPct", "Fouls": "foulsCommitted", "Yellow Cards": "yellowCards",
        "Red Cards": "redCards", "Offsides": "offsides", "Goalkeeper Saves": "saves", "Passes accurate": "accuratePasses",
        "Total passes": "totalPasses", "Blocked Shots": "blockedShots", "expected_goals": "xg"}
TEAM_COLS = list(STAT.values()) + ["totalCrosses"]


class APIFootballError(RuntimeError):
    pass


def _key() -> str:
    k = os.environ.get("API_FOOTBALL_KEY", "").strip()
    if not k:
        raise APIFootballError("API_FOOTBALL_KEY not set")
    return k


def get(path: str, **params) -> list:
    """GET /path with params; returns `response`. Retries transient errors; raises on API errors."""
    url = f"{BASE}/{path}?{urllib.parse.urlencode(params)}"
    for i in range(4):
        time.sleep(GAP)
        req = urllib.request.Request(url, headers={"x-apisports-key": _key(), "Accept": "application/json",
                                                   "User-Agent": "BettingDesk/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                js = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < 3:
                time.sleep(5 * (i + 1))
                continue
            raise APIFootballError(f"HTTP {e.code} on {path}")
        except Exception as e:
            if i < 3:
                time.sleep(3 * (i + 1))
                continue
            raise APIFootballError(f"{path}: {e}")
        errs = js.get("errors")
        if errs and (isinstance(errs, dict) and errs or isinstance(errs, list) and errs):
            if "rateLimit" in json.dumps(errs) and i < 3:
                time.sleep(10)
                continue
            raise APIFootballError(f"{path}: {errs}")
        return js.get("response") or []
    raise APIFootballError(f"{path}: retries exhausted")


def _num(v):
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip().rstrip("%")
        try:
            return float(v)
        except ValueError:
            return None
    return float(v)


def parse_fixture(f: dict) -> tuple[list[dict], list[dict]]:
    """One /fixtures?ids= item -> (team rows, player rows) in the desk's soccer schema."""
    fx, lg, teams, goals = f["fixture"], f["league"], f["teams"], f["goals"]
    code = LEAGUES.get(lg["id"], (None, f"af{lg['id']}"))[1]
    eid, date = str(fx["id"]), fx["date"][:10]
    h, a = teams["home"], teams["away"]
    stats = {str(t["team"]["id"]): {s["type"]: s["value"] for s in t.get("statistics") or []}
             for t in f.get("statistics") or [] if t.get("team")}
    rows = []
    for me, op, home, gf, ga in ((h, a, 1, goals["home"], goals["away"]), (a, h, 0, goals["away"], goals["home"])):
        st = stats.get(str(me["id"]), {})
        row = {"league": code, "event_id": eid, "date": date, "team": me["name"], "team_id": str(me["id"]),
               "opp": op["name"], "opp_id": str(op["id"]), "home": home, "goals": gf, "goals_against": ga,
               "neutral": int((lg.get("round") or "").lower().startswith("final")), "season": lg.get("season")}
        for src, dst in STAT.items():
            row[dst] = _num(st.get(src))
        row["totalCrosses"] = None
        if row["wonCorners"] is None and (row["totalShots"] is not None or row["shotsOnTarget"] is not None):
            # API-Football leaves zero counts blank; only trust that when the rest of the stats are there
            row["wonCorners"] = 0.0
        rows.append(row)
    players = []
    for t in f.get("players") or []:
        tid = str(t["team"]["id"])
        for p in t.get("players") or []:
            s = (p.get("statistics") or [{}])[0] or {}
            g = s.get("games") or {}
            if not (p.get("player") or {}).get("id"):
                continue
            mins = g.get("minutes") or 0
            if not mins:
                continue
            players.append({"league": code, "event_id": eid, "date": date, "team_id": tid,
                            "player_id": str(p["player"]["id"]), "player": p["player"].get("name"),
                            "pos": g.get("position"), "starter": int(not g.get("substitute", False)),
                            "minutes": float(mins), "shots": (s.get("shots") or {}).get("total") or 0,
                            "sot": (s.get("shots") or {}).get("on") or 0, "goals": (s.get("goals") or {}).get("total") or 0,
                            "assists": (s.get("goals") or {}).get("assists") or 0})
    return rows, players


def _read(prefix: str) -> pd.DataFrame:
    import glob
    files = sorted(glob.glob(f"{prefix}-*.csv.gz"))
    return pd.concat([pd.read_csv(f, dtype=_DT) for f in files], ignore_index=True) if files else pd.DataFrame()


def _write(prefix: str, df: pd.DataFrame, key: list[str]) -> None:
    for mth in sorted(set(df.date.str[:7])):
        part = df[df.date.str[:7] == mth]
        path = f"{prefix}-{mth}.csv.gz"
        if os.path.exists(path):
            part = pd.concat([pd.read_csv(path, dtype=_DT), part], ignore_index=True)
        part.drop_duplicates(key, keep="last").sort_values(["date", "event_id"]).to_csv(path, index=False)


def current_seasons() -> dict[int, int]:
    """League id -> current season year (one request)."""
    out = {}
    for item in get("leagues", current="true"):
        lid = item["league"]["id"]
        if lid in LEAGUES:
            cur = [s["year"] for s in item.get("seasons", []) if s.get("current")]
            if cur:
                out[lid] = cur[0]
    return out


def update(until: dt.date | None = None, leagues: list[int] | None = None, backfill: bool = False,
           max_requests: int = 6000) -> dict:
    """Store every finished fixture not yet stored. Normal runs check the current season only; backfill=True also
    loads past seasons from FIRST_SEASON. Stops before `max_requests` so the daily quota is never exhausted."""
    os.makedirs(DIR, exist_ok=True)
    until = until or dt.date.today()
    stored = _read(MATCHES)
    have = set(stored.event_id) if len(stored) else set()
    seasons = current_seasons()
    used, todo, report = 1, [], {"leagues": {}, "errors": []}
    for lid in leagues or list(LEAGUES):
        cur = seasons.get(lid)
        if cur is None:
            report["errors"].append(f"{lid}: no current season")
            continue
        years = range(FIRST_SEASON, cur + 1) if backfill else [cur]
        n = 0
        for y in years:
            if used >= max_requests:
                break
            try:
                fixtures = get("fixtures", league=lid, season=y)
            except APIFootballError as e:
                report["errors"].append(f"{lid}/{y}: {e}")
                continue
            used += 1
            for f in fixtures:
                if f["fixture"]["status"]["short"] in DONE and f["fixture"]["date"][:10] <= until.isoformat() \
                        and str(f["fixture"]["id"]) not in have:
                    todo.append(f["fixture"]["id"])
                    have.add(str(f["fixture"]["id"]))
                    n += 1
        report["leagues"][LEAGUES[lid][1]] = n
    mrows, prows = [], []
    for i in range(0, len(todo), 20):
        if used >= max_requests:
            report["errors"].append(f"stopped at request cap; {len(todo) - i} fixtures left for the next run")
            break
        chunk = todo[i:i + 20]
        try:
            items = get("fixtures", ids="-".join(str(x) for x in chunk))
        except APIFootballError as e:
            report["errors"].append(f"ids batch {i // 20}: {e}")
            continue
        used += 1
        for f in items:
            try:
                r, p = parse_fixture(f)
            except Exception as e:                       # one odd fixture never stops the load
                report["errors"].append(f"parse {f.get('fixture', {}).get('id')}: {e!r}")
                continue
            mrows += r
            prows += p
        if len(mrows) > 20000:                           # flush in pieces on big backfills
            _write(MATCHES, pd.DataFrame(mrows), ["event_id", "team_id"])
            _write(PLAYERS, pd.DataFrame(prows), ["event_id", "player_id"])
            mrows, prows = [], []
    if mrows:
        _write(MATCHES, pd.DataFrame(mrows), ["event_id", "team_id"])
    if prows:
        _write(PLAYERS, pd.DataFrame(prows), ["event_id", "player_id"])
    report.update(fixtures_loaded=len(todo), requests=used)
    return report


def fixtures_on(day: dt.date, seasons: dict[int, int] | None = None) -> list[dict]:
    """Upcoming fixtures for the desk's leagues on `day` (UTC date). One request for all leagues."""
    out = []
    for f in get("fixtures", date=day.isoformat()):
        if f["league"]["id"] in LEAGUES:
            out.append(f)
    return out


def lineups(fixture_id: int) -> list[dict]:
    return get("fixtures/lineups", fixture=fixture_id)


def matches() -> pd.DataFrame:
    return _read(MATCHES)


def players() -> pd.DataFrame:
    return _read(PLAYERS)
