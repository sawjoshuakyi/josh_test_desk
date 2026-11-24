"""Probe the paid-data candidates with the keys in GitHub secrets and write reports/data_probe.{json,md}.

API-Football (API_FOOTBALL_KEY): account status, per-league coverage flags, and one recent finished fixture per
target league checked for corners, shots on target and per-player shots on target.
balldontlie (BALLDONTLIE_KEY): which NBA endpoints the key's tier can reach.
Free tiers are rate limited (API-Football 10/min, balldontlie 5/min), so calls are spaced out. Keys are never printed.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
AF = "https://v3.football.api-sports.io"
BDL = "https://api.balldontlie.io/v1"

# API-Football league ids (names are checked against the API's own /leagues answer in the report)
TARGETS = {
    39: "Premier League", 140: "La Liga", 135: "Serie A", 78: "Bundesliga", 61: "Ligue 1",
    2: "UEFA Champions League", 3: "UEFA Europa League", 848: "UEFA Conference League", 253: "MLS",
    40: "Championship", 41: "League One", 42: "League Two", 79: "2. Bundesliga", 136: "Serie B",
    141: "Segunda Division", 62: "Ligue 2", 88: "Eredivisie", 94: "Primeira Liga", 203: "Super Lig",
    179: "Scottish Premiership", 144: "Belgian Pro League", 197: "Greek Super League",
    218: "Austrian Bundesliga", 103: "Eliteserien", 262: "Liga MX", 71: "Brasileirao", 128: "Argentina Liga Profesional",
}


def get(url: str, headers: dict, gap: float) -> tuple[int, dict | None, str]:
    time.sleep(gap)
    req = urllib.request.Request(url, headers={**headers, "Accept": "application/json", "User-Agent": "desk-probe"})
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            return r.status, json.loads(r.read().decode()), ""
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        return e.code, None, body
    except Exception as e:  # network
        return 0, None, str(e)[:300]


def probe_api_football(key: str) -> dict:
    h = {"x-apisports-key": key}
    out: dict = {"leagues": {}}
    code, js, err = get(f"{AF}/status", h, 0)
    out["status_http"] = code
    if js:
        resp = js.get("response") or {}
        out["account"] = {"plan": (resp.get("subscription") or {}).get("plan"),
                          "active": (resp.get("subscription") or {}).get("active"),
                          "requests": resp.get("requests")}
        out["status_errors"] = js.get("errors")
    else:
        out["status_error"] = err
        return out
    code, js, err = get(f"{AF}/leagues?current=true", h, 6.5)
    cov = {}
    for item in (js or {}).get("response", []):
        lid = item["league"]["id"]
        if lid in TARGETS:
            season = next((s for s in item.get("seasons", []) if s.get("current")), None) or {}
            c = season.get("coverage") or {}
            f = c.get("fixtures") or {}
            cov[lid] = {"name": item["league"]["name"], "country": item["country"]["name"], "season": season.get("year"),
                        "flags": {k: f.get(k) for k in ("events", "lineups", "statistics_fixtures", "statistics_players")}
                        | {k: c.get(k) for k in ("injuries", "players", "odds")}}
    out["leagues_errors"] = (js or {}).get("errors") or err
    sample_ids: dict[int, int] = {}
    for lid in TARGETS:
        info = cov.get(lid, {"name": TARGETS[lid], "missing_from_current": True})
        out["leagues"][lid] = info
        code, js, err = get(f"{AF}/fixtures?league={lid}&last=3", h, 6.5)
        errs = (js or {}).get("errors")
        if errs:
            info["fixtures_error"] = errs
            continue
        done = [f for f in (js or {}).get("response", []) if f["fixture"]["status"]["short"] in ("FT", "AET", "PEN")]
        if done:
            sample_ids[lid] = done[0]["fixture"]["id"]
            info["sample"] = f"{done[0]['teams']['home']['name']} v {done[0]['teams']['away']['name']} {done[0]['fixture']['date'][:10]}"
        else:
            info["fixtures_error"] = err or "no finished fixture returned"
    ids = list(sample_ids.items())
    for i in range(0, len(ids), 20):
        chunk = ids[i:i + 20]
        code, js, err = get(f"{AF}/fixtures?ids=" + "-".join(str(f) for _, f in chunk), h, 6.5)
        by_fix = {f["fixture"]["id"]: f for f in (js or {}).get("response", [])}
        for lid, fid in chunk:
            f = by_fix.get(fid)
            info = out["leagues"][lid]
            if not f:
                info["stats_error"] = (js or {}).get("errors") or err or "fixture not returned"
                continue
            stats = {s["type"]: s["value"] for t in f.get("statistics", []) for s in t.get("statistics", [])}
            players = [p for t in f.get("players", []) for p in t.get("players", [])]
            sot = [((p["statistics"] or [{}])[0].get("shots") or {}).get("on") for p in players]
            info["check"] = {
                "corners": "Corner Kicks" in stats and stats["Corner Kicks"] is not None,
                "shots_on_target": "Shots on Goal" in stats and stats["Shots on Goal"] is not None,
                "xg": "expected_goals" in stats,
                "player_rows": len(players),
                "player_sot_filled": sum(1 for v in sot if v is not None),
                "minutes_filled": sum(1 for p in players if ((p["statistics"] or [{}])[0].get("games") or {}).get("minutes")),
            }
    code, js, err = get(f"{AF}/status", h, 6.5)
    if js:
        out["requests_after"] = (js.get("response") or {}).get("requests")
    return out


def probe_balldontlie(key: str) -> dict:
    h = {"Authorization": key}
    day = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    tests = {
        "teams (free)": f"{BDL}/teams",
        "games (free)": f"{BDL}/games?dates[]={day}",
        "game player stats (ALL-STAR)": f"{BDL}/stats?dates[]={day}&per_page=5",
        "player injuries (ALL-STAR)": f"{BDL}/player_injuries?per_page=5",
        "box scores (GOAT)": f"{BDL}/box_scores?date={day}",
        "season averages (GOAT)": f"{BDL}/season_averages?season=2025&player_ids[]=237",
    }
    out = {"date_tested": day}
    for i, (name, url) in enumerate(tests.items()):
        code, js, err = get(url, h, 0 if i == 0 else 13)
        n = len((js or {}).get("data", [])) if js else None
        out[name] = {"http": code, "rows": n, "error": None if js else err[:150]}
    return out


def md(res: dict) -> str:
    L = [f"# Data probe — {res['ran_at']}", ""]
    af = res.get("api_football")
    if af is None:
        L += ["**API-Football:** API_FOOTBALL_KEY not set.", ""]
    else:
        L += [f"**API-Football:** HTTP {af.get('status_http')} · account {af.get('account')} · after run {af.get('requests_after')}", ""]
        L += ["| League | API name | Season | Stats flag | Player flag | Sample | Corners | SOT | Player SOT rows | Error |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for lid, i in af.get("leagues", {}).items():
            fl = i.get("flags", {}); c = i.get("check", {})
            L.append(f"| {TARGETS[int(lid)]} | {i.get('name')} ({i.get('country', '')}) | {i.get('season')} | "
                     f"{fl.get('statistics_fixtures')} | {fl.get('statistics_players')} | {i.get('sample', '')} | "
                     f"{c.get('corners', '')} | {c.get('shots_on_target', '')} | "
                     f"{c.get('player_sot_filled', '')}/{c.get('player_rows', '')} | "
                     f"{i.get('fixtures_error') or i.get('stats_error') or ''} |")
        L.append("")
    bd = res.get("balldontlie")
    if bd is None:
        L += ["**balldontlie:** BALLDONTLIE_KEY not set."]
    else:
        L += [f"**balldontlie** (tested {bd.pop('date_tested', '')}):", ""]
        L += [f"- {k}: HTTP {v['http']}, rows {v['rows']}{' — ' + v['error'] if v['error'] else ''}" for k, v in bd.items()]
    return "\n".join(L) + "\n"


def main():
    res = {"ran_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    k = os.environ.get("API_FOOTBALL_KEY", "").strip()
    res["api_football"] = probe_api_football(k) if k else None
    k = os.environ.get("BALLDONTLIE_KEY", "").strip()
    res["balldontlie"] = probe_balldontlie(k) if k else None
    os.makedirs(os.path.join(ROOT, "reports"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "reports", "data_probe.json"), "w"), indent=1, default=str)
    text = md(json.loads(json.dumps(res, default=str)))
    open(os.path.join(ROOT, "reports", "data_probe.md"), "w").write(text)
    print(text)


if __name__ == "__main__":
    sys.exit(main())
