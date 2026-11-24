"""Grade past model boards against results and closing lines.

For every board row from finished days it records the outcome and, when a closing snapshot exists, the closing
no-vig probability. Then it scores the model three ways:
  1. Accuracy  - Brier / log loss of the model vs the no-vig market at bet time (is the model better than the book?)
  2. CLV       - did the price we would have taken beat the closing price? (the best short-run signal of edge)
  3. P&L       - flat 1-unit and Kelly-staked results of the rows the board flagged (edge >= EDGE_FLAG)

Writes reports/model_performance.json, reports/model_performance.md and reports/graded/<date>.csv.
Usage: python3 scripts/grade_board.py
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys
import unicodedata
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pandas as pd

from desk import config, db, pricing

STAT_COLS = {"pts": ["pts"], "reb": ["reb"], "ast": ["ast"], "threes": ["threes"], "pra": ["pts", "reb", "ast"]}


def norm(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    for suf in (" jr.", " jr", " sr.", " iii", " ii", " iv"):
        s = s.replace(suf, "")
    return "".join(ch for ch in s if ch.isalnum() or ch == " ").strip()


def espn(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BettingDesk/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


# ---------------------------------------------------------------- outcomes
def nba_prop_outcome(box: pd.DataFrame, day: str, player: str, stat: str, line: float, side: str):
    rows = box[(box.date == day) & (box.player.map(norm) == norm(player))]
    if rows.empty or rows.iloc[0].dnp == 1 or rows.iloc[0].minutes == 0:
        return None  # no box score or did not play -> void
    val = sum(float(rows.iloc[0][c]) for c in STAT_COLS[stat])
    if val == line:
        return None  # push
    over = val > line
    return int(over if side == "Over" else not over)


NFL_COLS = {"rec": ["receptions"], "rec_yds": ["receiving_yards"], "rush_yds": ["rushing_yards"], "rush_att": ["carries"],
            "pass_yds": ["passing_yards"], "pass_att": ["attempts"], "pass_cmp": ["completions"],
            "pass_td": ["passing_tds"], "td": ["rushing_tds", "receiving_tds"]}


def nfl_prop_outcome(pg, day: str, player_id: str, stat: str, line: float, side: str):
    if pg is None or stat not in NFL_COLS:
        return None
    d = dt.date.fromisoformat(day)
    rows = pg[(pg.player_id == player_id) & (pg.date >= day) & (pg.date <= (d + dt.timedelta(days=1)).isoformat())]
    if rows.empty:
        return None  # not yet in nflverse, or did not play -> void/pending
    val = float(rows.iloc[0][NFL_COLS[stat]].sum())
    if val == line:
        return None
    over = val > line
    return int(over if side in ("Over", "Yes") else not over)


def tennis_outcome(live: pd.DataFrame, player: str, opponent: str):
    a, b = norm(player), norm(opponent)
    w, l = live.winner_name.map(norm), live.loser_name.map(norm)
    if ((w == a) & (l == b)).any():
        return 1
    if ((w == b) & (l == a)).any():
        return 0
    return None


_score_cache: dict = {}


def final_scores(sport: str, day: str) -> dict:
    """{(away_norm, home_norm): (away_pts, home_pts)} from ESPN for NBA/NFL/soccer game lines."""
    key = (sport, day)
    if key in _score_cache:
        return _score_cache[key]
    path = {"basketball_nba": "basketball/nba", "americanfootball_nfl": "football/nfl"}.get(sport)
    if sport.startswith("soccer"):
        path = {"soccer_epl": "soccer/eng.1", "soccer_spain_la_liga": "soccer/esp.1", "soccer_italy_serie_a": "soccer/ita.1",
                "soccer_germany_bundesliga": "soccer/ger.1", "soccer_france_ligue_one": "soccer/fra.1",
                "soccer_uefa_champs_league": "soccer/uefa.champions", "soccer_usa_mls": "soccer/usa.1"}.get(sport)
    out = {}
    if path:
        d = dt.date.fromisoformat(day)
        for dd in (d, d + dt.timedelta(days=1)):
            try:
                sb = espn(f"https://site.api.espn.com/apis/site/v2/sports/{path}/scoreboard?dates={dd:%Y%m%d}")
            except Exception:
                continue
            for ev in sb.get("events", []):
                comp = ev["competitions"][0]
                if not comp.get("status", {}).get("type", {}).get("completed"):
                    continue
                side = {c["homeAway"]: c for c in comp["competitors"]}
                names = lambda c: {norm(c["team"].get(k, "")) for k in ("displayName", "shortDisplayName", "name", "location")}
                out[(frozenset(names(side["away"])), frozenset(names(side["home"])))] = (
                    float(side["away"]["score"]), float(side["home"]["score"]))
    _score_cache[key] = out
    return out


def line_outcome(r: dict, day: str):
    away, home = [norm(x) for x in r["event"].split(" @ ")]
    for (an, hn), (ap, hp) in final_scores(r["sport"], day).items():
        if away in an and home in hn:
            break
    else:
        return None
    side = norm(r["side"])
    if r["market"] == "totals":
        tot = ap + hp
        if tot == r["line"]:
            return None
        return int((tot > r["line"]) == (side == "over"))
    if r["market"] == "h2h":
        if side == "draw":
            return int(ap == hp)
        mine, theirs = (ap, hp) if side == away else (hp, ap)
        return int(mine > theirs)
    if r["market"] == "spreads" and r["line"] is not None:
        mine, theirs = (ap, hp) if side == away else (hp, ap)
        margin = mine + r["line"] - theirs
        return None if margin == 0 else int(margin > 0)
    return None


# ---------------------------------------------------------------- closing lines
def closing_index(day: str) -> dict:
    """{(event_id, market, player_norm, side_norm, point): {book: price}} from close snapshots of that day and next."""
    d = dt.date.fromisoformat(day)
    idx: dict = {}
    for dd in (d, d + dt.timedelta(days=1)):
        for r in db.load_snapshots(f"{dd}-close-"):
            k = (r["event_id"], r["market"], norm(r["player"]), norm(r["side"]), r["point"])
            idx.setdefault(k, {})[r["book"]] = r["price"]
    return idx


def close_fair(idx: dict, event_id, market, player, side, other_sides, point):
    """No-vig closing probability for `side`: Pinnacle if it priced all sides, else DK/FD average."""
    keys = [(event_id, market, norm(player), norm(s), p) for s, p in [(side, point)] + other_sides]
    books = [idx.get(k, {}) for k in keys]
    for pref in ([config.SHARP_BOOK], config.BET_BOOKS):
        probs = []
        for b in pref:
            prices = [bk.get(b) for bk in books]
            if all(p is not None for p in prices):
                probs.append(pricing.devig_power(prices)[0])
        if probs:
            return sum(probs) / len(probs)
    return None


# ---------------------------------------------------------------- main
def latest_boards(today: dt.date) -> dict:
    """{date: [board json, ...]} for finished days, newest board per session."""
    out: dict = {}
    for path in sorted(glob.glob(os.path.join(ROOT, "boards", "20*-*.json"))):
        name = os.path.basename(path)[:-5]
        day = name[:10]
        if dt.date.fromisoformat(day) >= today:
            continue
        out.setdefault(day, []).append(json.load(open(path)))
    return out


def grade(today: dt.date) -> pd.DataFrame:
    box_path = os.path.join(ROOT, "data", "nba_boxscores.csv")
    box = pd.read_csv(box_path, dtype={"game_id": str, "player_id": str}) if os.path.exists(box_path) else pd.DataFrame()
    live_path = os.path.join(ROOT, "data", "tennis", "live.csv")
    live = pd.read_csv(live_path) if os.path.exists(live_path) else pd.DataFrame()
    pg = None
    try:
        from desk.nfl import data as nfl_data
        if os.path.exists(os.path.join(nfl_data.DIR, "games.csv")):
            pg = nfl_data.player_games()
    except Exception as err:
        print("nfl data unavailable:", err)
    graded = []
    for day, boards in latest_boards(today).items():
        cidx = closing_index(day)
        for b in boards:
            for r in b.get("nba", {}).get("props", []):
                if r.get("stat") not in STAT_COLS:
                    continue
                y = nba_prop_outcome(box, day, r["player"], r["stat"], r["line"], r["side"])
                other = "Under" if r["side"] == "Over" else "Over"
                cf = close_fair(cidx, r.get("event_id"), r["market"], r["player"], r["side"], [(other, r["line"])], r["line"])
                graded.append({"date": day, "sport": "nba", "kind": "prop" + ("_alt" if r.get("alt") else ""),
                               "label": f"{r['player']} {r['side']} {r['line']} {r['stat']}", **_common(r, y, cf)})
            for r in b.get("nfl", {}).get("props", []):
                y = nfl_prop_outcome(pg, day, r.get("player_id"), r["stat"], r["line"], r["side"])
                other = {"Over": "Under", "Under": "Over", "Yes": "No", "No": "Yes"}[r["side"]]
                cf = close_fair(cidx, r.get("event_id"), r["market"], r["player"], r["side"],
                                [(other, None if r["stat"] == "td" else r["line"])], None if r["stat"] == "td" else r["line"])
                graded.append({"date": day, "sport": "nfl", "kind": "prop" + ("_alt" if r.get("alt") else ""),
                               "label": f"{r['player']} {r['side']} {r['line']} {r['stat']}", **_common(r, y, cf)})
            for r in b.get("tennis", {}).get("priced", []):
                y = tennis_outcome(live, r["player"], r["opponent"]) if len(live) else None
                cf = close_fair(cidx, r.get("event_id"), "h2h", None, r["player"], [(r["opponent"], None)], None)
                graded.append({"date": day, "sport": "tennis", "kind": "h2h", "label": f"{r['player']} over {r['opponent']}",
                               **_common(r, y, cf)})
            for key in ("nba_lines", "nfl_lines", "soccer_lines"):
                for r in b.get(key, []):
                    y = line_outcome(r, day)
                    graded.append({"date": day, "sport": key.split("_")[0], "kind": r["market"],
                                   "label": f"{r['event']} {r['side']} {'' if r['line'] is None else r['line']}",
                                   "model_prob": r["fair_prob"], "fair_market_prob": r["fair_prob"], "best_price": r["best_price"],
                                   "edge": r["edge"], "kelly_usd": r["kelly_usd"], "outcome": y, "close_fair": None})
    df = pd.DataFrame(graded)
    if len(df):
        df["bet_implied"] = df.best_price.map(pricing.implied_prob)
        df["clv"] = df.close_fair - df.bet_implied  # >0: the price we could take was better than the fair close
        df["profit_1u"] = [(_payout(p) if y == 1 else -1.0) if y in (0, 1) else None for p, y in zip(df.best_price, df.outcome)]
        df["profit_kelly"] = [k * pu if pu is not None else None for k, pu in zip(df.kelly_usd, df.profit_1u)]
    return df


def _payout(price):
    return pricing.american_to_decimal(price) - 1


def _common(r, y, cf):
    return {"model_prob": r["model_prob"], "fair_market_prob": r.get("fair_market_prob"), "best_price": r["best_price"],
            "edge": r["edge"], "kelly_usd": r["kelly_usd"], "outcome": y, "close_fair": cf}


def summarize(df: pd.DataFrame) -> dict:
    out = {"generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "groups": []}
    if df.empty:
        return out
    for (sport, kind), g in df.groupby(["sport", "kind"]):
        done = g[g.outcome.isin([0, 1])]
        mk = done.dropna(subset=["fair_market_prob"])
        flagged = done[done.edge >= (config.MARKET_EDGE_FLAG if kind in ("h2h", "spreads", "totals") and sport != "tennis"
                                     else config.EDGE_FLAG)]
        clv = g.dropna(subset=["clv"])
        row = {"sport": sport, "kind": kind, "rows": int(len(g)), "graded": int(len(done))}
        if len(done):
            row.update(model_brier=pricing.brier(done.model_prob, done.outcome),
                       model_logloss=pricing.log_loss(done.model_prob, done.outcome))
        if len(mk):
            row.update(market_brier=pricing.brier(mk.fair_market_prob, mk.outcome),
                       market_logloss=pricing.log_loss(mk.fair_market_prob, mk.outcome),
                       model_logloss_same_rows=pricing.log_loss(mk.model_prob, mk.outcome))
        if len(clv):
            row.update(clv_rows=int(len(clv)), clv_avg=float(clv.clv.mean()), clv_beat_rate=float((clv.clv > 0).mean()))
        if len(flagged):
            row.update(flagged=int(len(flagged)), flagged_hit=float(flagged.outcome.mean()),
                       flagged_roi_1u=float(flagged.profit_1u.sum() / len(flagged)),
                       flagged_profit_kelly=float(flagged.profit_kelly.sum()),
                       flagged_staked_kelly=float(flagged.kelly_usd.sum()))
        out["groups"].append({k: (round(v, 4) if isinstance(v, float) else v) for k, v in row.items()})
    return out


def to_md(s: dict) -> str:
    lines = ["# Model performance (graded boards)", "", f"Updated {s['generated']}", "",
             "Model must beat the market's log loss on the same rows and show positive CLV before its edges are trusted.", "",
             "| Sport | Kind | Graded | Model LL | Market LL (same rows) | CLV avg | Beat close | Flagged | Hit | ROI/1u | Kelly P&L |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for g in s["groups"]:
        f = lambda k, pct=False: "–" if k not in g else (f"{g[k]:+.1%}" if pct else f"{g[k]}")
        lines.append(f"| {g['sport']} | {g['kind']} | {g['graded']} | {f('model_logloss_same_rows')} | {f('market_logloss')} | "
                     f"{f('clv_avg', True)} | {f('clv_beat_rate', True)} | {f('flagged')} | {f('flagged_hit', True)} | "
                     f"{f('flagged_roi_1u', True)} | {('$%+.2f' % g['flagged_profit_kelly']) if 'flagged_profit_kelly' in g else '–'} |")
    if not s["groups"]:
        lines.append("| _no graded boards yet_ | | | | | | | | | | |")
    return "\n".join(lines) + "\n"


def main():
    today = config.et_today()
    df = grade(today)
    os.makedirs(os.path.join(ROOT, "reports", "graded"), exist_ok=True)
    for day, g in (df.groupby("date") if len(df) else []):
        g.to_csv(os.path.join(ROOT, "reports", "graded", f"{day}.csv"), index=False)
    s = summarize(df)
    json.dump(s, open(os.path.join(ROOT, "reports", "model_performance.json"), "w"), indent=1)
    open(os.path.join(ROOT, "reports", "model_performance.md"), "w").write(to_md(s))
    print(to_md(s))


if __name__ == "__main__":
    main()
