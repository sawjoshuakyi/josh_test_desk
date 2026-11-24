"""Soccer line-ups and tennis withdrawals check (runs hourly).

Soccer: once ESPN publishes a fixture's starting XI (~1 hour before kickoff), every slip leg on that fixture is
re-checked: a shots-on-target leg on a player who is benched or absent, and big attacking absences that move the
team's expected goals/shots, are posted to the tennis/soccer Discord channel. Each fixture is reported once.
Tennis: a match on today's slips that ESPN shows as withdrawn/walkover, or with a changed opponent, is posted.
State: data/late_news_state.json (committed) so a fixture is never reported twice.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from desk import config, discord
from desk.nba.live import espn, norm
from desk.soccer import data as sdata

STATE = os.path.join(ROOT, "data", "late_news_state.json")
CODE_TO_LEAGUE = {code: slug for slug, (_k, code) in sdata.LEAGUES.items()}


def load_state():
    return json.load(open(STATE)) if os.path.exists(STATE) else {}


def _name_match(a: str, b: str) -> bool:
    a, b = norm(a), norm(b)
    if a == b:
        return True
    ta, tb = a.split(), b.split()
    return bool(ta and tb) and ta[-1] == tb[-1] and ta[0][:1] == tb[0][:1]


def soccer_af(day, legs, state, posts, fixtures):
    """API-Football line-ups for boards built from API-Football data (fixtures carry fixture_id)."""
    from desk.soccer import apifootball as af
    from desk.soccer.data import same_team
    by_fx = {}
    for slip, leg in legs:
        if leg.get("league") not in af.CODE_TO_ID or len(leg.get("teams", [])) != 2:
            continue
        t1, t2 = leg["teams"]
        fx = next((f for f in fixtures if (same_team(f["home"], t1) and same_team(f["away"], t2))
                   or (same_team(f["home"], t2) and same_team(f["away"], t1))), None)
        if fx:
            by_fx.setdefault(fx["fixture_id"], (fx, []))[1].append((slip, leg))
    for fid, (fx, items) in by_fx.items():
        key = f"soccer-af-{fid}"
        if state.get(key):
            continue
        try:
            info = af.get("fixtures", id=fid)
            started = bool(info) and info[0]["fixture"]["status"]["short"] not in ("NS", "TBD")
            if started and not os.environ.get("LATE_NEWS_TEST"):
                continue
            ups = af.lineups(fid)
        except af.APIFootballError as err:
            print("lineups failed", fid, err)
            continue
        xi = []
        for t in ups:
            xi += [(p["player"]["name"], True) for p in t.get("startXI") or []]
            xi += [(p["player"]["name"], False) for p in t.get("substitutes") or []]
        if not any(st for _, st in xi):
            continue  # line-ups not out yet

        def status(name):
            hits = [st for n, st in xi if _name_match(n, name)]
            return None if not hits else any(hits)
        lines = []
        for side in ("home", "away"):
            exp = sorted([p for p in fx["players"] if p.get("role") == "projected starter" and p["team"] == fx[side]],
                         key=lambda p: -p["sot_mean"])
            missing = [p for p in exp[:4] if not status(p["player"])]
            if missing:
                lost = sum(p["sot_mean"] for p in missing)
                lines.append(f"• {fx[side]}: not starting — " + ", ".join(p["player"] for p in missing) +
                             f" (≈{lost:.1f} of the team's projected {fx['sot_' + side]:.1f} shots on target)")
        for slip, leg in items:
            if leg.get("player"):
                st = status(leg["player"])
                if st is None:
                    lines.append(f"• ⚠️ **{leg['player']}** is not in the match-day squad — {leg.get('stat')} leg is dead · _{slip}_")
                elif st is False:
                    lines.append(f"• ⚠️ **{leg['player']}** is on the **bench** — {leg.get('stat')} {leg.get('min', '')}+ "
                                 f"leg now needs him to come on · _{slip}_")
        title = f"{fx['home']} v {fx['away']} — line-ups are out"
        posts.append({"title": ("🚨 " if lines else "🟢 ") + title, "color": 0xE67E22 if lines else 0x2ECC71,
                      "description": "\n".join(lines) if lines else "All projected starters on our legs are in the XI."})
        state[key] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def soccer(day, legs, state, posts):
    board_path = os.path.join(ROOT, "boards", f"{day}-am.json")
    fixtures = json.load(open(board_path)).get("soccer", {}).get("fixtures", []) if os.path.exists(board_path) else []
    if fixtures and "fixture_id" in fixtures[0]:
        return soccer_af(day, legs, state, posts, fixtures)
    # boards built before the API-Football switch (ESPN fixtures) — transition only
    by_fixture = {}
    for slip, leg in legs:
        if leg.get("league") in CODE_TO_LEAGUE:
            by_fixture.setdefault((leg["league"], tuple(leg["teams"])), []).append((slip, leg))
    board_path = os.path.join(ROOT, "boards", f"{day}-am.json")
    fixtures = json.load(open(board_path)).get("soccer", {}).get("fixtures", []) if os.path.exists(board_path) else []
    for (code, teams), items in by_fixture.items():
        slug = CODE_TO_LEAGUE[code]
        sb = espn(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={day:%Y%m%d}")
        for ev in sb.get("events", []):
            comp = ev["competitions"][0]
            names = {c["team"].get("abbreviation", "").upper() for c in comp["competitors"]} | \
                    {c["team"].get("displayName", "").upper() for c in comp["competitors"]}
            if not all(t.upper() in names for t in teams):
                continue
            key = f"soccer-{ev['id']}"
            started = comp.get("status", {}).get("type", {}).get("state") != "pre"
            if state.get(key) or (started and not os.environ.get("LATE_NEWS_TEST")):
                break
            summ = espn(f"https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/summary?event={ev['id']}")
            xi = {}
            for r in summ.get("rosters", []):
                for p in r.get("roster", []):
                    xi[norm(p["athlete"].get("displayName", ""))] = bool(p.get("starter"))
            if not any(xi.values()):
                break  # line-ups not out yet
            fx = next((f for f in fixtures if f["espn_id"] == ev["id"]), None)
            lines = []
            if fx:
                for side in ("home", "away"):
                    exp = sorted([p for p in fx["players"] if p.get("role") == "projected starter"
                                  and p["team"] == fx[side]], key=lambda p: -p["sot_mean"])
                    missing = [p for p in exp[:4] if not xi.get(norm(p["player"]), False)]
                    if missing:
                        lost = sum(p["sot_mean"] for p in missing)
                        lines.append(f"• {fx[side]}: not starting — " + ", ".join(p["player"] for p in missing) +
                                     f" (≈{lost:.1f} of the team's projected {fx['sot_' + side]:.1f} shots on target)")
            for slip, leg in items:
                if leg.get("player"):
                    st = xi.get(norm(leg["player"]))
                    if st is None:
                        lines.append(f"• ⚠️ **{leg['player']}** is not in the match-day squad — {leg.get('stat')} leg is dead · _{slip}_")
                    elif st is False:
                        lines.append(f"• ⚠️ **{leg['player']}** is on the **bench** — {leg.get('stat')} {leg.get('min', '')}+ "
                                     f"leg now needs him to come on · _{slip}_")
            title = f"{ev.get('name')} — line-ups are out"
            posts.append({"title": ("🚨 " if lines else "🟢 ") + title, "color": 0xE67E22 if lines else 0x2ECC71,
                          "description": "\n".join(lines) if lines else "All projected starters on our legs are in the XI."})
            state[key] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            break


def tennis(day, legs, state, posts):
    for slip, leg in legs:
        if leg.get("league") not in ("atp", "wta"):
            continue
        key = f"tennis-{'-'.join(leg['teams'])}-{day}"
        if state.get(key):
            continue
        sb = espn(f"https://site.api.espn.com/apis/site/v2/sports/tennis/{leg['league']}/scoreboard?dates={day:%Y%m%d}")
        found = None
        for ev in sb.get("events", []):
            for g in ev.get("groupings", []):
                for c in g.get("competitions", []):
                    nm = {norm((x.get("athlete") or {}).get("displayName", "")) for x in c.get("competitors", [])}
                    if any(norm(t) in nm for t in leg["teams"]):
                        found = (c, nm)
        if not found:
            continue
        c, nm = found
        st = c.get("status", {}).get("type", {})
        detail = (st.get("shortDetail") or st.get("description") or "").lower()
        if "walkover" in detail or "withdr" in detail or not all(norm(t) in nm for t in leg["teams"]):
            posts.append({"title": f"🚨 Tennis: {' v '.join(leg['teams'])}", "color": 0xE67E22,
                          "description": f"ESPN shows **{st.get('shortDetail') or 'a changed draw'}** — the leg may be void or "
                                         f"face a different opponent · _{slip}_"})
            state[key] = "posted"


def main():
    day = dt.date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else config.et_today()
    path = os.environ.get("LEGS_FILE") or os.path.join(ROOT, "legs", f"{day}-am.json")
    if not os.path.exists(path):
        print("no AM legs")
        return
    legs = [(s["name"], leg) for s in json.load(open(path)).get("slips", []) for leg in s.get("legs", [])]
    state, posts = load_state(), []
    soccer(day, legs, state, posts)
    tennis(day, legs, state, posts)
    if posts:
        discord.post("tennis_soccer", posts)
        if not os.environ.get("LATE_NEWS_TEST"):
            json.dump(state, open(STATE, "w"), indent=1)
    print(f"{len(posts)} alerts")


if __name__ == "__main__":
    main()
