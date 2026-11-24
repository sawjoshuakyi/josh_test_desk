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
    from desk import facts
    opp_of = {}
    for g in games:
        teams = [t.strip() for t in g["event"].split("@")]
        if len(teams) == 2:
            opp_of[teams[0]], opp_of[teams[1]] = teams[1], teams[0]
    for r in [x for x in props if x["edge"] > 0][:config.FACTS_ROWS]:
        opp = opp_of.get(r["team"])
        r["opponent"] = opp
        r["facts"] = facts.nba_facts(box, r["player"], r["stat"], r["line"], r["side"], day.isoformat()) + \
            (facts.nba_matchup(box, opp, r["stat"], day.isoformat()) if opp else []) + [
            facts.model_bullet(r["model_mean"] or 0, r["model_prob"], r["fair_market_prob"], r["edge"], r["line"],
                               r["side"], r["stat"])]
    return {"games": games, "projections": projections, "props": props, "credits_remaining": credits}


# ------------------------------------------------------------------ NFL
NFL_MARKET_STAT = {"player_receptions": "rec", "player_reception_yds": "rec_yds", "player_rush_yds": "rush_yds",
                   "player_rush_attempts": "rush_att", "player_pass_yds": "pass_yds", "player_pass_attempts": "pass_att",
                   "player_pass_completions": "pass_cmp", "player_pass_tds": "pass_td", "player_anytime_td": "td",
                   "player_receptions_alternate": "rec", "player_reception_yds_alternate": "rec_yds",
                   "player_rush_yds_alternate": "rush_yds", "player_pass_yds_alternate": "pass_yds"}
ESPN_TO_NFLVERSE = {"WSH": "WAS", "LAR": "LA"}
NFL_OUT = ("out", "doubtful", "injured reserve", "ir", "suspended", "physically unable to perform")


def nfl_slate(day: dt.date) -> list[dict]:
    sb = espn(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard?dates={day:%Y%m%d}")
    out = []
    for ev in sb.get("events", []):
        comp = ev["competitions"][0]
        if comp.get("status", {}).get("type", {}).get("state") != "pre":
            continue
        teams = {c["homeAway"]: c["team"]["abbreviation"] for c in comp["competitors"]}
        odds = (comp.get("odds") or [{}])[0]
        spread_for, total = {}, odds.get("overUnder")
        details = odds.get("details") or ""
        if " " in details:
            fav, num = details.split(" ", 1)
            try:
                n = abs(float(num))
                spread_for = {t: (-n if t == fav else n) for t in teams.values()}
            except ValueError:
                pass
        injured = {}
        try:
            summ = espn(f"https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary?event={ev['id']}")
            for tb in summ.get("injuries", []):
                for inj in tb.get("injuries", []):
                    injured[norm(inj.get("athlete", {}).get("displayName", ""))] = inj.get("status", "")
        except Exception:
            pass
        out.append({"event": ev["shortName"], "espn_id": ev["id"], "start": ev["date"], "teams": teams,
                    "spread": spread_for, "total": total, "injury_report": injured})
    return out


def nfl_board(day: dt.date, api: OddsAPI | None) -> dict:
    from desk import facts
    from desk.nfl import data as nfl_data
    from desk.nfl.model import NFLModel, prob_at_least

    slate_games = nfl_slate(day)
    if not slate_games:
        return {"games": [], "projections": [], "props": [], "credits_remaining": None}
    nfl_data.download()
    pg = nfl_data.player_games()
    hist = pg[pg.date < day.isoformat()]
    model = NFLModel(hist)
    games, projections, by_name = [], [], {}
    for g in slate_games:
        games.append({k: g[k] for k in ("event", "espn_id", "start", "spread", "total", "injury_report")})
        for espn_team in g["teams"].values():
            team = ESPN_TO_NFLVERSE.get(espn_team, espn_team)
            regulars = model.team_players(team)
            avail = {p.player_id for p in regulars
                     if g["injury_report"].get(norm(p.name), "").lower() not in NFL_OUT}
            proj = model.project_team(team, avail, g["spread"].get(espn_team), g["total"])
            for pid, pj in proj.items():
                st, m = pj["state"], pj["means"]
                row = {"event": g["event"], "player": st.name, "player_id": pid, "team": espn_team, "pos": st.position,
                       "status": g["injury_report"].get(norm(st.name), "") or "active",
                       "tgt_share": round(st.tgt_share, 3), "car_share": round(st.car_share, 3),
                       **{k: round(v, 2) for k, v in m.items()}}
                if max(m.get("targets", 0), m.get("rush_att", 0), m.get("pass_att", 0)) >= 1.5:
                    projections.append(row)
                    by_name[norm(st.name)] = (pj, row)
    props, credits = [], None
    if api and games:
        events = [e for e in api.events("americanfootball_nfl") if et_date(e["commence_time"]) == day]
        con = db.connect()
        for e in events:
            if low_credits(api):
                print("credit guard: stopping NFL prop calls")
                break
            try:
                payload = api.event_odds("americanfootball_nfl", e["id"], config.NFL_PROP_MARKETS + config.NFL_ALT_MARKETS)
            except OddsAPIError as err:
                print("odds error", err)
                continue
            rows = flatten(payload, "props", "americanfootball_nfl")
            db.insert_many(con, "odds_snapshots", rows)
            db.archive(rows, "open-nfl-props")
            for (eid, market, player, point), books in pair_two_way(rows).items():
                stat = NFL_MARKET_STAT.get(market)
                hit = by_name.get(norm(player or ""))
                if not stat or hit is None:
                    continue
                pj, prow = hit
                if stat == "td":  # anytime TD: "Yes"/"No" outcomes, no point
                    line, sides = 0.5, (("Yes", "No"),)
                else:
                    if point is None:
                        continue
                    line, sides = point, (("Over", "Under"), ("Under", "Over"))
                p_over = prob_at_least(pj["sims"], stat, math.floor(line) + 1, calibrated=True)
                if p_over is None:
                    continue
                for side, other in sides:
                    p_model = p_over if side in ("Over", "Yes") else 1 - p_over
                    best = best_side(books, side)
                    if best is None:
                        continue
                    fair, src = fair_prob(books, side, other)
                    edge = pricing.edge(p_model, best[1])
                    props.append({
                        "event_id": eid, "start": e["commence_time"], "event": f'{e["away_team"]} @ {e["home_team"]}',
                        "player": player, "player_id": prow["player_id"], "team": prow["team"], "market": market,
                        "stat": stat, "line": line, "side": side, "alt": market.endswith("alternate"),
                        "model_mean": round(pj["means"].get(stat, 0), 2), "model_prob": round(p_model, 4),
                        "fair_market_prob": round(fair, 4) if fair is not None else None, "fair_source": src,
                        "dk": books.get("draftkings", {}).get(side), "fd": books.get("fanduel", {}).get(side),
                        "pin": books.get("pinnacle", {}).get(side), "best_book": best[0], "best_price": best[1],
                        "edge": round(edge, 4), "model_vs_market": round(p_model - fair, 4) if fair is not None else None,
                        "kelly_usd": pricing.kelly_stake(p_model, best[1]), "player_status": prow["status"],
                        "low_trust": stat in config.NFL_LOW_TRUST,
                    })
        credits = api.remaining
    props.sort(key=lambda r: r["edge"], reverse=True)
    season = int(pg.season.max())
    for r in [x for x in props if x["edge"] > 0][:config.FACTS_ROWS]:
        side = "Over" if r["side"] in ("Over", "Yes") else "Under"
        prow = next((p for p in projections if p["player_id"] == r["player_id"]), None)
        g = next((x for x in games if prow and prow["team"] in x["event"]), None)
        opp = None
        if g and prow:
            a, h = [t.strip() for t in g["event"].split("@")]
            opp = ESPN_TO_NFLVERSE.get(h if prow["team"] == a else a, h if prow["team"] == a else a)
        r["facts"] = facts.nfl_facts(pg, r["player_id"], r["player"], r["stat"], r["line"], side, day.isoformat(), season) + \
            (facts.nfl_matchup(pg, opp, prow["pos"], r["stat"], day.isoformat(), season) if opp and prow else []) + [
            facts.model_bullet(r["model_mean"], r["model_prob"], r["fair_market_prob"], r["edge"], r["line"], side, r["stat"])]
    return {"games": games, "projections": projections, "props": props, "credits_remaining": credits}


# ------------------------------------------------------------------ tennis
def _pmf(d: dict, digits: int = 4) -> dict:
    return {str(k): round(v, digits) for k, v in sorted(d.items()) if v >= 1e-4}


def tennis_board(day: dt.date, api: OddsAPI | None) -> dict:
    from desk import facts
    from desk.tennis import data as tdata
    from desk.tennis.elo import build
    from desk.tennis.score import ServeTable, p_cover, p_total_over

    tdata.update(day)
    allm = tdata.all_matches()
    elos = build(allm)
    serve = ServeTable()
    lookup = tdata.surface_lookup()
    now = dt.datetime.now(dt.timezone.utc)
    matches, dists = [], {}
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
                    bo = 5 if slam and g_tour == "atp" else 3
                    p = elo.predict(a, b, surface, bo)
                    sd = serve.match(g_tour, a, b, surface, p, bo)
                    dists[c.get("id")] = sd
                    m = {"espn_id": c.get("id"), "tour": g_tour, "tournament": ev.get("name"), "surface": surface,
                         "start": c.get("date"), "best_of": bo, "player_a": a, "player_b": b, "p_a": round(p, 4),
                         "elo_a": round(elo.rating(a, surface)), "elo_b": round(elo.rating(b, surface)),
                         "elo_matches_a": elo.n[a], "elo_matches_b": elo.n[b],
                         "low_sample": min(elo.n[a], elo.n[b]) < 15,
                         "hold_a": round(sd["hold_a"], 3), "hold_b": round(sd["hold_b"], 3),
                         "exp_total_games": round(sum(k * v for k, v in sd["total_games"].items()), 1),
                         "set_scores": {f"{x}-{y}": round(v, 3) for (x, y), v in sd["set_scores"].items()},
                         "total_games_pmf": _pmf(sd["total_games"]), "margin_pmf": _pmf(sd["margin"])}
                    m["facts"] = facts.tennis_facts(allm, m)
                    matches.append(m)
    priced = []
    credits = None
    if api and matches:
        con = db.connect()
        sports = [s for s in api.sports() if s.get("group") == "Tennis" and s.get("active")]
        idx = {}
        for m in matches:
            idx[(norm(m["player_a"]), norm(m["player_b"]))] = m
            idx[(norm(m["player_b"]), norm(m["player_a"]))] = m
        for sp in sports:
            if low_credits(api):
                break
            try:
                payload = api.game_odds(sp["key"], markets=("h2h", "spreads", "totals"))
            except OddsAPIError as err:
                print("odds error", err)
                continue
            payload = [ev for ev in payload if (norm(ev.get("home_team", "")), norm(ev.get("away_team", ""))) in idx]
            rows = flatten(payload, "game", sp["key"])
            db.insert_many(con, "odds_snapshots", rows)
            db.archive(rows, "open-tennis")
            for (eid, market, _pl, point), books in pair_two_way(rows).items():
                ev = next(e for e in payload if e["id"] == eid)
                m = idx[(norm(ev.get("home_team", "")), norm(ev.get("away_team", "")))]
                sd = dists[m["espn_id"]]
                sides = list(next(iter(books.values())).keys())
                if len(sides) != 2:
                    continue
                for side in sides:
                    other = sides[1] if side == sides[0] else sides[0]
                    if market == "totals":
                        p_model = p_total_over(sd["total_games"], point) if side == "Over" else 1 - p_total_over(sd["total_games"], point)
                        line, trust = point, "medium"
                    else:
                        is_a = norm(side) == norm(m["player_a"])
                        if not is_a and norm(side) != norm(m["player_b"]):
                            continue
                        if market == "h2h":
                            p_model, line, trust = (m["p_a"] if is_a else 1 - m["p_a"]), None, "model"
                        else:  # spreads: the side's own handicap line
                            line = next((r["point"] for r in rows if r["event_id"] == eid and r["market"] == market
                                         and r["side"] == side and r["point"] is not None and abs(r["point"]) == point), None)
                            if line is None:
                                continue
                            mg = sd["margin"] if is_a else {-k: v for k, v in sd["margin"].items()}
                            p_model, trust = p_cover(mg, line), "medium"
                    best = best_side(books, side)
                    if best is None:
                        continue
                    fair, src = fair_prob(books, side, other)
                    priced.append({"event_id": eid, "sport": sp["key"], "start": ev.get("commence_time"), "tour": m["tour"],
                                   "tournament": m["tournament"], "surface": m["surface"], "market": market,
                                   "player": side if market != "totals" else f"{m['player_a']} v {m['player_b']}",
                                   "side": side, "line": line,
                                   "opponent": other if market != "totals" else None, "match": f"{m['player_a']} v {m['player_b']}",
                                   "model_prob": round(p_model, 4), "trust": trust,
                                   "fair_market_prob": round(fair, 4) if fair is not None else None, "fair_source": src,
                                   "dk": books.get("draftkings", {}).get(side), "fd": books.get("fanduel", {}).get(side),
                                   "pin": books.get("pinnacle", {}).get(side), "best_book": best[0], "best_price": best[1],
                                   "edge": round(pricing.edge(p_model, best[1]), 4),
                                   "model_vs_market": round(p_model - fair, 4) if fair is not None else None,
                                   "kelly_usd": pricing.kelly_stake(p_model, best[1]), "low_sample": m["low_sample"]})
        credits = api.remaining
    priced.sort(key=lambda r: r["edge"], reverse=True)
    return {"matches": matches, "priced": priced, "credits_remaining": credits}


# ------------------------------------------------------------------ soccer
from desk.soccer.data import same_team  # noqa: E402  (shared with grading)


def fair_multi_books(books: dict, side: str):
    """No-vig probability of `side` in a 2- or 3-way market: Pinnacle if it priced every side, else DK/FD average."""
    sides = set().union(*[set(v) for v in books.values()]) if books else set()
    pin = books.get(config.SHARP_BOOK, {})
    if sides and set(pin) == sides:
        return pricing.fair_multi(pin)[side], "pinnacle"
    vals = [pricing.fair_multi(bp)[side] for b, bp in books.items() if b in config.BET_BOOKS and set(bp) == sides]
    return (sum(vals) / len(vals), "dk/fd") if vals else (None, None)


def soccer_board(day: dt.date, api: OddsAPI | None) -> dict:
    from desk import facts
    from desk.soccer import data as sdata
    from desk.soccer.model import SoccerModel

    sdata.update(day - dt.timedelta(days=1))
    mt, pl = sdata.matches(), sdata.players()
    model = SoccerModel(mt, pl, day.isoformat())
    now = dt.datetime.now(dt.timezone.utc)
    fixtures = []
    for league, (sport_key, code) in sdata.LEAGUES.items():
        try:
            sb = espn(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/scoreboard?dates={day:%Y%m%d}")
        except Exception:
            continue
        for ev in sb.get("events", []):
            comp = ev["competitions"][0]
            if comp.get("status", {}).get("type", {}).get("state") != "pre":
                continue
            start = dt.datetime.fromisoformat(ev["date"].replace("Z", "+00:00"))
            if not (now - dt.timedelta(hours=1) <= start <= now + dt.timedelta(hours=26)):
                continue
            side = {c["homeAway"]: c["team"] for c in comp["competitors"]}
            h, a = side["home"], side["away"]
            r = model.match(h["id"], a["id"], neutral=bool(comp.get("neutralSite")))
            n_h = int((mt.team_id == h["id"]).sum())
            n_a = int((mt.team_id == a["id"]).sum())
            cpmf = model.corners_total_pmf(r["corners_home"], r["corners_away"])
            fx = {"league": league, "sport_key": sport_key, "tracker_league": code, "espn_id": ev["id"], "start": ev["date"],
                  "home": h["displayName"], "away": a["displayName"], "home_id": h["id"], "away_id": a["id"],
                  "home_abbr": h.get("abbreviation"), "away_abbr": a.get("abbreviation"),
                  "p_home": round(r["p_home"], 4), "p_draw": round(r["p_draw"], 4), "p_away": round(r["p_away"], 4),
                  "xg_home": round(r["lambda_home"], 2), "xg_away": round(r["lambda_away"], 2), "btts": round(r["btts"], 3),
                  "p_over": {str(L): round(model.p_total_over(r["goals_pmf"], L), 3) for L in (1.5, 2.5, 3.5, 4.5)},
                  "exp_corners": round(r["corners_home"] + r["corners_away"], 1),
                  "p_corners_over": {str(L): round(model.p_total_over(cpmf, L), 3) for L in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5)},
                  "sot_home": round(r["sot_home"], 2), "sot_away": round(r["sot_away"], 2),
                  "low_sample": min(n_h, n_a) < 10, "players": []}
            for tid, opp, is_home, tname in ((h["id"], a["id"], 1, h["displayName"]), (a["id"], h["id"], 0, a["displayName"])):
                recent_events = mt[(mt.team_id == tid) & (mt.date < day.isoformat())].sort_values("date").event_id.tail(5)
                rp = pl[(pl.team_id == tid) & pl.event_id.isin(recent_events)]
                starters = rp.groupby("player_id").agg(starts=("starter", "sum"), player=("player", "last"))
                for pid, srow in starters.iterrows():
                    likely = bool(srow.starts >= 3)
                    pr = model.player_sot(pid, tid, opp, is_home, starter=likely)
                    if pr and pr["group"] != "GK":
                        fx["players"].append({"player": srow.player, "player_id": pid, "team": tname, "team_id": tid,
                                              "role": "projected starter" if likely else "rotation / bench",
                                              "pos": pr["group"], "sot_mean": round(pr["mean"], 2), "per90": round(pr["per90"], 2),
                                              "minutes": round(pr["minutes"]), "p_sot_1": round(model.p_sot_at_least(pr["mean"], 1), 3),
                                              "p_sot_2": round(model.p_sot_at_least(pr["mean"], 2), 3)})
            fx["facts"] = facts.soccer_team_facts(mt, h["id"], h["displayName"], day.isoformat()) + \
                facts.soccer_team_facts(mt, a["id"], a["displayName"], day.isoformat())
            fixtures.append(fx)
    props, credits = [], None
    if api and fixtures:
        con = db.connect()
        for sport_key in sorted({f["sport_key"] for f in fixtures}):
            if low_credits(api):
                break
            try:
                events = api.events(sport_key)
            except OddsAPIError as err:
                print("odds error", err)
                continue
            for e in events:
                fx = next((f for f in fixtures if f["sport_key"] == sport_key and same_team(f["home"], e["home_team"])
                           and same_team(f["away"], e["away_team"])), None)
                if fx is None or low_credits(api):
                    continue
                try:
                    payload = api.event_odds(sport_key, e["id"], config.SOCCER_MARKETS)
                except OddsAPIError as err:
                    print("odds error", err)
                    continue
                rows = flatten(payload, "props", sport_key)
                db.insert_many(con, "odds_snapshots", rows)
                db.archive(rows, "open-soccer")
                r = model.match(fx["home_id"], fx["away_id"])
                cpmf = model.corners_total_pmf(r["corners_home"], r["corners_away"])
                byname = {norm(p["player"]): p for p in fx["players"]}
                for (eid, market, player, point), books in pair_two_way(rows).items():
                    for side in sorted(set().union(*[set(v) for v in books.values()])):
                        stat, line = market, point
                        if market == "h2h":
                            if side == "Draw":
                                p_model, label = r["p_draw"], "Draw"
                            elif same_team(side, fx["home"]):
                                p_model, label = r["p_home"], fx["home"]
                            elif same_team(side, fx["away"]):
                                p_model, label = r["p_away"], fx["away"]
                            else:
                                continue
                            fair, src = fair_multi_books(books, side)
                        elif market in ("totals", "alternate_totals", "alternate_totals_corners"):
                            pmf = cpmf if "corners" in market else r["goals_pmf"]
                            po = model.p_total_over(pmf, point)
                            p_model, label = (po if side == "Over" else 1 - po), f"{side} {point}"
                            stat = "corners" if "corners" in market else "goals"
                            fair, src = fair_prob(books, side, "Under" if side == "Over" else "Over")
                        elif market == "player_shots_on_target":
                            pp = byname.get(norm(player or ""))
                            if pp is None or point is None:
                                continue
                            pk = model.p_sot_at_least(pp["sot_mean"], math.floor(point) + 1)
                            p_model, label, stat = (pk if side == "Over" else 1 - pk), f"{player} {side} {point}", "sot"
                            fair, src = fair_prob(books, side, "Under" if side == "Over" else "Over")
                        else:
                            continue
                        best = best_side(books, side)
                        if best is None:
                            continue
                        edge = pricing.edge(p_model, best[1])
                        row = {"event_id": eid, "sport": sport_key, "start": e["commence_time"],
                               "event": f"{fx['away']} @ {fx['home']}", "league": fx["league"], "market": market,
                               "stat": stat, "side": side, "label": label, "line": line, "player": player,
                               "model_prob": round(p_model, 4), "fair_market_prob": round(fair, 4) if fair is not None else None,
                               "fair_source": src, "dk": books.get("draftkings", {}).get(side),
                               "fd": books.get("fanduel", {}).get(side), "pin": books.get("pinnacle", {}).get(side),
                               "best_book": best[0], "best_price": best[1], "edge": round(edge, 4),
                               "model_vs_market": round(p_model - fair, 4) if fair is not None else None,
                               "kelly_usd": pricing.kelly_stake(p_model, best[1]), "low_sample": fx["low_sample"]}
                        if stat == "sot":
                            pp = byname[norm(player)]
                            row["player_id"] = pp["player_id"]
                            opp_id = fx["away_id"] if pp["team_id"] == fx["home_id"] else fx["home_id"]
                            opp_nm = fx["away"] if pp["team_id"] == fx["home_id"] else fx["home"]
                            row["facts"] = facts.soccer_player_facts(pl, pp["player_id"], player, point, side, day.isoformat()) + \
                                facts.soccer_sot_matchup(mt, opp_id, opp_nm, day.isoformat()) + [
                                facts.model_bullet(pp["sot_mean"], p_model, row["fair_market_prob"], edge, point, side, "sot",
                                                   f"Projected {pp['minutes']} minutes ({pp['role']}); confirm the XI ~1 hour before kickoff")]
                            row["role"] = pp["role"]
                        props.append(row)
        credits = api.remaining
    props.sort(key=lambda r: r["edge"], reverse=True)
    return {"fixtures": fixtures, "props": props, "credits_remaining": credits}


# ------------------------------------------------------------------ output
def _pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


def to_markdown(board: dict) -> str:
    lines = [f"# Model board — {board['date']} {board['session'].upper()}",
             f"Generated {board['generated_at']} · odds: {board['odds_source']}", ""]
    if "nba" in board:
        props = board["nba"]["props"]
        lines += ["## NBA props with the largest model edge", "",
                  "⚠️ = model and no-vig market disagree by more than 10 points: check for news before using.", "",
                  "| Player | Market | Side | Line | Model mean | Model | Fair mkt | Best | Edge | Kelly $ |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in [p for p in props if p["edge"] > 0][:40]:
            fair = r["fair_market_prob"]
            warn = " ⚠️" if fair is not None and abs(r["model_prob"] - fair) > 0.10 else ""
            lines.append(f"| {r['player']} | {r['stat']}{' (alt)' if r['alt'] else ''} | {r['side']} | {r['line']} | "
                         f"{r['model_mean']} | {r['model_prob']:.0%}{warn} | {'–' if fair is None else f'{fair:.0%}'} | "
                         f"{r['best_price']:+.0f} {r['best_book']} | {r['edge']:+.1%} | {r['kelly_usd']:.0f} |")
        if not props:
            lines += ["", "_No prices (no odds key or no markets yet)._"]
        lines += ["", "## NBA projections (model means; injuries from ESPN at run time)", "",
                  "| Game | Player | Status | Min | Pts | Reb | Ast | 3PM | PRA |", "|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(board["nba"]["projections"], key=lambda r: (r["event"], -r["minutes"])):
            if r["minutes"] >= 20:
                lines.append(f"| {r['event']} | {r['player']} | {r['status']} | {r['minutes']} | {r['pts']} | {r['reb']} | "
                             f"{r['ast']} | {r.get('threes', 0)} | {r['pra']} |")
    if board.get("nfl", {}).get("games"):
        props = board["nfl"]["props"]
        lines += ["", "## NFL props with the largest model edge", "",
                  "| Player | Market | Side | Line | Model mean | Model | Fair mkt | Best | Edge | Kelly $ |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for r in [p for p in props if p["edge"] > 0][:40]:
            fair = r["fair_market_prob"]
            warn = " ⚠️" if fair is not None and abs(r["model_prob"] - fair) > 0.10 else ""
            lt = " (low trust)" if r.get("low_trust") else ""
            lines.append(f"| {r['player']} | {r['stat']}{lt}{' (alt)' if r['alt'] else ''} | {r['side']} | {r['line']} | "
                         f"{r['model_mean']} | {r['model_prob']:.0%}{warn} | {'–' if fair is None else f'{fair:.0%}'} | "
                         f"{r['best_price']:+.0f} {r['best_book']} | {r['edge']:+.1%} | {r['kelly_usd']:.0f} |")
        if not props:
            lines += ["", "_No NFL prices (no odds key or no markets yet)._"]
        lines += ["", "## NFL projections (model means; ESPN injury report at build time)", "",
                  "| Game | Player | Pos | Status | Tgt | Rec | Rec yds | Rush att | Rush yds | Pass yds | TD |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for r in sorted(board["nfl"]["projections"], key=lambda r: (r["event"], r["team"], -r.get("targets", 0) - r.get("rush_att", 0))):
            lines.append(f"| {r['event']} | {r['player']} | {r['pos']} | {r['status']} | {r.get('targets', 0)} | {r.get('rec', 0)} | "
                         f"{r.get('rec_yds', 0)} | {r.get('rush_att', 0)} | {r.get('rush_yds', 0)} | {r.get('pass_yds', '–')} | "
                         f"{r.get('td', 0)} |")
    for key, title in (("nba", "NBA"), ("nfl", "NFL")):
        rows = [r for r in board.get(key, {}).get("props", []) if r.get("facts")]
        if rows:
            lines += ["", f"## {title} leg reasoning (our own data) — top edges", ""]
            for r in rows[:25]:
                lines.append(f"**{r['player']} {r['side']} {r['line']} {r['stat']}** ({r['best_price']:+.0f} {r['best_book']}, "
                             f"edge {r['edge']:+.1%})")
                lines += [f"- {b}" for b in r["facts"]] + [""]
    if "tennis" in board:
        t = board["tennis"]
        lines += ["", "## Tennis — priced markets (match winner = Elo model; games/handicap = medium-trust score model)", "",
                  "| Match | Market | Pick | Line | Model | Fair mkt | Best | Edge |", "|---|---|---|---|---|---|---|---|"]
        for r in [x for x in t["priced"] if x["edge"] > 0][:30]:
            lines.append(f"| {r['match']} | {r['market']} | {r['side']} | {'' if r['line'] is None else r['line']} | "
                         f"{r['model_prob']:.0%} | {_pct(r['fair_market_prob'])} | "
                         f"{r['best_price']:+.0f} {r['best_book']} | {r['edge']:+.1%} |")
        lines += ["", "## Tennis — match model", "",
                  "| Match | Surface | P(A) | Hold A / B | Exp. games | Set scores |", "|---|---|---|---|---|---|"]
        for m in t["matches"]:
            ss = ", ".join(f"{k} {v:.0%}" for k, v in m["set_scores"].items())
            lines.append(f"| {m['player_a']} v {m['player_b']}{' (low sample)' if m['low_sample'] else ''} | {m['surface']} | "
                         f"{m['p_a']:.0%} | {m['hold_a']:.0%} / {m['hold_b']:.0%} | {m['exp_total_games']} | {ss} |")
        for m in t["matches"][:20]:
            lines += ["", f"**{m['player_a']} v {m['player_b']}** — {m['tournament']}"] + [f"- {b}" for b in m["facts"]]
    if "soccer" in board:
        sc = board["soccer"]
        lines += ["", "## Soccer — priced markets (result, total goals, corners, player shots on target)", "",
                  "| Match | Market | Pick | Model | Fair mkt | Best | Edge |", "|---|---|---|---|---|---|---|"]
        for r in [x for x in sc["props"] if x["edge"] > 0][:40]:
            lines.append(f"| {r['event']} | {r['stat']} | {r['label']} | {r['model_prob']:.0%}{' (low sample)' if r['low_sample'] else ''} | "
                         f"{_pct(r['fair_market_prob'])} | "
                         f"{r['best_price']:+.0f} {r['best_book']} | {r['edge']:+.1%} |")
        lines += ["", "## Soccer — match model", "",
                  "| Match | H / D / A | xG H–A | O2.5 | BTTS | Exp. corners | O9.5 corners |", "|---|---|---|---|---|---|---|"]
        for f in sc["fixtures"]:
            lines.append(f"| {f['home']} v {f['away']}{' (low sample)' if f['low_sample'] else ''} | {f['p_home']:.0%} / "
                         f"{f['p_draw']:.0%} / {f['p_away']:.0%} | {f['xg_home']}–{f['xg_away']} | {f['p_over']['2.5']:.0%} | "
                         f"{f['btts']:.0%} | {f['exp_corners']} | {f['p_corners_over']['9.5']:.0%} |")
        for f in sc["fixtures"]:
            top = sorted([p for p in f["players"] if p.get("role") == "projected starter"], key=lambda p: -p["sot_mean"])[:6]
            lines += ["", f"**{f['home']} v {f['away']}**"] + [f"- {b}" for b in f["facts"]]
            lines.append("- Likely starters' shots on target (model mean · P(1+) · P(2+)): " +
                         "; ".join(f"{p['player']} {p['sot_mean']} · {p['p_sot_1']:.0%} · {p['p_sot_2']:.0%}" for p in top))
        rows = [r for r in sc["props"] if r.get("facts")]
        if rows:
            lines += ["", "## Soccer shots-on-target leg reasoning (our own data) — top edges", ""]
            for r in rows[:20]:
                lines.append(f"**{r['label']} SOT** ({r['best_price']:+.0f} {r['best_book']}, edge {r['edge']:+.1%})")
                lines += [f"- {b}" for b in r["facts"]] + [""]
    return "\n".join(lines) + "\n"


def main():
    session = sys.argv[1] if len(sys.argv) > 1 else "pm"
    day = dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else config.et_today()
    odds_error = None
    try:
        api = OddsAPI()
        api.sports()  # one free call: validates the key before any priced call
    except OddsAPIError as err:
        odds_error = str(err)[:300] if os.environ.get("ODDS_API_KEY") else "ODDS_API_KEY not set"
        print("odds disabled:", odds_error)
        api = None
    board = {"date": day.isoformat(), "session": session,
             "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
             "odds_source": "the-odds-api" if api else "none (model only)", "odds_error": odds_error}
    if session == "pm":
        board["nba"] = nba_board(day, api)
        if day.weekday() != 6:  # weekday NFL (TNF/MNF/Saturday); Sunday has its own session
            board["nfl"] = nfl_board(day, api)
        if api:
            board["nba_lines"] = market_board(day, api, ["basketball_nba"], "nba-lines")
            board["nfl_lines"] = market_board(day, api, ["americanfootball_nfl"], "nfl-lines")
    elif session == "nfl":
        board["nfl"] = nfl_board(day, api)
        if api:
            board["nfl_lines"] = market_board(day, api, ["americanfootball_nfl"], "nfl-lines")
    else:
        board["tennis"] = tennis_board(day, api)
        board["soccer"] = soccer_board(day, api)
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
