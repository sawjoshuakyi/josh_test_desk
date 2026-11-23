#!/usr/bin/env python3
"""
Betting Desk live leg tracker.

Polls ESPN's public scoreboard/box-score feeds and posts to a Discord webhook
the moment a leg hits (overs as soon as the number is reached; unders,
moneylines and spreads at the final). Uses only the Python standard library.

Usage:
  DISCORD_LIVE_WEBHOOK=https://discord.com/api/webhooks/... python3 tracker.py legs.json
Options (environment variables):
  POLL_SECONDS   seconds between checks (default 60)
  MAX_MINUTES    stop after this many minutes (default 330)
  ALERT_MISSES   1 = also post misses and busted slips (default 1)
  DRY_RUN        1 = print alerts instead of posting to Discord
  STATE_FILE     where already-sent alerts are remembered (default state-<date>.json)
"""
import json, os, sys, time, unicodedata, urllib.request, urllib.error

ESPN = "https://site.api.espn.com/apis/site/v2/sports/{path}"
SPORT_PATHS = {
    "nba": "basketball/nba",
    "nfl": "football/nfl",
    "ncaaf": "football/college-football",
    "epl": "soccer/eng.1", "laliga": "soccer/esp.1", "seriea": "soccer/ita.1",
    "bundesliga": "soccer/ger.1", "ligue1": "soccer/fra.1", "ucl": "soccer/uefa.champions",
    "mls": "soccer/usa.1",
    "atp": "tennis/atp", "wta": "tennis/wta",
}
# player stat -> how to compute it from ESPN box-score keys
NBA_STATS = {
    "pts": ["points"], "reb": ["rebounds"], "ast": ["assists"], "stl": ["steals"],
    "blk": ["blocks"], "threes": ["threePointFieldGoalsMade"],
    "pra": ["points", "rebounds", "assists"], "pr": ["points", "rebounds"],
    "pa": ["points", "assists"], "ra": ["rebounds", "assists"],
}
NFL_STATS = {
    "pass_yds": ["passing.passingYards"], "pass_td": ["passing.passingTouchdowns"],
    "pass_cmp": ["passing.completions"],
    "rush_yds": ["rushing.rushingYards"], "rush_att": ["rushing.rushingAttempts"],
    "rec": ["receiving.receptions"], "rec_yds": ["receiving.receivingYards"],
    "rush_rec_yds": ["rushing.rushingYards", "receiving.receivingYards"],
    "td": ["rushing.rushingTouchdowns", "receiving.receivingTouchdowns"],
}
LABELS = {"pts": "PTS", "reb": "REB", "ast": "AST", "stl": "STL", "blk": "BLK", "threes": "3PM",
          "pra": "PRA", "pr": "P+R", "pa": "P+A", "ra": "R+A", "pass_yds": "pass yds",
          "pass_td": "pass TD", "pass_cmp": "completions", "rush_yds": "rush yds",
          "rush_att": "carries", "rec": "rec", "rec_yds": "rec yds", "rush_rec_yds": "rush+rec yds",
          "td": "TD"}

def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return "".join(ch for ch in s.lower() if ch.isalnum() or ch == " ").replace(" jr", "").replace(" iii", "").replace(" ii", "").strip()

def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 BettingDeskTracker/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

# ---------------------------------------------------------------- ESPN data
class Feed:
    def __init__(self, date):
        self.date = date.replace("-", "")
        self.scoreboards, self.summaries = {}, {}

    def reset(self):
        self.scoreboards, self.summaries = {}, {}

    def events(self, league):
        if league not in self.scoreboards:
            data = get_json(ESPN.format(path=SPORT_PATHS[league]) + f"/scoreboard?dates={self.date}")
            self.scoreboards[league] = data.get("events", [])
        return self.scoreboards[league]

    def find_event(self, league, teams):
        want = {t.upper() for t in teams}
        for e in self.events(league):
            comp = e["competitions"][0]
            abbrs = set()
            for c in comp["competitors"]:
                for key in ("team", "athlete"):
                    obj = c.get(key) or {}
                    for f in ("abbreviation", "shortDisplayName", "displayName"):
                        if obj.get(f):
                            abbrs.add(obj[f].upper())
            if want & abbrs and (len(want) == 1 or want <= abbrs or len(want & abbrs) >= 1):
                return e
        return None

    def summary(self, league, event_id):
        key = (league, event_id)
        if key not in self.summaries:
            self.summaries[key] = get_json(ESPN.format(path=SPORT_PATHS[league]) + f"/summary?event={event_id}")
        return self.summaries[key]

def game_status(event):
    st = event["competitions"][0]["status"]
    t = st["type"]
    return t.get("state"), t.get("completed", False), t.get("shortDetail") or t.get("description", "")

def team_scores(event):
    out = {}
    for c in event["competitions"][0]["competitors"]:
        abbr = ((c.get("team") or {}).get("abbreviation") or (c.get("athlete") or {}).get("shortName") or "").upper()
        try:
            score = float(c.get("score") or 0)
        except ValueError:
            score = 0.0
        out[abbr] = {"score": score, "winner": c.get("winner", False), "home": c.get("homeAway") == "home"}
    return out

def player_stat(league, summary, player, stat):
    """Return (value or None if player not in box score)."""
    target = norm(player)
    for team in summary.get("boxscore", {}).get("players", []):
        for cat in team.get("statistics", []):
            keys = cat.get("keys", [])
            for a in cat.get("athletes", []):
                name = norm(a.get("athlete", {}).get("displayName", ""))
                if name != target and not (target.split()[-1] == name.split()[-1] and target[0] == name[:1]):
                    continue
                if a.get("didNotPlay") or (league == "nba" and not a.get("stats")):
                    return None
                return _compute(league, team, player, stat)
    return None

def _compute(league, team_block, player, stat):
    target = norm(player)
    total, found = 0.0, False
    parts = NBA_STATS[stat] if league == "nba" else NFL_STATS[stat]
    for part in parts:
        cat_name, key = (part.split(".", 1) + [None])[:2] if "." in part else (None, part)
        for cat in team_block.get("statistics", []):
            if cat_name and cat.get("name") != cat_name:
                continue
            keys = cat.get("keys", [])
            for a in cat.get("athletes", []):
                name = norm(a.get("athlete", {}).get("displayName", ""))
                if name != target and not (target.split()[-1] == name.split()[-1] and target[0] == name[:1]):
                    continue
                stats = a.get("stats", [])
                for i, k in enumerate(keys):
                    pieces = k.replace("/", "-").split("-")
                    if key in pieces and i < len(stats):
                        raw = stats[i].replace("/", "-").split("-")[pieces.index(key)]
                        try:
                            total += float(raw); found = True
                        except ValueError:
                            pass
    return total if found else 0.0

# ---------------------------------------------------------------- legs
def leg_key(leg):
    return json.dumps({k: leg.get(k) for k in ("league", "teams", "type", "player", "stat", "min", "max", "team", "line", "dir")}, sort_keys=True)

def describe(leg):
    t = leg.get("type", "player")
    if t == "player":
        lab = LABELS.get(leg["stat"], leg["stat"])
        if "min" in leg:
            return f"{leg['player']} {leg['min']:g}+ {lab}"
        return f"{leg['player']} {leg['max']:g} or fewer {lab}"
    if t == "moneyline":
        return f"{leg['team']} to win"
    if t == "spread":
        return f"{leg['team']} {leg['line']:+g}"
    if t == "total":
        return f"{leg['dir'].title()} {leg['line']:g} ({'/'.join(leg['teams'])})"
    return leg.get("label", t)

def evaluate(feed, leg):
    """Return (status, detail) where status is pending/hit/miss/void."""
    event = feed.find_event(leg["league"], leg["teams"])
    if not event:
        return "pending", "game not found yet"
    state, done, clock = game_status(event)
    if state == "pre":
        return "pending", "not started"
    t = leg.get("type", "player")
    if t == "player":
        summ = feed.summary(leg["league"], event["id"])
        val = player_stat(leg["league"], summ, leg["player"], leg["stat"])
        lab = LABELS.get(leg["stat"], leg["stat"])
        if val is None:
            return ("void", "did not play") if done else ("pending", "not in box score yet")
        if "min" in leg:
            if val >= leg["min"]:
                return "hit", f"{val:g} {lab} · {clock}"
            return ("miss", f"finished with {val:g} {lab}") if done else ("pending", f"{val:g} {lab} · {clock}")
        if val > leg["max"]:
            return "miss", f"{val:g} {lab} · {clock}"
        return ("hit", f"finished with {val:g} {lab}") if done else ("pending", f"{val:g} {lab} · {clock}")
    scores = team_scores(event)
    if t == "total":
        tot = sum(s["score"] for s in scores.values())
        if leg["dir"] == "over":
            if tot > leg["line"]:
                return "hit", f"{tot:g} total · {clock}"
            return ("miss", f"final total {tot:g}") if done else ("pending", f"{tot:g} total · {clock}")
        if tot > leg["line"]:
            return "miss", f"{tot:g} total · {clock}"
        return ("hit", f"final total {tot:g}") if done else ("pending", f"{tot:g} total · {clock}")
    team = leg["team"].upper()
    if team not in scores:
        return "pending", f"team {team} not matched"
    mine = scores[team]["score"]
    other = max(s["score"] for k, s in scores.items() if k != team) if len(scores) > 1 else 0
    if not done:
        return "pending", f"{team} {mine:g}-{other:g} · {clock}"
    if t == "moneyline":
        return ("hit" if mine > other else "miss"), f"final {team} {mine:g}-{other:g}"
    if t == "spread":
        margin = mine + leg["line"] - other
        if margin == 0:
            return "void", f"push · final {team} {mine:g}-{other:g}"
        return ("hit" if margin > 0 else "miss"), f"final {team} {mine:g}-{other:g}"
    return "pending", "unknown leg type"

# ---------------------------------------------------------------- discord
def post(webhook, embeds, content=None, dry=False):
    payload = {"username": "Betting Desk · Live", "embeds": embeds}
    if content:
        payload["content"] = content
    if dry:
        print(json.dumps(payload, indent=1)); return
    req = urllib.request.Request(webhook, data=json.dumps(payload).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "BettingDeskTracker/1.0"})
    for _ in range(3):
        try:
            urllib.request.urlopen(req, timeout=15); return
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 2)) + 0.5)
            else:
                print("discord error", e.code, file=sys.stderr); return
        except Exception as e:  # network blip
            print("discord error", e, file=sys.stderr); time.sleep(3)

# ---------------------------------------------------------------- main loop
def main():
    legs_path = sys.argv[1] if len(sys.argv) > 1 else "legs.json"
    book = json.load(open(legs_path))
    webhook = os.environ.get("DISCORD_LIVE_WEBHOOK", "")
    dry = os.environ.get("DRY_RUN") == "1"
    if not webhook and not dry:
        sys.exit("Set DISCORD_LIVE_WEBHOOK (or DRY_RUN=1).")
    poll = int(os.environ.get("POLL_SECONDS", "60"))
    max_min = int(os.environ.get("MAX_MINUTES", "330"))
    alert_misses = os.environ.get("ALERT_MISSES", "1") == "1"
    state_path = os.environ.get("STATE_FILE", f"state-{book['date']}.json")
    state = json.load(open(state_path)) if os.path.exists(state_path) else {"legs": {}, "slips": {}}

    # unique legs -> which slips use them
    unique, users = {}, {}
    for slip in book["slips"]:
        for leg in slip["legs"]:
            k = leg_key(leg)
            unique[k] = leg
            users.setdefault(k, []).append(slip["name"])

    feed = Feed(book["date"])
    start = time.time()
    if not state.get("started"):
        n = len(book["slips"])
        post(webhook, [{"title": f"🔴 Live tracking started · {book['date']}", "color": 0x95A5A6,
                        "description": f"Tracking {len(unique)} unique legs across {n} slips:\n" +
                                       "\n".join(f"• {s['name']} ({len(s['legs'])} legs)" for s in book["slips"])}], dry=dry)
        state["started"] = True

    while True:
        feed.reset()
        alerts = []
        for k, leg in unique.items():
            if state["legs"].get(k, {}).get("status") in ("hit", "miss", "void"):
                continue
            try:
                status, detail = evaluate(feed, leg)
            except Exception as e:
                status, detail = "pending", f"feed error: {e}"
            if status in ("hit", "miss", "void"):
                state["legs"][k] = {"status": status, "detail": detail}
                if status == "hit" or alert_misses or status == "void":
                    alerts.append((status, leg, detail, users[k]))
        # slip progress
        slip_msgs = []
        for slip in book["slips"]:
            res = [state["legs"].get(leg_key(l), {}).get("status", "pending") for l in slip["legs"]]
            hit, miss, void = res.count("hit"), res.count("miss"), res.count("void")
            live = len(res) - hit - miss - void
            prev = state["slips"].get(slip["name"])
            now = "busted" if miss else ("cashed" if live == 0 else "live")
            if now != prev and now in ("cashed", "busted"):
                if now == "cashed" or alert_misses:
                    slip_msgs.append((now, slip, hit, len(res), void))
            state["slips"][slip["name"]] = now
        icon = {"hit": ("✅ HIT", 0x2ECC71), "miss": ("❌ MISS", 0xE74C3C), "void": ("⚪ VOID", 0x95A5A6)}
        embeds = []
        for status, leg, detail, used in alerts:
            title, color = icon[status]
            embeds.append({"title": f"{title} — {describe(leg)}", "color": color,
                           "description": f"{detail}\nOn: " + ", ".join(used)})
        for now, slip, hit, total, void in slip_msgs:
            if now == "cashed":
                embeds.append({"title": f"💰 SLIP CASHED — {slip['name']}", "color": 0xF1C40F,
                               "description": f"All legs in ({hit}/{total} hit{', ' + str(void) + ' void' if void else ''})." +
                                              (f" Odds {slip['odds']}" if slip.get("odds") else "")})
            else:
                embeds.append({"title": f"💥 Slip busted — {slip['name']}", "color": 0x7F8C8D,
                               "description": f"{hit}/{total} legs hit before the miss."})
        for i in range(0, len(embeds), 10):
            post(webhook, embeds[i:i + 10], dry=dry)
        json.dump(state, open(state_path, "w"), indent=1)

        settled = all(state["legs"].get(k, {}).get("status") in ("hit", "miss", "void") for k in unique)
        if settled:
            post(webhook, [{"title": "🏁 All legs settled", "color": 0x95A5A6,
                            "description": "\n".join(f"• {s['name']}: {state['slips'].get(s['name'])}" for s in book["slips"])}], dry=dry)
            break
        if time.time() - start > max_min * 60:
            print("max runtime reached; state saved, rerun to continue")
            break
        time.sleep(poll)

if __name__ == "__main__":
    main()
