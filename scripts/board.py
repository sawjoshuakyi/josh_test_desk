"""Daily model board: fair prices and edges for today's NBA props (pm) and tennis matches (am).

Usage: python3 scripts/board.py pm|am [YYYY-MM-DD]
Writes boards/<date>-<session>.json and .md, and appends rows to data/desk.db.
Without ODDS_API_KEY it still writes model projections (no prices/edges).
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from desk import config, db, pricing
from desk.odds import OddsAPI, OddsAPIError, flatten, pair_two_way

NBA_MARKET_STAT = {"player_points": "pts", "player_rebounds": "reb", "player_assists": "ast",
                   "player_threes": "threes", "player_points_rebounds_assists": "pra",
                   "player_points_alternate": "pts", "player_rebounds_alternate": "reb",
                   "player_assists_alternate": "ast"}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    for suf in (" jr.", " jr", " sr.", " iii", " ii", " iv"):
        s = s.replace(suf, "")
    return "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()


def espn(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BettingDesk/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def best_side(book_prices: dict, side: str):
    best = None
    for book in config.BET_BOOKS:
        price = book_prices.get(book, {}).get(side)
        if price is not None and (best is None or pricing.american_to_decimal(price) > pricing.american_to_decimal(best[1])):
            best = (book, price)
    return best


def fair_prob(book_prices: dict, side: str, other: str):
    """No-vig probability of `side`: Pinnacle if it has both sides, else the average of DK/FD."""
    pin = book_prices.get(config.SHARP_BOOK, {})
    if side in pin and other in pin:
        return pricing.fair_two_way(pin[side], pin[other]), "pinnacle"
    vals = [pricing.fair_two_way(bp[side], bp[other]) for b, bp in book_prices.items()
            if b in config.BET_BOOKS and side in bp and other in bp]
    return (sum(vals) / len(vals), "dk/fd") if vals else (None, None)


def low_credits(api) -> bool:
    try:
        return api.remaining is not None and float(api.remaining) < config.MIN_CREDITS
    except ValueError:
        return False


def et_date(iso: str) -> dt.date:
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(config.ET).date()


# ------------------------------------------------------------------ game lines (any sport)
def market_board(day: dt.date, api: OddsAPI, sports: list[str], tag: str) -> list[dict]:
    """Where DK/FD pay more than Pinnacle's no-vig fair price on moneylines, spreads and totals."""
    out, con = [], db.connect()
    for sport in sports:
        if low_credits(api):
            break
        try:
            payload = api.game_odds(sport, markets=config.GAME_MARKETS)
        except OddsAPIError as err:
            print("odds error", sport, err)
            continue
        payload = [e for e in payload if et_date(e["commence_time"]) == day]
        rows = flatten(payload, "game", sport)
        db.insert_many(con, "odds_snapshots", rows)
        db.archive(rows, f"open-{tag}")
        names = {e["id"]: f'{e["away_team"]} @ {e["home_team"]}' for e in payload}
        starts = {e["id"]: e["commence_time"] for e in payload}
        for (eid, market, _player, point), books in pair_two_way(rows).items():
            pin = books.get(config.SHARP_BOOK, {})
            n_sides = 3 if (market == "h2h" and sport.startswith("soccer")) else 2
            if len(pin) != n_sides:
                continue
            fair = pricing.fair_multi(pin)
            for side, p in fair.items():
                best = best_side(books, side)
                if best is None:
                    continue
                line = None
                if market == "spreads":
                    line = next((r["point"] for r in rows if r["event_id"] == eid and r["market"] == market
                                 and r["side"] == side and r["book"] == best[0] and abs(r["point"]) == point), None)
                elif market == "totals":
                    line = point
                ev_edge = pricing.edge(p, best[1])
                out.append({"sport": sport, "event_id": eid, "event": names.get(eid), "start": starts.get(eid), "market": market,
                            "side": side, "line": line, "fair_prob": round(p, 4), "fair_price": round(pricing.prob_to_american(p)),
                            "pin": pin.get(side), "dk": books.get("draftkings", {}).get(side),
                            "fd": books.get("fanduel", {}).get(side), "best_book": best[0], "best_price": best[1],
                            "edge": round(ev_edge, 4), "flag": ev_edge >= config.MARKET_EDGE_FLAG,
                            "kelly_usd": pricing.kelly_stake(p, best[1])})
    out.sort(key=lambda r: r["edge"], reverse=True)
    return out


# ------------------------------------------------------------------ NBA
def nba_board(day: dt.date, api: OddsAPI | None) -> dict:
    from desk.nba import data as nba_data
    from desk.nba.model import Projector

    nba_data.update(day - dt.timedelta(days=1))
    box = pd.read_csv(nba_data.BOX_CSV, dtype={"game_id": str, "player_id": str})
    hist = box[box.date < day.isoformat()]
    proj = Projector(hist)
    from desk.nba.live import slate, team_projections
    games, projections, by_name = [], [], {}
    for g in slate(day):
        games.append({k: g[k] for k in ("event", "espn_id", "start", "spread", "total", "injury_report")})
        for team in g["teams"].values():
            for pr, row in team_projections(proj, hist, team, g["injury_report"], g["spread"].get(team), g["total"]):
                row = {"event": g["event"], **row}
                projections.append(row)
                by_name[norm(row["player"])] = (pr, row)
    props = []
    credits = None
    if api:
        events = api.events("basketball_nba")
        today = [e for e in events if e["commence_time"][:10] in (day.isoformat(), (day + dt.timedelta(days=1)).isoformat())
                 and dt.datetime.fromisoformat(e["commence_time"].replace("Z", "+00:00")).astimezone(config.ET).date() == day]
        con = db.connect()
        for e in today:
            if low_credits(api):
                print("credit guard: stopping prop calls")
                break
            try:
                payload = api.event_odds("basketball_nba", e["id"], config.NBA_PROP_MARKETS + config.NBA_ALT_MARKETS)
            except OddsAPIError as err:
                print("odds error", err)
                continue
            rows = flatten(payload, "props", "basketball_nba")
            db.insert_many(con, "odds_snapshots", rows)
            db.archive(rows, "open-nba-props")
            for (eid, market, player, point), books in pair_two_way(rows).items():
                stat = NBA_MARKET_STAT.get(market)
                hit = by_name.get(norm(player or ""))
                if not stat or hit is None or point is None:
                    continue
                pr, prow = hit
                k = math.floor(point) + 1
                p_over = proj.prob_at_least(pr, stat, k)
                for side, other, p_model in (("Over", "Under", p_over), ("Under", "Over", 1 - p_over)):
                    best = best_side(books, side)
                    if best is None:
                        continue
                    fair, src = fair_prob(books, side, other)
                    edge = pricing.edge(p_model, best[1])
                    props.append({
                        "event_id": eid, "start": e["commence_time"], "event": f'{e["away_team"]} @ {e["home_team"]}', "player": player, "team": prow["team"],
                        "market": market, "stat": stat, "line": point, "side": side, "alt": market.endswith("alternate"),
                        "model_mean": prow["pra"] if stat == "pra" else prow.get(stat), "model_prob": round(p_model, 4),
                        "fair_market_prob": round(fair, 4) if fair is not None else None, "fair_source": src,
                        "dk": books.get("draftkings", {}).get(side), "fd": books.get("fanduel", {}).get(side),
                        "pin": books.get("pinnacle", {}).get(side), "best_book": best[0], "best_price": best[1],
                        "edge": round(edge, 4), "model_vs_market": round(p_model - fair, 4) if fair is not None else None,
                        "kelly_usd": pricing.kelly_stake(p_model, best[1]), "player_status": prow["status"],
                    })
        credits = api.remaining
    props.sort(key=lambda r: r["edge"], reverse=True)
    return {"games": games, "projections": projections, "props": props, "credits_remaining": credits}


# ------------------------------------------------------------------ tennis
def tennis_board(day: dt.date, api: OddsAPI | None) -> dict:
    from desk.tennis import data as tdata
    from desk.tennis.elo import build

    tdata.update(day)
    elos = build(tdata.all_matches())
    lookup = tdata.surface_lookup()
    now = dt.datetime.now(dt.timezone.utc)
    matches = []
    for tour in ("atp", "wta"):
        sb = espn(f"https://site.api.espn.com/apis/site/v2/sports/tennis/{tour}/scoreboard?dates={day:%Y%m%d}")
        for ev in sb.get("events", []):
            surface = tdata.guess_surface(ev.get("name", ""), day, lookup)
            for g in ev.get("groupings", []):
                g_tour = tdata.grouping_tour(g, tour)
                if g_tour is None:
                    continue
                for c in g.get("competitions", []):
                    if c.get("status", {}).get("type", {}).get("state") != "pre":
                        continue
                    try:
                        start = dt.datetime.fromisoformat(c.get("date", "").replace("Z", "+00:00"))
                    except ValueError:
                        continue
                    if not (now - dt.timedelta(hours=1) <= start <= now + dt.timedelta(hours=26)):
                        continue
                    names = [tdata._singles_name(x) for x in c.get("competitors", [])]
                    if len(names) != 2 or None in names:
                        continue
                    if any(m["espn_id"] == c.get("id") for m in matches):
                        continue  # Slams appear under both tours
                    elo = elos[g_tour]
                    a, b = names
                    slam = any(x in ev.get("name", "") for x in ("Australian Open", "Roland Garros", "Wimbledon", "US Open"))
                    p = elo.predict(a, b, surface, 5 if slam and g_tour == "atp" else 3)
                    matches.append({"espn_id": c.get("id"), "tour": g_tour, "tournament": ev.get("name"), "surface": surface, "start": c.get("date"),
                                    "player_a": a, "player_b": b, "p_a": round(p, 4), "elo_matches_a": elo.n[a],
                                    "elo_matches_b": elo.n[b], "low_sample": min(elo.n[a], elo.n[b]) < 15})
    priced = []
    credits = None
    if api and matches:
        con = db.connect()
        sports = [s for s in api.sports() if s.get("group") == "Tennis" and s.get("active")]
        idx = {}
        for m in matches:
            idx[(norm(m["player_a"]), norm(m["player_b"]))] = (m, False)
            idx[(norm(m["player_b"]), norm(m["player_a"]))] = (m, True)
        for s in sports:
            try:
                payload = api.game_odds(s["key"], markets=("h2h",))
            except OddsAPIError as err:
                print("odds error", err)
                continue
            payload = [ev for ev in payload if (norm(ev.get("home_team", "")), norm(ev.get("away_team", ""))) in idx]
            rows = flatten(payload, "game", s["key"])
            db.insert_many(con, "odds_snapshots", rows)
            db.archive(rows, "open-tennis")
            for ev in payload:
                key = (norm(ev.get("home_team", "")), norm(ev.get("away_team", "")))
                if key not in idx:
                    continue
                m, flipped = idx[key]
                books = {}
                for bm in ev.get("bookmakers", []):
                    for mk in bm.get("markets", []):
                        if mk["key"] == "h2h":
                            books[bm["key"]] = {o["name"]: o["price"] for o in mk["outcomes"]}
                for player, p_model in ((m["player_a"], m["p_a"]), (m["player_b"], 1 - m["p_a"])):
                    opp = m["player_b"] if player == m["player_a"] else m["player_a"]
                    pname = next((n for n in (books.get(config.SHARP_BOOK) or next(iter(books.values()), {})) if norm(n) == norm(player)), None)
                    oname = next((n for n in (books.get(config.SHARP_BOOK) or next(iter(books.values()), {})) if norm(n) == norm(opp)), None)
                    if not pname or not oname:
                        continue
                    best = best_side(books, pname)
                    if best is None:
                        continue
                    fair, src = fair_prob(books, pname, oname)
                    priced.append({"event_id": ev["id"], "sport": s["key"], "start": ev.get("commence_time"), "tour": m["tour"], "tournament": m["tournament"], "surface": m["surface"], "player": player,
                                   "opponent": opp, "model_prob": round(p_model, 4),
                                   "fair_market_prob": round(fair, 4) if fair is not None else None, "fair_source": src,
                                   "dk": books.get("draftkings", {}).get(pname), "fd": books.get("fanduel", {}).get(pname),
                                   "pin": books.get("pinnacle", {}).get(pname), "best_book": best[0], "best_price": best[1],
                                   "edge": round(pricing.edge(p_model, best[1]), 4),
                                   "model_vs_market": round(p_model - fair, 4) if fair is not None else None,
                                   "kelly_usd": pricing.kelly_stake(p_model, best[1]), "low_sample": m["low_sample"]})
        credits = api.remaining
    priced.sort(key=lambda r: r["edge"], reverse=True)
    return {"matches": matches, "priced": priced, "credits_remaining": credits}


# ------------------------------------------------------------------ output
def to_markdown(board: dict) -> str:
    lines = [f"# Model board — {board['date']} {board['session'].upper()}",
             f"Generated {board['generated_at']} · odds: {board['odds_source']}", ""]
    if "nba" in board:
        props = board["nba"]["props"]
        lines += ["## NBA props with the largest model edge", "",
                  "| Player | Market | Side | Line | Model | Fair mkt | Best | Edge | Kelly $ |", "|---|---|---|---|---|---|---|---|---|"]
        for r in [p for p in props if p["edge"] > 0][:30]:
            lines.append(f"| {r['player']} | {r['stat']}{' (alt)' if r['alt'] else ''} | {r['side']} | {r['line']} | "
                         f"{r['model_prob']:.0%} | {(r['fair_market_prob'] or 0):.0%} | {r['best_price']:+.0f} {r['best_book']} | "
                         f"{r['edge']:+.1%} | {r['kelly_usd']:.0f} |")
        if not props:
            lines += ["", "_No prices (no odds key or no markets yet)._"]
        lines += ["", "## NBA projections (model means; injuries from ESPN at run time)", "",
                  "| Game | Player | Status | Min | Pts | Reb | Ast | 3PM | PRA |", "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(board["nba"]["projections"], key=lambda r: (r["event"], -r["minutes"])):
            if r["minutes"] >= 20:
                lines.append(f"| {r['event']} | {r['player']} | {r['status']} | {r['minutes']} | {r['pts']} | {r['reb']} | "
                             f"{r['ast']} | {r.get('threes', 0)} | {r['pra']} |")
    if "tennis" in board:
        lines += ["", "## Tennis matches", "", "| Player | vs | Model | Fair mkt | Best | Edge |", "|---|---|---|---|---|---|"]
        for r in board["tennis"]["priced"][:30]:
            lines.append(f"| {r['player']} | {r['opponent']} | {r['model_prob']:.0%} | {(r['fair_market_prob'] or 0):.0%} | "
                         f"{r['best_price']:+.0f} {r['best_book']} | {r['edge']:+.1%} |")
        if not board["tennis"]["priced"]:
            lines += [f"| {m['player_a']} | {m['player_b']} | {m['p_a']:.0%}{' (low sample)' if m['low_sample'] else ''} | – | – | – |"
                      for m in board["tennis"]["matches"][:60]]
    for key, title in (("nba_lines", "NBA game lines"), ("nfl_lines", "NFL game lines"), ("soccer_lines", "Soccer game lines")):
        if key in board:
            rows = [r for r in board[key] if r["edge"] > 0][:20]
            lines += ["", f"## {title}: DK/FD price vs Pinnacle no-vig fair", "",
                      "| Event | Market | Side | Line | Fair | Best | Edge |", "|---|---|---|---|---|---|---|"]
            lines += [f"| {r['event']} | {r['market']} | {r['side']} | {'' if r['line'] is None else r['line']} | "
                      f"{r['fair_price']:+d} | {r['best_price']:+.0f} {r['best_book']} | {r['edge']:+.1%}{' ⭐' if r['flag'] else ''} |"
                      for r in rows]
            if not rows:
                lines.append("| _none positive_ | | | | | | |")
    return "\n".join(lines) + "\n"


def main():
    session = sys.argv[1] if len(sys.argv) > 1 else "pm"
    day = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else config.et_today()
    try:
        api = OddsAPI()
    except OddsAPIError:
        api = None
    board = {"date": day.isoformat(), "session": session,
             "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "odds_source": "the-odds-api" if api else "none (model only)"}
    if session == "pm":
        board["nba"] = nba_board(day, api)
        if api:
            board["nba_lines"] = market_board(day, api, ["basketball_nba"], "nba-lines")
            board["nfl_lines"] = market_board(day, api, ["americanfootball_nfl"], "nfl-lines")
    elif session == "nfl":
        if api:
            board["nfl_lines"] = market_board(day, api, ["americanfootball_nfl"], "nfl-lines")
    else:
        board["tennis"] = tennis_board(day, api)
        if api:
            board["soccer_lines"] = market_board(day, api, config.SOCCER_SPORTS, "soccer-lines")
    board["credits_remaining"] = api.remaining if api else None
    os.makedirs(os.path.join(ROOT, "boards"), exist_ok=True)
    base = os.path.join(ROOT, "boards", f"{day}-{session}")
    json.dump(board, open(base + ".json", "w"), indent=1, default=str)
    open(base + ".md", "w").write(to_markdown(board))
    con = db.connect()
    created = board["generated_at"]
    rows = []
    for r in board.get("nba", {}).get("props", []):
        rows.append({"created_at": created, "game_date": day.isoformat(), "session": session, "sport": "nba", "event": r["event"],
                     "player": r["player"], "market": r["market"], "side": r["side"], "line": r["line"],
                     "model_prob": r["model_prob"], "fair_market_prob": r["fair_market_prob"], "dk_price": r["dk"],
                     "fd_price": r["fd"], "pin_price": r["pin"], "best_book": r["best_book"], "best_price": r["best_price"],
                     "edge": r["edge"], "kelly_stake": r["kelly_usd"], "model": "nba-v1"})
    for r in board.get("tennis", {}).get("priced", []):
        rows.append({"created_at": created, "game_date": day.isoformat(), "session": session, "sport": "tennis",
                     "event": f"{r['player']} v {r['opponent']}", "player": r["player"], "market": "h2h", "side": "win",
                     "line": None, "model_prob": r["model_prob"], "fair_market_prob": r["fair_market_prob"], "dk_price": r["dk"],
                     "fd_price": r["fd"], "pin_price": r["pin"], "best_book": r["best_book"], "best_price": r["best_price"],
                     "edge": r["edge"], "kelly_stake": r["kelly_usd"], "model": "tennis-elo-v1"})
    db.insert_many(con, "board", rows)
    print(f"board written: {base}.json ({len(rows)} priced rows)")


if __name__ == "__main__":
    main()
