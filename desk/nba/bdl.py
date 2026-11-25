"""NBA data from balldontlie (ALL-STAR tier): games, per-game player stats, injuries, teams.

data/nba_bdl/teams.json                 — 30 teams (id, abbreviation, conference, division, full name)
data/nba_bdl/games-<season>.csv.gz      — every game of the season (scores, date, postseason flag, status)
data/nba_bdl/stats-<season>.csv.gz      — one row per player per game (min, pts, reb, ast, fg/3p/ft, oreb, tov, pos)
data/nba_bdl/injuries.json              — latest injury report (status, return date, description)
Seasons are balldontlie's start years: 2026 = the 2026-27 season. Key: BALLDONTLIE_KEY (GitHub secret).
ALL-STAR allows 60 requests/minute, so calls are spaced ~1.05 s apart.
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
DIR = os.path.join(ROOT, "data", "nba_bdl")
BASE = "https://api.balldontlie.io/v1"
GAP = 1.05
SAMPLES = os.path.join(ROOT, "reports", "bdl_samples")
_DT = {"player_id": str, "team_id": str, "game_id": str, "opp_id": str}


class BDLError(RuntimeError):
    pass


def current_season(today: dt.date | None = None) -> int:
    d = today or dt.date.today()
    return d.year if d.month >= 9 else d.year - 1


def get(path: str, params: list[tuple[str, str]] | None = None) -> dict:
    key = os.environ.get("BALLDONTLIE_KEY", "").strip()
    if not key:
        raise BDLError("BALLDONTLIE_KEY not set")
    url = f"{BASE}/{path}" + ("?" + urllib.parse.urlencode(params) if params else "")
    for i in range(5):
        time.sleep(GAP)
        req = urllib.request.Request(url, headers={"Authorization": key, "Accept": "application/json",
                                                   "User-Agent": "BettingDesk/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < 4:
                time.sleep(10 * (i + 1))
                continue
            raise BDLError(f"HTTP {e.code} on {path}")
        except Exception as e:
            if i < 4:
                time.sleep(3 * (i + 1))
                continue
            raise BDLError(f"{path}: {e}")
    raise BDLError(f"{path}: retries exhausted")


def paginate(path: str, params: list[tuple[str, str]], sample: str | None = None, max_pages: int = 2000) -> list[dict]:
    out, cursor, pages = [], None, 0
    while pages < max_pages:
        p = list(params) + [("per_page", "100")] + ([("cursor", str(cursor))] if cursor else [])
        js = get(path, p)
        if sample and pages == 0:
            os.makedirs(SAMPLES, exist_ok=True)
            json.dump({"data": (js.get("data") or [])[:3], "meta": js.get("meta")},
                      open(os.path.join(SAMPLES, f"{sample}.json"), "w"), indent=1)
        out += js.get("data") or []
        cursor = (js.get("meta") or {}).get("next_cursor")
        pages += 1
        if not cursor:
            break
    return out


def _min(v) -> float:
    """balldontlie minutes come as '34', '34:12' or ''."""
    if v in (None, ""):
        return 0.0
    s = str(v)
    if ":" in s:
        m, sec = s.split(":")[:2]
        try:
            return int(m) + int(sec) / 60
        except ValueError:
            return 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def teams() -> list[dict]:
    path = os.path.join(DIR, "teams.json")
    if os.path.exists(path):
        return json.load(open(path))
    js = get("teams")
    rows = [t for t in js.get("data", []) if t.get("conference") and t.get("id", 99) <= 30]
    os.makedirs(DIR, exist_ok=True)
    json.dump(rows, open(path, "w"), indent=1)
    return rows


def load_games(season: int) -> pd.DataFrame:
    rows = []
    for g in paginate("games", [("seasons[]", str(season))], sample=f"games-{season}"):
        rows.append({"game_id": str(g["id"]), "date": (g.get("date") or "")[:10], "season": g.get("season"),
                     "status": g.get("status"), "postseason": bool(g.get("postseason")),
                     "home_id": str(g["home_team"]["id"]), "home": g["home_team"]["abbreviation"],
                     "away_id": str(g["visitor_team"]["id"]), "away": g["visitor_team"]["abbreviation"],
                     "home_score": g.get("home_team_score"), "away_score": g.get("visitor_team_score"),
                     "datetime": g.get("datetime")})
    df = pd.DataFrame(rows)
    os.makedirs(DIR, exist_ok=True)
    df.to_csv(os.path.join(DIR, f"games-{season}.csv.gz"), index=False)
    return df


def _stat_row(s: dict) -> dict:
    g, p, t = s.get("game") or {}, s.get("player") or {}, s.get("team") or {}
    tid = str(t.get("id"))
    home = str(g.get("home_team_id")) == tid
    return {"game_id": str(g.get("id")), "date": (g.get("date") or "")[:10], "season": g.get("season"),
            "team_id": tid, "team": t.get("abbreviation"),
            "opp_id": str(g.get("visitor_team_id") if home else g.get("home_team_id")), "home": int(home),
            "player_id": str(p.get("id")), "player": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
            "pos": p.get("position") or "", "min": round(_min(s.get("min")), 2),
            **{k: s.get(k) for k in ("pts", "reb", "ast", "stl", "blk", "turnover", "pf", "fgm", "fga", "fg3m",
                                     "fg3a", "ftm", "fta", "oreb", "dreb")}}


def load_stats(season: int, dates: list[str] | None = None) -> pd.DataFrame:
    """Full season (dates None) or just the given dates, merged into stats-<season>.csv.gz."""
    params = [("seasons[]", str(season))] + [("dates[]", d) for d in (dates or [])]
    rows = [_stat_row(s) for s in paginate("stats", params, sample=f"stats-{season}")]
    new = pd.DataFrame(rows)
    path = os.path.join(DIR, f"stats-{season}.csv.gz")
    if dates and os.path.exists(path):
        new = pd.concat([pd.read_csv(path, dtype=_DT), new], ignore_index=True)
    if len(new):
        new = new.drop_duplicates(["game_id", "player_id"], keep="last").sort_values(["date", "game_id"])
        os.makedirs(DIR, exist_ok=True)
        new.to_csv(path, index=False)
    return new


def load_injuries() -> list[dict]:
    rows = []
    for r in paginate("player_injuries", [], sample="injuries"):
        p = r.get("player") or {}
        rows.append({"player_id": str(p.get("id")), "player": f"{p.get('first_name', '')} {p.get('last_name', '')}".strip(),
                     "team_id": str(p.get("team_id")), "pos": p.get("position"), "status": r.get("status"),
                     "return_date": r.get("return_date"), "description": r.get("description")})
    os.makedirs(DIR, exist_ok=True)
    json.dump({"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "injuries": rows},
              open(os.path.join(DIR, "injuries.json"), "w"), indent=1)
    return rows


def update(today: dt.date | None = None, backfill: bool = False) -> dict:
    """Daily: this season's games, the last 3 days of stats, injuries. Backfill: last season + this season in full."""
    today = today or dt.date.today()
    cur = current_season(today)
    rep = {"season": cur}
    teams()
    seasons = [cur - 1, cur] if backfill else [cur]
    for s in seasons:
        rep[f"games_{s}"] = len(load_games(s))
        if backfill or not os.path.exists(os.path.join(DIR, f"stats-{s}.csv.gz")):
            rep[f"stats_{s}"] = len(load_stats(s))
        else:
            days = [(today - dt.timedelta(days=i)).isoformat() for i in range(1, 4)]
            rep[f"stats_{s}"] = len(load_stats(s, days))
    rep["injuries"] = len(load_injuries())
    return rep


def games(season: int | None = None) -> pd.DataFrame:
    import glob
    files = [os.path.join(DIR, f"games-{season}.csv.gz")] if season else sorted(glob.glob(os.path.join(DIR, "games-*.csv.gz")))
    return pd.concat([pd.read_csv(f, dtype=_DT) for f in files if os.path.exists(f)], ignore_index=True)


def stats(season: int | None = None) -> pd.DataFrame:
    import glob
    files = [os.path.join(DIR, f"stats-{season}.csv.gz")] if season else sorted(glob.glob(os.path.join(DIR, "stats-*.csv.gz")))
    return pd.concat([pd.read_csv(f, dtype=_DT) for f in files if os.path.exists(f)], ignore_index=True)


def injuries() -> list[dict]:
    path = os.path.join(DIR, "injuries.json")
    return json.load(open(path))["injuries"] if os.path.exists(path) else []
