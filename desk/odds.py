"""The Odds API client (https://the-odds-api.com, v4).

Credit costs (per The Odds API docs): a featured-odds call costs (#markets x #regions);
a per-event call (player props) costs (#markets x #regions) per event. When `bookmakers`
is given, every 10 bookmakers count as one region. Remaining credits come back in the
x-requests-remaining header, which this client records.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config


class OddsAPIError(RuntimeError):
    pass


class OddsAPI:
    def __init__(self, api_key: str | None = None):
        self.key = api_key or os.environ.get("ODDS_API_KEY", "")
        if not self.key:
            raise OddsAPIError("Set ODDS_API_KEY")
        self.remaining = None
        self.used = None

    def _get(self, path: str, **params):
        params["apiKey"] = self.key
        url = f"{config.ODDS_API_BASE}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "BettingDesk/1.0"})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    self.remaining = r.headers.get("x-requests-remaining")
                    self.used = r.headers.get("x-requests-used")
                    return json.load(r)
            except urllib.error.HTTPError as e:
                body = e.read().decode(errors="replace")[:300]
                if e.code == 429 and attempt < 2:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise OddsAPIError(f"HTTP {e.code}: {body}") from None
        raise OddsAPIError("request failed")

    # ---- discovery
    def sports(self, all_sports: bool = False):
        return self._get("/sports", **({"all": "true"} if all_sports else {}))

    def events(self, sport: str):
        return self._get(f"/sports/{sport}/events")

    # ---- odds
    def game_odds(self, sport: str, markets=("h2h", "spreads", "totals"), books=None):
        return self._get(f"/sports/{sport}/odds", markets=",".join(markets),
                         bookmakers=",".join(books or config.ALL_BOOKS), oddsFormat="american")

    def event_odds(self, sport: str, event_id: str, markets, books=None):
        return self._get(f"/sports/{sport}/events/{event_id}/odds", markets=",".join(markets),
                         bookmakers=",".join(books or config.ALL_BOOKS), oddsFormat="american")

    def historical_game_odds(self, sport: str, when: str, markets=("h2h",), books=None):
        """when: ISO timestamp, e.g. 2026-11-20T23:00:00Z (paid plans only)."""
        return self._get(f"/historical/sports/{sport}/odds", date=when, markets=",".join(markets),
                         bookmakers=",".join(books or config.ALL_BOOKS), oddsFormat="american")


def flatten(payload, kind: str, sport: str) -> list[dict]:
    """Turn an Odds API odds payload (one event dict or a list) into snapshot rows."""
    taken = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    events = payload if isinstance(payload, list) else [payload]
    rows = []
    for ev in events:
        for bm in ev.get("bookmakers", []):
            for mk in bm.get("markets", []):
                for oc in mk.get("outcomes", []):
                    rows.append({
                        "taken_at": taken, "kind": kind, "sport": sport, "event_id": ev.get("id"),
                        "commence": ev.get("commence_time"), "home": ev.get("home_team"),
                        "away": ev.get("away_team"), "book": bm.get("key"), "market": mk.get("key"),
                        "player": oc.get("description"), "side": oc.get("name"),
                        "point": oc.get("point"), "price": oc.get("price"),
                    })
    return rows


def pair_two_way(rows: list[dict]) -> dict:
    """Group snapshot rows into two-way markets.

    Returns {(event_id, market, player, point): {book: {"Over": price, "Under": price}}} for props, and
    {(event_id, market, None, point_or_None): {book: {side_name: price}}} for game markets.
    """
    out: dict = {}
    for r in rows:
        point = r["point"]
        if r["market"] == "spreads" and point is not None:
            point = abs(point)  # both sides of a spread share |line|
        key = (r["event_id"], r["market"], r["player"], point)
        out.setdefault(key, {}).setdefault(r["book"], {})[r["side"]] = r["price"]
    return out
