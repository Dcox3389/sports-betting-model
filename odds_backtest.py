"""
Does the screen actually BEAT THE MARKET?

Accuracy and profit are different questions. An 84%-accurate pick on a favorite
priced at -600 loses money, because -600 already implies 85.7%. This script
answers the only question that matters for betting: staking real money at real
closing prices, what happens?

Uses ESPN's `pickcenter` DraftKings moneylines on completed NBA/WNBA games
(the leagues where ESPN retains odds), replays the same walk-forward Elo the
screen uses, and computes ROI at every confidence threshold.

Flat $100 stakes. No parlays, no compounding.
"""
import json, math, os, csv, urllib.request, concurrent.futures as cf
from collections import defaultdict
from config import DATA, OUT, EVAL_START, EVAL_END, ELO
from fetch_espn import get, split, TEAM_SPAN, WORKERS

BASE = "https://site.api.espn.com/apis/site/v2/sports/"
LEAGUES = {"nba": "basketball/nba", "wnba": "basketball/wnba"}
RANGES = {"nba": [("20241020", "20250625"), ("20251020", "20260803")],
          "wnba": [("20250501", "20251020"), ("20260501", "20260803")]}


def american_to_prob(ml):
    return (-ml) / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def payout(ml, stake=100.0):
    """Profit on a winning bet (excludes returned stake)."""
    return stake * (100 / -ml) if ml < 0 else stake * (ml / 100)


def scoreboards():
    """Games with ESPN event ids (team_games.json doesn't retain them)."""
    jobs = [(lg, f"{BASE}{LEAGUES[lg]}/scoreboard?dates={a}-{b}&limit=1000")
            for lg in LEAGUES for r in RANGES[lg] for a, b in split(*r, TEAM_SPAN)]
    out, seen = [], set()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for (lg, _), data in zip(jobs, ex.map(get, [u for _, u in jobs])):
            for ev in (data or {}).get("events", []):
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                try:
                    c = ev["competitions"][0]
                    if not c["status"]["type"].get("completed"):
                        continue
                    cs = c["competitors"]
                    h = next(x for x in cs if x["homeAway"] == "home")
                    a = next(x for x in cs if x["homeAway"] == "away")
                    hs, as_ = int(h["score"]), int(a["score"])
                    if hs == as_:
                        continue
                    out.append(dict(id=ev["id"], lg=lg, date=ev["date"][:10],
                                    home=h["team"]["displayName"],
                                    away=a["team"]["displayName"],
                                    hs=hs, as_=as_))
                except Exception:
                    continue
    out.sort(key=lambda x: x["date"])
    return out


def fetch_odds(games):
    """DraftKings moneyline per game, from ESPN pickcenter."""
    need = [g for g in games if EVAL_START <= g["date"] <= EVAL_END]
    print(f"fetching odds for {len(need)} games in window...")
    urls = [f"{BASE}{LEAGUES[g['lg']]}/summary?event={g['id']}" for g in need]
    odds = {}
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for g, data in zip(need, ex.map(get, urls)):
            for pc in (data or {}).get("pickcenter", []):
                ho = (pc.get("homeTeamOdds") or {}).get("moneyLine")
                ao = (pc.get("awayTeamOdds") or {}).get("moneyLine")
                if ho and ao:
                    odds[g["id"]] = (float(ho), float(ao),
                                     pc.get("provider", {}).get("name", "?"))
                    break
    print(f"  got moneylines for {len(odds)} ({len(odds)/max(1,len(need)):.0%})")
    return odds


def main():
    cache = os.path.join(DATA, "odds_games.json")
    if os.path.exists(cache):
        games, odds = json.load(open(cache))
        odds = {k: tuple(v) for k, v in odds.items()}
        print(f"loaded cache: {len(games)} games, {len(odds)} with odds")
    else:
        games = scoreboards()
        print(f"games with ids: {len(games)}")
        odds = fetch_odds(games)
        json.dump([games, {k: list(v) for k, v in odds.items()}], open(cache, "w"))

    # ---- replay walk-forward Elo (identical to screen.py) ----
    elo, cnt, rows = defaultdict(lambda: 1500.0), defaultdict(int), []
    for g in games:
        lg = g["lg"]; K, hfa, minp = ELO[lg]
        rh, ra = elo[(lg, g["home"])], elo[(lg, g["away"])]
        p = 1.0 / (1.0 + 10 ** (-((rh + hfa) - ra) / 400.0))
        home_won = g["hs"] > g["as_"]

        if (EVAL_START <= g["date"] <= EVAL_END and g["id"] in odds
                and cnt[(lg, g["home"])] >= minp and cnt[(lg, g["away"])] >= minp):
            ho, ao, prov = odds[g["id"]]
            pick_home = p >= 0.5
            conf = p if pick_home else 1 - p
            ml = ho if pick_home else ao
            won = (pick_home == home_won)
            rows.append(dict(lg=lg, date=g["date"], conf=conf, won=int(won), ml=ml,
                             mkt=american_to_prob(ml), book=prov,
                             pick=(g["home"] if pick_home else g["away"]),
                             profit=(payout(ml) if won else -100.0)))

        d = K * math.log(abs(g["hs"] - g["as_"]) + 1) * ((1.0 if home_won else 0.0) - p)
        elo[(lg, g["home"])] += d; elo[(lg, g["away"])] -= d
        cnt[(lg, g["home"])] += 1; cnt[(lg, g["away"])] += 1

    if not rows:
        print("no priced events"); return
    print(f"\npriced, graded bets: {len(rows)}\n")

    print(f"{'threshold':<12}{'bets':>6}{'win%':>8}{'mkt implied':>13}"
          f"{'edge':>8}{'staked':>10}{'profit':>11}{'ROI':>9}")
    for th in (0.50, 0.60, 0.70, 0.75, 0.80, 0.85, 0.90):
        sub = [r for r in rows if r["conf"] >= th]
        if len(sub) < 20:
            continue
        n = len(sub)
        wr = sum(r["won"] for r in sub) / n
        mkt = sum(r["mkt"] for r in sub) / n
        prof = sum(r["profit"] for r in sub)
        staked = 100.0 * n
        print(f">= {th:<9.0%}{n:>6}{wr:>8.1%}{mkt:>13.1%}{wr-mkt:>+8.1%}"
              f"{staked:>10,.0f}{prof:>+11,.0f}{prof/staked:>+9.2%}")

    print("\nby confidence band (is the model beating the price anywhere?)")
    print(f"{'band':<12}{'bets':>6}{'model says':>12}{'actual':>9}{'market':>9}{'ROI':>9}")
    for lo, hi in [(.5,.6),(.6,.7),(.7,.8),(.8,.85),(.85,.9),(.9,1.01)]:
        sub = [r for r in rows if lo <= r["conf"] < hi]
        if len(sub) < 20:
            continue
        n = len(sub)
        print(f"{f'{lo:.0%}-{hi:.0%}':<12}{n:>6}"
              f"{sum(r['conf'] for r in sub)/n:>12.1%}"
              f"{sum(r['won'] for r in sub)/n:>9.1%}"
              f"{sum(r['mkt'] for r in sub)/n:>9.1%}"
              f"{sum(r['profit'] for r in sub)/(100*n):>+9.2%}")

    path = os.path.join(OUT, "odds_backtest.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
