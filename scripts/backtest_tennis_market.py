"""Tennis Elo vs the market: Pinnacle closing odds from tennis-data.co.uk (runs on GitHub Actions).

For every 2025-2026 ATP/WTA match found in both sources, compares the model's pre-match win
probability with Pinnacle's no-vig closing probability, and simulates flat 1-unit bets at
Pinnacle's closing price whenever the model's edge exceeds a threshold. Beating Pinnacle's close
is the hardest test in tennis; a model that cannot do it has no edge there.
"""
import io, json, math, os, sys, urllib.request
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from desk.tennis.elo import Elo, EloParams, is_completed
from desk.tennis.data import all_matches
from desk import pricing

URLS = {("atp", y): f"http://www.tennis-data.co.uk/{y}/{y}.xlsx" for y in (2025, 2026)}
URLS.update({("wta", y): f"http://www.tennis-data.co.uk/{y}w/{y}.xlsx" for y in (2025, 2026)})


def key_full(name: str) -> str:
    t = str(name).replace("-", " ").split()
    return (" ".join(t[1:]) + " " + t[0][0]).lower() if len(t) > 1 else str(name).lower()


def key_td(name: str) -> str:
    s = str(name).strip().replace("-", " ")
    if " " not in s:
        return s.lower()
    last, init = s.rsplit(" ", 1)
    return (last + " " + init[0]).lower()


def load_market():
    frames = []
    for (tour, y), url in URLS.items():
        try:
            raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=60).read()
        except Exception as e:
            print("skip", url, e)
            continue
        d = pd.read_excel(io.BytesIO(raw))
        d["tour"] = tour
        frames.append(d)
    if not frames:
        return None
    m = pd.concat(frames, ignore_index=True)
    m = m.dropna(subset=["PSW", "PSL"])
    m["date"] = pd.to_datetime(m["Date"]).dt.strftime("%Y%m%d").astype(int)
    m["wk"], m["lk"] = m.Winner.map(key_td), m.Loser.map(key_td)
    return m


def main(threshold=0.03):
    market = load_market()
    if market is None:
        json.dump({"status": "unavailable", "reason": "tennis-data.co.uk refused the download (HTTP 403) from GitHub's servers. "
                   "The model-vs-market test now runs on the desk's own closing-line snapshots (scripts/grade_board.py)."},
                  open(os.path.join(ROOT, "reports", "backtest_tennis_market.json"), "w"), indent=1)
        print("market data unavailable; wrote status file")
        return
    index = {}
    for r in market.itertuples():
        index.setdefault((r.tour, r.wk, r.lk), []).append(r)
    df = all_matches().sort_values(["tourney_date", "match_num"], kind="stable")
    rows = []
    for tour, g in df.groupby("tour"):
        elo = Elo(EloParams())
        for r in g.itertuples():
            if not is_completed(r.score):
                continue
            if r.tourney_date >= 20250101:
                cands = index.get((tour, key_full(r.winner_name), key_full(r.loser_name)), [])
                hit = next((c for c in cands if 0 <= c.date - r.tourney_date <= 21 or abs(c.date - r.tourney_date) <= 3), None)
                if hit is not None and elo.n[r.winner_name] >= 10 and elo.n[r.loser_name] >= 10:
                    p_w = elo.predict(r.winner_name, r.loser_name, r.surface, r.best_of)
                    ow, ol = hit.PSW, hit.PSL  # decimal odds
                    mw = (1 / ow) / ((1 / ow) + (1 / ol))
                    rows.append({"tour": tour, "date": r.tourney_date, "p_model_w": p_w, "p_mkt_w": mw, "dec_w": ow, "dec_l": ol})
            elo.update(r.winner_name, r.loser_name, r.surface)
    res = pd.DataFrame(rows)
    ll_model = float((-res.p_model_w.clip(1e-6, 1 - 1e-6).map(math.log)).mean())
    ll_mkt = float((-res.p_mkt_w.clip(1e-6, 1 - 1e-6).map(math.log)).mean())
    bets = []
    for r in res.itertuples():
        e_w = r.p_model_w * r.dec_w - 1
        e_l = (1 - r.p_model_w) * r.dec_l - 1
        if r.p_model_w - r.p_mkt_w > threshold and e_w > 0:
            bets.append(r.dec_w - 1)
        elif (1 - r.p_model_w) - (1 - r.p_mkt_w) > threshold and e_l > 0:
            bets.append(-1.0)
    out = {"matched_matches": len(res), "logloss_model": ll_model, "logloss_pinnacle_close": ll_mkt,
           "bets": len(bets), "units": float(sum(bets)), "roi": float(sum(bets) / len(bets)) if bets else None,
           "threshold": threshold,
           "verdict": "Model beats the Pinnacle close on log loss" if ll_model < ll_mkt else "Pinnacle close is sharper than the model"}
    os.makedirs("reports", exist_ok=True)
    json.dump(out, open("reports/backtest_tennis_market.json", "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
