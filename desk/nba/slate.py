"""Daily NBA slate report from our own data (balldontlie box scores + injuries, official NBA schedule for game type).

For every game on the slate:
 1. game type — regular season or Emirates NBA Cup (with the Cup label)
 2. standings and motivation signals — record, conference rank, games back of 6th/10th, last 10, streak, rest
 3. team strengths and weaknesses — offense/defense per 100 possessions, pace, and what each defense allows to
    guards / forwards / centers and to lead guards (ranked 1-30, 1 = allows the most)
 4. for each key player facing a defense that is weak against his position: how he did against similarly weak
    defenses and in head-to-head games (this season and last)
 5. each key player's recent form (last 5 / last 10 vs season) and fatigue (back-to-backs, games in 4/7 days,
    recent minutes load)
 6. injuries and how the absent player's minutes and shots have been redistributed
 7. how each teammate performs with vs without that injured player
All numbers come from our stored box scores; nothing is taken from previews or picks.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict

import numpy as np
import pandas as pd

KEY_MIN = 20.0          # a "key player" averages 20+ minutes over his last 10 games
STATS = ["pts", "reb", "ast", "fg3m"]
LABEL = {"pts": "pts", "reb": "reb", "ast": "ast", "fg3m": "3PM", "min": "min"}
OUT_STATUSES = ("out", "doubtful")
ROLE_PL = {"G": "guards", "F": "forwards", "C": "centers", "lead guard": "lead guards"}


# ---------------------------------------------------------------------------------------------- helpers
def pos_group(pos: str) -> str:
    p = (pos or "").upper().replace(" ", "")
    if p.startswith("C"):
        return "C"
    if p.startswith("F"):
        return "F"
    if p.startswith("G"):
        return "G"
    return "F"


def _f(x, nd=1):
    return "–" if x is None or (isinstance(x, float) and math.isnan(x)) else f"{x:.{nd}f}"


def rank_desc(series: pd.Series) -> pd.Series:
    """1 = highest value."""
    return series.rank(ascending=False, method="min").fillna(len(series)).astype(int)


# ---------------------------------------------------------------------------------------------- data prep
def prepare(stats: pd.DataFrame, games: pd.DataFrame, asof: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    s = stats[stats.date < asof].copy()
    for c in ["min", "pts", "reb", "ast", "stl", "blk", "turnover", "fgm", "fga", "fg3m", "fg3a", "ftm", "fta", "oreb", "dreb"]:
        if c in s:
            s[c] = pd.to_numeric(s[c], errors="coerce").fillna(0.0)
    s["played"] = s["min"] > 0
    s["grp"] = s.pos.map(pos_group)
    g = games[(games.date < asof)].copy()
    g = g[g.status.astype(str).str.lower().str.startswith("final")]
    return s, g


def team_games(s: pd.DataFrame) -> pd.DataFrame:
    """One row per team per game: totals and possessions."""
    p = s[s.played]
    t = p.groupby(["game_id", "date", "season", "team_id", "team", "opp_id", "home"], as_index=False).agg(
        pts=("pts", "sum"), reb=("reb", "sum"), ast=("ast", "sum"), fg3m=("fg3m", "sum"), fga=("fga", "sum"),
        fta=("fta", "sum"), oreb=("oreb", "sum"), tov=("turnover", "sum"), mins=("min", "sum"))
    t["poss"] = t.fga - t.oreb + t.tov + 0.44 * t.fta
    opp = t[["game_id", "team_id", "pts", "poss", "reb", "fg3m"]].rename(
        columns={"team_id": "opp_id", "pts": "opp_pts", "poss": "opp_poss", "reb": "opp_reb", "fg3m": "opp_fg3m"})
    t = t.merge(opp, on=["game_id", "opp_id"], how="left")
    t["pace"] = (t.poss + t.opp_poss) / 2 * 48 / (t.mins / 5).clip(lower=48)
    return t


def standings(g: pd.DataFrame, teams: list[dict], season: int) -> pd.DataFrame:
    g = g[(g.season == season) & (~g.postseason.astype(bool))]
    rows = []
    for _, x in g.iterrows():
        hw = x.home_score > x.away_score
        rows.append({"team_id": x.home_id, "date": x.date, "w": int(hw), "home": 1, "margin": x.home_score - x.away_score})
        rows.append({"team_id": x.away_id, "date": x.date, "w": int(not hw), "home": 0, "margin": x.away_score - x.home_score})
    r = pd.DataFrame(rows)
    info = {str(t["id"]): t for t in teams}
    out = []
    for tid, d in r.groupby("team_id"):
        d = d.sort_values("date")
        res = d.w.tolist()
        streak = 0
        for v in reversed(res):
            if v == res[-1]:
                streak += 1
            else:
                break
        out.append({"team_id": tid, "abbr": info.get(tid, {}).get("abbreviation", tid),
                    "name": info.get(tid, {}).get("full_name", tid), "conf": info.get(tid, {}).get("conference", "?"),
                    "w": int(d.w.sum()), "l": int(len(d) - d.w.sum()), "pct": d.w.mean(),
                    "home_rec": f"{int(d[d.home == 1].w.sum())}-{int((d.home == 1).sum() - d[d.home == 1].w.sum())}",
                    "away_rec": f"{int(d[d.home == 0].w.sum())}-{int((d.home == 0).sum() - d[d.home == 0].w.sum())}",
                    "last10": f"{int(sum(res[-10:]))}-{len(res[-10:]) - int(sum(res[-10:]))}",
                    "streak": f"{'W' if res[-1] else 'L'}{streak}", "margin": d.margin.mean()})
    st = pd.DataFrame(out)
    st["conf_rank"] = st.groupby("conf").pct.rank(ascending=False, method="first").astype(int)
    for conf, d in st.groupby("conf"):
        d = d.sort_values("conf_rank")
        lead_w, lead_l = d.iloc[0].w, d.iloc[0].l
        for k in (6, 10):
            if len(d) >= k:
                kw, kl = d.iloc[k - 1].w, d.iloc[k - 1].l
                st.loc[d.index, f"gb_{k}"] = ((kw - d.w) + (d.l - kl)) / 2
        st.loc[d.index, "gb_1"] = ((lead_w - d.w) + (d.l - lead_l)) / 2
    return st


def defense_vs_position(s: pd.DataFrame, season: int) -> pd.DataFrame:
    """Per defense: per-game pts/reb/ast/3PM allowed to opposing G, F, C, and to the opponent's lead guard
    (the guard with the most assists in that game). Ranks: 1 = allows the most."""
    p = s[(s.season == season) & s.played]
    by = p.groupby(["game_id", "opp_id", "grp"])[STATS].sum().reset_index()
    n_games = p.groupby("opp_id").game_id.nunique()
    out = by.groupby(["opp_id", "grp"])[STATS].sum().div(n_games, axis=0, level="opp_id").unstack("grp")
    out = out.fillna(0.0)
    out.columns = [f"{st}_{g}" for st, g in out.columns]
    guards = p[p.grp == "G"].sort_values("ast", ascending=False).drop_duplicates(["game_id", "team_id"])
    lg = guards.groupby("opp_id")[STATS].mean()
    lg.columns = [f"{c}_LG" for c in lg.columns]
    out = out.join(lg).fillna(0.0)
    out = pd.concat([out, pd.DataFrame({f"rk_{c}": rank_desc(out[c]) for c in out.columns})], axis=1)
    out.index.name = "team_id"
    return out


def team_profile(tg: pd.DataFrame, season: int) -> pd.DataFrame:
    t = tg[tg.season == season]
    prof = t.groupby("team_id").agg(gp=("game_id", "nunique"), pts=("pts", "mean"), opp_pts=("opp_pts", "mean"),
                                    poss=("poss", "sum"), opp_poss=("opp_poss", "sum"), pts_sum=("pts", "sum"),
                                    opp_sum=("opp_pts", "sum"), pace=("pace", "mean"), reb=("reb", "mean"),
                                    opp_reb=("opp_reb", "mean"), fg3m=("fg3m", "mean"), opp_fg3m=("opp_fg3m", "mean"))
    prof["ortg"] = prof.pts_sum / prof.poss * 100
    prof["drtg"] = prof.opp_sum / prof.opp_poss * 100
    prof["net"] = prof.ortg - prof.drtg
    prof["rk_ortg"] = rank_desc(prof.ortg)
    prof["rk_drtg_best"] = prof.drtg.rank(method="min").astype(int)      # 1 = best defense
    prof["rk_pace"] = rank_desc(prof.pace)
    prof["rk_opp_fg3m"] = rank_desc(prof.opp_fg3m)
    prof["rk_opp_reb"] = rank_desc(prof.opp_reb)
    return prof


# ---------------------------------------------------------------------------------------------- players
def player_lines(s: pd.DataFrame, tid: str, season: int) -> pd.DataFrame:
    p = s[(s.team_id == tid) & (s.season == season) & s.played].sort_values("date")
    rows = []
    for pid, d in p.groupby("player_id"):
        last10 = d.tail(10)
        rows.append({"player_id": pid, "player": d.player.iloc[-1], "pos": d.pos.iloc[-1], "grp": d.grp.iloc[-1],
                     "gp": len(d), "min": d["min"].mean(), "min_l10": last10["min"].mean(),
                     **{f"{k}": d[k].mean() for k in STATS},
                     **{f"{k}_l5": d.tail(5)[k].mean() for k in STATS + ["min"]},
                     **{f"{k}_l10": last10[k].mean() for k in STATS},
                     "last_date": d.date.iloc[-1], "min_last3": d.tail(3)["min"].tolist()})
    return pd.DataFrame(rows).sort_values("min_l10", ascending=False) if rows else pd.DataFrame()


def fatigue(tg: pd.DataFrame, tid: str, day: str) -> dict:
    d = tg[tg.team_id == tid].sort_values("date")
    dates = pd.to_datetime(d.date)
    today = pd.Timestamp(day)
    last = dates.iloc[-1] if len(dates) else None
    return {"b2b": bool(last is not None and (today - last).days == 1),
            "rest_days": int((today - last).days - 1) if last is not None else None,
            "games_last4": int(((today - dates).dt.days <= 4).sum()),
            "games_last7": int(((today - dates).dt.days <= 7).sum()),
            "last_home": bool(d.home.iloc[-1]) if len(d) else None}


def vs_weak_defenses(s: pd.DataFrame, dvp: pd.DataFrame, pid: str, stat_key: str, top: int = 8, season: int | None = None):
    """Player's per-game line against the defenses ranked in the top `top` for allowing stat_key (e.g. pts_G)."""
    weak = set(dvp.index[dvp[f"rk_{stat_key}"] <= top])
    p = s[(s.player_id == pid) & s.played & (s.season == season)]
    vs = p[p.opp_id.isin(weak)]
    return len(vs), {k: vs[k].mean() for k in STATS + ["min"]} if len(vs) else {}


def head_to_head(s: pd.DataFrame, pid: str, opp_id: str) -> list[dict]:
    p = s[(s.player_id == pid) & (s.opp_id == opp_id) & s.played].sort_values("date", ascending=False)
    return [{"date": r.date, **{k: r[k] for k in STATS + ["min"]}} for _, r in p.head(4).iterrows()]


def with_without(s: pd.DataFrame, tid: str, absent_pid: str, season: int, min_games: int = 3) -> dict:
    """Teammates' per-game lines in team games with vs without `absent_pid` (this season; last season too when the
    player was on the same team and this season has too few games without him)."""
    out = {}
    for seasons in ([season], [season, season - 1]):
        t = s[(s.team_id == tid) & s.season.isin(seasons)]
        mine = t[(t.player_id == absent_pid) & t.played]
        first = mine.date.min() if len(mine) else None
        if first is not None:                      # only games since he joined this team (trades)
            t = t[t.date >= first]
        games_all = set(t.game_id)
        with_g = set(mine.game_id)
        without_g = games_all - with_g
        if len(without_g) >= min_games or seasons != [season]:
            break
    if not with_g:
        return {"n_with": 0, "n_without": len(without_g), "rows": []}
    rows = []
    mates = t[t.played & (t.player_id != absent_pid)]
    for pid, d in mates.groupby("player_id"):
        a, b = d[d.game_id.isin(with_g)], d[d.game_id.isin(without_g)]
        if len(a) < 3 or len(b) < 2:
            continue
        row = {"player_id": pid, "player": d.player.iloc[-1], "n_with": len(a), "n_without": len(b)}
        for k in ["min", "pts", "reb", "ast", "fga"]:
            row[f"{k}_with"], row[f"{k}_without"] = a[k].mean(), b[k].mean()
            row[f"{k}_delta"] = b[k].mean() - a[k].mean()
        rows.append(row)
    rows.sort(key=lambda r: -abs(r["min_delta"]) - abs(r["pts_delta"]) / 2)
    return {"n_with": len(with_g), "n_without": len(without_g), "seasons": seasons, "rows": rows[:8]}


# ---------------------------------------------------------------------------------------------- report
def strengths_weaknesses(tid: str, prof: pd.DataFrame, dvp: pd.DataFrame) -> tuple[list[str], list[str]]:
    p, d = prof.loc[tid], dvp.loc[tid]
    p = {k: (int(v) if k.startswith("rk_") else float(v)) for k, v in p.items()}
    p = type("P", (), p)
    good, bad = [], []
    if p.rk_ortg <= 8:
        good.append(f"top-{p.rk_ortg} offense ({p.ortg:.1f} pts per 100 possessions)")
    if p.rk_ortg >= 23:
        bad.append(f"bottom-8 offense (#{p.rk_ortg}, {p.ortg:.1f} per 100)")
    if p.rk_drtg_best <= 8:
        good.append(f"top-{p.rk_drtg_best} defense ({p.drtg:.1f} allowed per 100)")
    if p.rk_drtg_best >= 23:
        bad.append(f"bottom-8 defense (#{p.rk_drtg_best}, {p.drtg:.1f} allowed per 100)")
    names = {"G": "guards", "F": "forwards", "C": "centers", "LG": "lead guards"}
    for g in ("G", "F", "C", "LG"):
        for st in ("pts", "reb", "ast", "fg3m"):
            col = f"{st}_{g}"
            if col not in d:
                continue
            rk = int(d[f"rk_{col}"])
            if rk <= 5:
                bad.append(f"allows the {rk}{_ord(rk)}-most {LABEL[st]} to {names[g]} ({d[col]:.1f} per game)")
            elif rk >= 26:
                good.append(f"shuts down {names[g]}' {LABEL[st]}: {31 - rk}{_ord(31 - rk)}-fewest allowed ({d[col]:.1f} per game)")
    if p.rk_opp_fg3m <= 5:
        bad.append(f"allows the {int(p.rk_opp_fg3m)}{_ord(int(p.rk_opp_fg3m))}-most threes ({p.opp_fg3m:.1f} per game)")
    if p.rk_pace <= 5:
        good.append(f"plays fast (#{int(p.rk_pace)} pace, {p.pace:.1f})")
    elif p.rk_pace >= 26:
        good.append(f"plays slow (#{int(p.rk_pace)} pace, {p.pace:.1f})")
    return good, bad


def _gb(x, place: str) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return f"– vs {place}"
    if x == 0:
        return f"level with {place}" if "1st" not in place else "in 1st"
    return f"{abs(x):g} games {'behind' if x > 0 else 'ahead of'} {place}"


def _ord(n: int) -> str:
    return "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


def build(day: dt.date, stats: pd.DataFrame, games: pd.DataFrame, teams: list[dict], injuries: list[dict],
          schedule: list[dict], season: int) -> dict:
    asof = day.isoformat()
    s, g_done = prepare(stats, games, asof)
    tg = team_games(s)
    st = standings(g_done, teams, season).set_index("team_id")
    dvp = defense_vs_position(s, season)
    prof = team_profile(tg, season)
    abbr = {str(t["id"]): t["abbreviation"] for t in teams}
    inj_by_team = defaultdict(list)
    for r in injuries:
        inj_by_team[str(r.get("team_id"))].append(r)
    slate = games[(games.date == asof)]
    report = {"date": asof, "season": season, "games": [], "notes": []}
    sched = {(x["date"], x["home"], x["away"]): x for x in schedule}
    for _, gm in slate.iterrows():
        h, a = gm.home_id, gm.away_id
        sc = sched.get((asof, gm.home, gm.away)) or {}
        game = {"matchup": f"{gm.away} @ {gm.home}", "home": gm.home, "away": gm.away,
                "type": ("NBA Cup — " + " ".join(x for x in (sc.get("label"), sc.get("sublabel")) if x).strip(" —"))
                if sc.get("cup") else ("Regular season" if sc else "Regular season (official schedule not loaded)"),
                "cup": bool(sc.get("cup")), "teams": {}}
        for tid, oid, side in ((h, a, "home"), (a, h, "away")):
            T = {"abbr": abbr.get(tid, tid), "side": side}
            if tid in st.index:
                r = st.loc[tid]
                T["standing"] = {k: (None if isinstance(r[k], float) and math.isnan(r[k]) else
                                     (round(float(r[k]), 3) if isinstance(r[k], (float, np.floating)) else r[k]))
                                 for k in ("w", "l", "conf", "conf_rank", "gb_1", "gb_6", "gb_10", "home_rec", "away_rec",
                                           "last10", "streak", "margin") if k in r}
            T["fatigue"] = fatigue(tg, tid, asof)
            if tid in prof.index:
                pr = prof.loc[tid]
                T["profile"] = {k: round(float(pr[k]), 1) for k in ("ortg", "drtg", "net", "pace")} | \
                    {k: int(pr[k]) for k in ("rk_ortg", "rk_drtg_best", "rk_pace")}
                T["strengths"], T["weaknesses"] = strengths_weaknesses(tid, prof, dvp)
            T["injuries"] = [{k: r.get(k) for k in ("player", "player_id", "pos", "status", "return_date", "description")}
                             for r in inj_by_team.get(tid, [])]
            out_ids = {str(r["player_id"]) for r in inj_by_team.get(tid, []) if str(r.get("status", "")).lower().startswith(OUT_STATUSES)}
            lines = player_lines(s, tid, season)
            T["players"] = []
            if len(lines):
                key = lines[(lines.min_l10 >= KEY_MIN) & (~lines.player_id.isin(out_ids))].head(8)
                lead_guard = key[key.grp == "G"].sort_values("ast", ascending=False).head(1).player_id.tolist()
                for _, pl in key.iterrows():
                    grp = "LG" if pl.player_id in lead_guard else pl.grp
                    P = {"player": pl.player, "pos": pl.pos, "role": "lead guard" if grp == "LG" else pl.grp,
                         "gp": int(pl.gp), "season": {k: round(pl[k], 1) for k in STATS + ["min"]},
                         "l5": {k: round(pl[f"{k}_l5"], 1) for k in STATS + ["min"]},
                         "l10": {k: round(pl[f"{k}_l10"], 1) for k in STATS}, "min_last3": [round(x) for x in pl.min_last3]}
                    # opponent's defense against his position
                    if oid in dvp.index:
                        dv = dvp.loc[oid]
                        P["opp_vs_pos"] = {st_: {"allowed": round(float(dv[f"{st_}_{grp}"]), 1), "rank": int(dv[f"rk_{st_}_{grp}"])}
                                           for st_ in STATS if f"{st_}_{grp}" in dv}
                        soft = [st_ for st_, v in P["opp_vs_pos"].items() if v["rank"] <= 8]
                        tough = [st_ for st_, v in P["opp_vs_pos"].items() if v["rank"] >= 23]
                        P["matchup"] = {"soft": soft, "tough": tough}
                        P["vs_similar"] = {}
                        for st_ in soft:
                            n, line = vs_weak_defenses(s, dvp, pl.player_id, f"{st_}_{grp}", season=season)
                            if n:
                                P["vs_similar"][st_] = {"n": n, **{k: round(v, 1) for k, v in line.items()}}
                    P["h2h"] = head_to_head(s, pl.player_id, oid)
                    T["players"].append(P)
            # injury impact (with / without) for absent key players
            T["injury_impact"] = []
            for r in inj_by_team.get(tid, []):
                pid = str(r["player_id"])
                hist = s[(s.player_id == pid) & (s.season.isin([season, season - 1])) & s.played]
                if hist.empty or hist.tail(10)["min"].mean() < 15:
                    continue
                ww = with_without(s, tid, pid, season)
                T["injury_impact"].append({"player": r["player"], "status": r.get("status"),
                                           "his_min": round(hist.tail(10)["min"].mean(), 1),
                                           "his_pts": round(hist.tail(10)["pts"].mean(), 1), **ww})
            game["teams"][side] = T
        game["mismatches"] = mismatches(game)
        report["games"].append(game)
    return report


def mismatches(game: dict) -> list[str]:
    out = []
    for side, other in (("home", "away"), ("away", "home")):
        T = game["teams"].get(side, {})
        for P in T.get("players", []):
            for st_ in (P.get("matchup") or {}).get("soft", []):
                v = P["opp_vs_pos"][st_]
                if v["rank"] <= 5 and P["season"][st_] >= (2 if st_ != "pts" else 12):
                    out.append(f"{P['player']} ({T['abbr']}, {P['role']}) vs {game['teams'][other]['abbr']}: "
                               f"they allow the {v['rank']}{_ord(v['rank'])}-most {LABEL[st_]} to {ROLE_PL[P['role']]} "
                               f"({v['allowed']} per game); he averages {P['season'][st_]} ({P['l5'][st_]} last 5)")
            for st_ in (P.get("matchup") or {}).get("tough", []):
                v = P["opp_vs_pos"][st_]
                if v["rank"] >= 28 and P["season"][st_] >= (2 if st_ != "pts" else 15):
                    out.append(f"Tough: {P['player']} ({T['abbr']}) — {game['teams'][other]['abbr']} allow the "
                               f"{31 - v['rank']}{_ord(31 - v['rank'])}-fewest {LABEL[st_]} to {ROLE_PL[P['role']]} ({v['allowed']})")
    return out


def to_markdown(rep: dict) -> str:
    L = [f"# NBA slate report — {rep['date']}", "",
         "Our own numbers: balldontlie box scores and injury report, official NBA schedule for game type. Ranks are 1-30; "
         "for 'allowed' stats, #1 allows the most. Key players: 20+ minutes over their last 10.", ""]
    for g in rep["games"]:
        L += [f"## {g['matchup']} · {g['type']}", ""]
        for side in ("away", "home"):
            T = g["teams"][side]
            s_ = T.get("standing", {})
            f = T["fatigue"]
            L.append(f"### {T['abbr']} — {s_.get('w', '?')}-{s_.get('l', '?')}, #{s_.get('conf_rank', '?')} in the {s_.get('conf', '?')}")
            L.append(f"- **Standing:** {_gb(s_.get('gb_1'), '1st')} · {_gb(s_.get('gb_6'), '6th (last guaranteed playoff spot)')} · "
                     f"{_gb(s_.get('gb_10'), '10th (last play-in spot)')} · last 10 {s_.get('last10')} · streak {s_.get('streak')} · "
                     f"home {s_.get('home_rec')} / away {s_.get('away_rec')} · avg margin {_f(s_.get('margin'), 1)}")
            mot = []
            if f["b2b"]:
                mot.append("second night of a back-to-back")
            if f.get("rest_days") is not None and f["rest_days"] >= 2:
                mot.append(f"{f['rest_days']} days' rest")
            if f["games_last7"] >= 4:
                mot.append(f"{f['games_last7']} games in 7 days")
            if g["cup"]:
                mot.append("NBA Cup group game: it counts in the standings and point differential is a Cup tiebreaker")
            if s_.get("gb_6") is not None and -1.5 <= s_["gb_6"] <= 1.5:
                mot.append("within 1.5 games of the 6th seed line (top-6 avoids the play-in)")
            if s_.get("streak", "").startswith("L") and int(s_["streak"][1:]) >= 3:
                mot.append(f"on a {s_['streak'][1:]}-game losing streak")
            L.append(f"- **Motivation and schedule signals:** {'; '.join(mot) if mot else 'none stand out'}")
            pr = T.get("profile")
            if pr:
                L.append(f"- **Profile:** offense #{pr['rk_ortg']} ({pr['ortg']}), defense #{pr['rk_drtg_best']} ({pr['drtg']}), "
                         f"net {pr['net']:+.1f}, pace #{pr['rk_pace']} ({pr['pace']})")
            if T.get("strengths"):
                L.append("- **Strengths:** " + "; ".join(T["strengths"]))
            if T.get("weaknesses"):
                L.append("- **Weaknesses:** " + "; ".join(T["weaknesses"]))
            if T["injuries"]:
                L.append("- **Injury report:** " + "; ".join(f"{r['player']} — {r['status']}" +
                                                             (f" (return {r['return_date']})" if r.get("return_date") else "")
                                                             for r in T["injuries"]))
            for imp in T["injury_impact"]:
                small = " — small sample, treat as a hint" if imp["n_without"] < 5 else ""
                L.append(f"- **Without {imp['player']}** ({imp['status']}; {imp['his_min']} min / {imp['his_pts']} pts last 10) — "
                         f"{imp['n_without']} games without vs {imp['n_with']} with{small}:")
                for r in imp["rows"][:6]:
                    L.append(f"  - {r['player']}: {r['min_with']:.1f} → {r['min_without']:.1f} min, {r['pts_with']:.1f} → "
                             f"{r['pts_without']:.1f} pts, {r['reb_with']:.1f} → {r['reb_without']:.1f} reb, "
                             f"{r['ast_with']:.1f} → {r['ast_without']:.1f} ast, {r['fga_with']:.1f} → {r['fga_without']:.1f} FGA "
                             f"(n {r['n_with']}/{r['n_without']})")
            L.append("")
            L.append("| Player | Role | Season pts/reb/ast/3PM/min | Last 5 | Min last 3 | vs opp defense (rank allowed) |")
            L.append("|---|---|---|---|---|---|")
            for P in T["players"]:
                sv, l5 = P["season"], P["l5"]
                opp = P.get("opp_vs_pos", {})
                ov = ", ".join(f"{LABEL[k]} #{v['rank']}" for k, v in opp.items())
                L.append(f"| {P['player']} | {P['role']} | {sv['pts']}/{sv['reb']}/{sv['ast']}/{sv['fg3m']}/{sv['min']} | "
                         f"{l5['pts']}/{l5['reb']}/{l5['ast']}/{l5['fg3m']}/{l5['min']} | {', '.join(map(str, P['min_last3']))} | {ov} |")
            for P in T["players"]:
                extra = []
                for st_, v in (P.get("vs_similar") or {}).items():
                    if v["n"] < 3:
                        continue
                    extra.append(f"vs the 8 defenses that allow the most {LABEL[st_]} to {ROLE_PL[P['role']]}: {v.get(st_)} {LABEL[st_]} "
                                 f"in {v['n']} games (season {P['season'][st_]})")
                if P["h2h"]:
                    extra.append("H2H: " + "; ".join(f"{x['date']} {x['pts']:.0f}p/{x['reb']:.0f}r/{x['ast']:.0f}a in {x['min']:.0f} min"
                                                     for x in P["h2h"]))
                if extra:
                    L.append(f"- **{P['player']}** — " + " · ".join(extra))
            L.append("")
        if g["mismatches"]:
            L += ["**Mismatches to look at:**"] + [f"- {m}" for m in g["mismatches"]] + [""]
    return "\n".join(L) + "\n"
