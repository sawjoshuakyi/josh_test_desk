"""Today's NBA slate from ESPN: teams, market spread/total, injury report, and model projections per roster."""
from __future__ import annotations

import datetime as dt
import json
import unicodedata
import urllib.request

OUT_STATUSES = ("out", "doubtful")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    for suf in (" jr.", " jr", " sr.", " iii", " ii", " iv"):
        s = s.replace(suf, "")
    return "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()


def espn(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BettingDesk/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def slate(day: dt.date) -> list[dict]:
    sb = espn(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={day:%Y%m%d}")
    games = []
    for ev in sb.get("events", []):
        comp = ev["competitions"][0]
        teams = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        odds = (comp.get("odds") or [{}])[0]
        details, total, spread_for = (odds.get("details") or ""), odds.get("overUnder"), {}
        if details and " " in details:
            fav, num = details.split(" ", 1)
            try:
                n = abs(float(num))
                spread_for = {t: (-n if t == fav else n) for t in teams.values()}
            except ValueError:
                pass
        injured = {}
        try:
            summ = espn(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={ev['id']}")
            for tb in summ.get("injuries", []):
                for inj in tb.get("injuries", []):
                    injured[norm(inj.get("athlete", {}).get("displayName", ""))] = inj.get("status", "")
        except Exception:
            pass
        games.append({"event": ev["shortName"], "espn_id": ev["id"], "start": ev["date"], "teams": teams,
                      "state": comp.get("status", {}).get("type", {}).get("state"),
                      "spread": spread_for, "total": total, "injury_report": injured})
    return games


def team_projections(proj, hist, team: str, injured: dict, spread, total) -> list[tuple[dict, dict]]:
    """[(projection, summary_row)] for the team's recent rotation, excluding players listed Out/Doubtful."""
    tg = hist[hist.team == team]
    last_ids = tg.drop_duplicates("game_id").game_id.tolist()[-10:]
    roster = tg[tg.game_id.isin(last_ids)].drop_duplicates("player_id", keep="last")
    available = {r.player_id for r in roster.itertuples() if injured.get(norm(r.player), "").lower() not in OUT_STATUSES}
    out = []
    for r in roster.itertuples():
        if r.player_id not in available:
            continue
        pr = proj.project(r.player_id, team, available, None, spread, total)
        if pr is None or pr["minutes"] < 8:
            continue
        row = {"player": r.player, "player_id": r.player_id, "team": team,
               "status": injured.get(norm(r.player), "") or "active", "minutes": round(pr["minutes"], 1),
               **{k: round(v, 2) for k, v in pr["means"].items()},
               "pra": round(sum(pr["means"][s] for s in ("pts", "reb", "ast")), 2)}
        out.append((pr, row))
    return out
