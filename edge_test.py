"""
Is there real edge against closing lines?

The previous run found +7.2% ROI in the 50-60% confidence band. That band was
found by LOOKING at the results, so testing it on the same data proves nothing
-- with six bands examined, one landing 1.2 SE above zero is expected noise.

This script does it properly:

  1. Expands to four leagues (MLB, NBA, NHL, WNBA) for ~5x the sample.
  2. Reframes the question. "Confidence band" is the wrong axis. What matters
     is whether our probability beats the market's DEVIGGED probability:
         edge = model_p - fair_market_p
     Betting is only justified where that edge is positive and real.
  3. Guards against the multiple-comparisons trap two ways:
       TIME  split -- choose on 2025-06..2026-01, validate on 2026-02..2026-08
       LEAGUE split -- the 50-60% finding came from NBA/WNBA, so MLB/NHL are a
                       genuinely independent test of it
  4. Bootstrap confidence intervals on ROI, because ROI on moneylines is highly
     skewed and a plain t-test understates the spread.

Flat $100 stakes throughout.
"""
import json, math, os, csv, random
import concurrent.futures as cf
from collections import defaultdict
from config import DATA, OUT, EVAL_START, EVAL_END, ELO
from fetch_espn import get, split, TEAM_SPAN, WORKERS

BASE = "https://site.api.espn.com/apis/site/v2/sports/"
PATHS = {"mlb": "baseball/mlb", "nba": "basketball/nba",
         "nhl": "hockey/nhl", "wnba": "basketball/wnba"}
RANGES = {
    "mlb":  [("20250320", "20251105"), ("20260320", "20260803")],
    "nba":  [("20241020", "20250625"), ("20251020", "20260803")],
    "nhl":  [("20241005", "20250625"), ("20251005", "20260803")],
    "wnba": [("20250501", "20251020"), ("20260501", "20260803")],
}
SPLIT_DATE = "2026-02-01"      # everything before = in-sample, after = holdout


def am_prob(ml):
    return (-ml) / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def payout(ml, stake=100.0):
    return stake * (100 / -ml) if ml < 0 else stake * (ml / 100)


def scoreboards():
    jobs = [(lg, f"{BASE}{PATHS[lg]}/scoreboard?dates={a}-{b}&limit=1000")
            for lg in PATHS for r in RANGES[lg] for a, b in split(*r, TEAM_SPAN)]
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
                                    away=a["team"]["displayName"], hs=hs, as_=as_))
                except Exception:
                    continue
    out.sort(key=lambda x: x["date"])
    return out


def fetch_odds(games):
    need = [g for g in games if EVAL_START <= g["date"] <= EVAL_END]
    print(f"fetching odds for {len(need)} games...")
    urls = [f"{BASE}{PATHS[g['lg']]}/summary?event={g['id']}" for g in need]
    odds = {}
    done = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for g, data in zip(need, ex.map(get, urls)):
            done += 1
            if done % 1000 == 0:
                print(f"   {done}/{len(need)}")
            for pc in (data or {}).get("pickcenter", []):
                ho = (pc.get("homeTeamOdds") or {}).get("moneyLine")
                ao = (pc.get("awayTeamOdds") or {}).get("moneyLine")
                if ho and ao:
                    odds[g["id"]] = (float(ho), float(ao))
                    break
    print(f"  got {len(odds)} ({len(odds)/max(1,len(need)):.0%})")
    return odds


def boot_ci(profits, n_boot=4000, seed=7):
    if not profits:
        return 0.0, 0.0
    rnd = random.Random(seed)
    n = len(profits)
    means = []
    for _ in range(n_boot):
        means.append(sum(profits[rnd.randrange(n)] for _ in range(n)) / n)
    means.sort()
    return means[int(.025 * n_boot)] / 100.0, means[int(.975 * n_boot)] / 100.0


def build_rows(games, odds):
    elo, cnt, rows = defaultdict(lambda: 1500.0), defaultdict(int), []
    for g in games:
        lg = g["lg"]; K, hfa, minp = ELO[lg]
        rh, ra = elo[(lg, g["home"])], elo[(lg, g["away"])]
        p_home = 1.0 / (1.0 + 10 ** (-((rh + hfa) - ra) / 400.0))
        home_won = g["hs"] > g["as_"]

        if (EVAL_START <= g["date"] <= EVAL_END and g["id"] in odds
                and cnt[(lg, g["home"])] >= minp and cnt[(lg, g["away"])] >= minp):
            ho, ao = odds[g["id"]]
            rawh, rawa = am_prob(ho), am_prob(ao)
            vig = rawh + rawa
            fair_h = rawh / vig                      # devigged market probability
            # back whichever side our model likes more than the market does
            if (p_home - fair_h) >= ((1 - p_home) - (1 - fair_h)):
                side, ml, mp, won = "home", ho, fair_h, home_won
                edge = p_home - fair_h
            else:
                side, ml, mp, won = "away", ao, 1 - fair_h, not home_won
                edge = (1 - p_home) - (1 - fair_h)
            rows.append(dict(lg=lg, date=g["date"], side=side,
                             model_p=round(p_home if side == "home" else 1 - p_home, 4),
                             fair_p=round(mp, 4), edge=round(edge, 4),
                             ml=ml, vig=round(vig - 1, 4), won=int(won),
                             pick=g["home"] if side == "home" else g["away"],
                             profit=(payout(ml) if won else -100.0)))

        d = K * math.log(abs(g["hs"] - g["as_"]) + 1) * ((1.0 if home_won else 0.0) - p_home)
        elo[(lg, g["home"])] += d; elo[(lg, g["away"])] -= d
        cnt[(lg, g["home"])] += 1; cnt[(lg, g["away"])] += 1
    return rows


def table(rows, label, thresholds=(0.0, 0.02, 0.04, 0.06, 0.08, 0.10)):
    print(f"\n--- {label}  (n={len(rows)}) ---")
    print(f"{'edge >=':<10}{'bets':>7}{'win%':>8}{'ROI':>9}{'95% CI (bootstrap)':>26}")
    for th in thresholds:
        sub = [r for r in rows if r["edge"] >= th]
        if len(sub) < 30:
            continue
        pr = [r["profit"] for r in sub]
        roi = sum(pr) / (100 * len(sub))
        lo, hi = boot_ci(pr)
        flag = "  <-- positive" if lo > 0 else ""
        print(f"{th:<10.0%}{len(sub):>7}{sum(r['won'] for r in sub)/len(sub):>8.1%}"
              f"{roi:>+9.2%}{f'[{lo:+.2%}, {hi:+.2%}]':>26}{flag}")


def main():
    # Prefer the 4-league cache; fall back to the NBA/WNBA cache. Expanding to
    # MLB/NHL needs ~7k summary calls and ESPN throttles to ~0.13 req/s once it
    # has seen heavy traffic, so that pull has to run cold (see README).
    cache = os.path.join(DATA, "edge_games.json")
    alt = os.path.join(DATA, "odds_games.json")
    src = cache if os.path.exists(cache) else (alt if os.path.exists(alt) else None)
    if src:
        games, odds = json.load(open(src))
        odds = {k: tuple(v[:2]) for k, v in odds.items()}
        print(f"cache {os.path.basename(src)}: {len(games)} games, {len(odds)} priced")
    else:
        games = scoreboards()
        print(f"games: {len(games)}")
        odds = fetch_odds(games)
        json.dump([games, {k: list(v) for k, v in odds.items()}], open(cache, "w"))

    rows = build_rows(games, odds)
    print(f"\npriced graded bets: {len(rows)}")
    print(f"average book vig on these games: {sum(r['vig'] for r in rows)/len(rows):.2%}")

    table(rows, "ALL DATA (in-sample -- proves nothing on its own)")

    ins = [r for r in rows if r["date"] < SPLIT_DATE]
    oos = [r for r in rows if r["date"] >= SPLIT_DATE]
    table(ins, f"TIME SPLIT: in-sample (< {SPLIT_DATE})")
    table(oos, f"TIME SPLIT: HOLDOUT (>= {SPLIT_DATE})")

    disc = [r for r in rows if r["lg"] in ("nba", "wnba")]
    indep = [r for r in rows if r["lg"] in ("mlb", "nhl")]
    table(disc, "LEAGUE SPLIT: NBA/WNBA (where the +7.2% was discovered)")
    table(indep, "LEAGUE SPLIT: MLB/NHL (independent test of it)")

    # the original claim, retested on independent leagues
    print("\n--- retesting the original '50-60% confidence' finding ---")
    for lbl, sub in (("NBA/WNBA (discovery)", disc), ("MLB/NHL (independent)", indep)):
        band = [r for r in sub if 0.50 <= r["model_p"] < 0.60]
        if len(band) >= 30:
            pr = [r["profit"] for r in band]
            lo, hi = boot_ci(pr)
            print(f"  {lbl:<24}n={len(band):<6}ROI {sum(pr)/(100*len(band)):+.2%}"
                  f"   95% CI [{lo:+.2%}, {hi:+.2%}]")

    print("\n--- per league, no edge filter ---")
    by = defaultdict(list)
    for r in rows:
        by[r["lg"]].append(r)
    for lg in sorted(by):
        pr = [r["profit"] for r in by[lg]]
        lo, hi = boot_ci(pr)
        print(f"  {lg:<6}n={len(pr):<6}win {sum(r['won'] for r in by[lg])/len(pr):>6.1%}"
              f"  ROI {sum(pr)/(100*len(pr)):>+7.2%}  CI [{lo:+.2%}, {hi:+.2%}]")

    path = os.path.join(OUT, "edge_test.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
