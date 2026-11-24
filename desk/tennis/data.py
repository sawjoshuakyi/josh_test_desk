"""Tennis results: the archived match history plus live ESPN results since the archive ends.

data/tennis/matches.csv.gz  - ATP/WTA tour-level singles 2010 to May 2026 (Sackmann archive mirror,
                              CC BY-NC-SA 4.0: personal, non-commercial use).
data/tennis/live.csv        - singles results scraped daily from ESPN's public scoreboard.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import time
import urllib.request

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
ARCHIVE = os.path.join(ROOT, "data", "tennis", "matches.csv.gz")
LIVE = os.path.join(ROOT, "data", "tennis", "live.csv")
SB = "https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={d}"
FIELDS = ["tour", "tourney_date", "tourney_name", "tourney_level", "surface", "round", "best_of",
          "match_num", "winner_name", "loser_name", "winner_rank", "loser_rank", "score", "espn_id"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BettingDesk/1.0"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.load(r)
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


def surface_lookup() -> dict:
    """Most common surface for each tournament name in the archive."""
    df = pd.read_csv(ARCHIVE, usecols=["tourney_name", "surface"])
    return df.groupby("tourney_name").surface.agg(lambda s: s.mode().iat[0]).to_dict()


def guess_surface(name: str, day: dt.date, lookup: dict) -> str:
    if name in lookup:
        return lookup[name]
    for k, v in lookup.items():
        if k and (k in name or name in k):
            return v
    if dt.date(day.year, 6, 8) <= day <= dt.date(day.year, 7, 14):
        return "Grass"
    if dt.date(day.year, 4, 1) <= day <= dt.date(day.year, 6, 7):
        return "Clay"
    return "Hard"


def _singles_name(c) -> str | None:
    a = c.get("athlete") or {}
    if a.get("displayName"):
        return a["displayName"]
    roster = c.get("roster") or {}
    if len(roster.get("athletes", [])) == 1:
        return roster["athletes"][0].get("displayName")
    return None


def grouping_tour(g: dict, default: str) -> str | None:
    """Tour of a singles grouping (Slams list men's and women's draws under both tours), or None if not singles."""
    slug = (g.get("grouping", {}).get("slug", "") + " " + g.get("grouping", {}).get("displayName", "")).lower()
    if "single" not in slug:
        return None
    if "women" in slug:
        return "wta"
    if "men" in slug:
        return "atp"
    return default


def _score(cw: dict, cl: dict, note: str) -> str:
    """Winner-first set scores from ESPN linescores, e.g. '7-6 6-3'; 'W/O' for walkovers, ' RET' appended for retirements."""
    if "walkover" in note.lower():
        return "W/O"
    lw, ll = cw.get("linescores") or [], cl.get("linescores") or []
    sets = [f"{int(a.get('value', 0))}-{int(b.get('value', 0))}" for a, b in zip(lw, ll)]
    out = " ".join(sets) if sets else "completed"
    return out + (" RET" if "ret" in note.lower() else "")


def fetch_day(tour: str, day: dt.date, lookup: dict) -> list[dict]:
    data = _get(SB.format(tour=tour, d=day.strftime("%Y%m%d")))
    rows = []
    for ev in data.get("events", []):
        name = ev.get("name", "")
        slam = any(s in name for s in ("Australian Open", "Roland Garros", "French Open", "Wimbledon", "US Open"))
        for g in ev.get("groupings", []):
            g_tour = grouping_tour(g, tour)
            if g_tour is None:
                continue
            best_of = 5 if slam and g_tour == "atp" else 3
            for c in g.get("competitions", []):
                if not c.get("status", {}).get("type", {}).get("completed"):
                    continue
                comps = c.get("competitors", [])
                if len(comps) != 2:
                    continue
                names = [_singles_name(x) for x in comps]
                if None in names:
                    continue
                win = [i for i, x in enumerate(comps) if x.get("winner")]
                if len(win) != 1:
                    continue
                w, l = win[0], 1 - win[0]
                when = dt.date.fromisoformat((c.get("date") or day.isoformat())[:10])
                note = c.get("status", {}).get("type", {}).get("shortDetail", "")
                rows.append({"tour": g_tour, "tourney_date": int(when.strftime("%Y%m%d")), "tourney_name": name,
                             "tourney_level": "A", "surface": guess_surface(name, when, lookup),
                             "round": (c.get("round") or {}).get("displayName", ""), "best_of": best_of,
                             "match_num": 0, "winner_name": names[w], "loser_name": names[l],
                             "winner_rank": (comps[w].get("curatedRank") or {}).get("current"),
                             "loser_rank": (comps[l].get("curatedRank") or {}).get("current"),
                             "score": _score(comps[w], comps[l], note), "espn_id": c.get("id")})
    return rows


def update(until: dt.date | None = None) -> int:
    until = until or dt.date.today()
    have, start = set(), dt.date(2026, 5, 25)
    if os.path.exists(LIVE):
        live = pd.read_csv(LIVE, dtype={"espn_id": str})
        have = set(live.espn_id.astype(str))
        if len(live):
            start = dt.datetime.strptime(str(int(live.tourney_date.max())), "%Y%m%d").date() - dt.timedelta(days=3)
    lookup = surface_lookup()
    new = []
    day = start
    while day <= until:
        for tour in ("atp", "wta"):
            for r in fetch_day(tour, day, lookup):
                if str(r["espn_id"]) not in have:
                    new.append(r)
                    have.add(str(r["espn_id"]))
        day += dt.timedelta(days=1)
        time.sleep(0.05)
    exists = os.path.exists(LIVE)
    with open(LIVE, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        w.writerows(new)
    return len(new)


def all_matches() -> pd.DataFrame:
    df = pd.read_csv(ARCHIVE)
    if os.path.exists(LIVE):
        live = pd.read_csv(LIVE).drop(columns=["espn_id"], errors="ignore")
        live = live[live.tourney_date > df.tourney_date.max()]
        df = pd.concat([df, live], ignore_index=True)
    return df


if __name__ == "__main__":
    print("new live results:", update())
