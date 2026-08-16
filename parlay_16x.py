"""
What does a $50 -> $800+ parlay actually require, and what does it return?

$50 paying $800 is a 16x multiplier (+1500 American), which implies a 5.9%
chance of hitting. To profit you must hit MORE than 5.9% of the time.

Key structural fact this measures: our picks win LESS often than their price
implies (80.7% actual vs 85.0% implied at the >=85% filter). Call that ratio
r = 0.949. Every leg added multiplies EV by r, so:

    EV multiplier of an n-leg parlay ~ r^n

which means the bigger the payout you chase, the MORE legs you need, and the
worse the expected return gets. Chasing 16x moves away from profit, not toward
it. This script confirms that against real picks and real prices.
"""
import csv, os, random, math
from collections import defaultdict
from config import OUT

TARGET = 16.0     # $50 -> $800
STAKE = 50.0


def dec(ml):
    return 1 + (100 / -ml if ml < 0 else ml / 100)


def load():
    path = os.path.join(OUT, "odds_backtest.csv")
    return [dict(date=r["date"], conf=float(r["conf"]), ml=float(r["ml"]),
                 won=int(r["won"]), pick=r["pick"], lg=r["lg"],
                 mkt=float(r["mkt"]))
            for r in csv.DictReader(open(path, encoding="utf-8"))]


def boot(vals, n_boot=4000, seed=3):
    if not vals:
        return 0.0, 0.0
    rnd = random.Random(seed); n = len(vals); m = []
    for _ in range(n_boot):
        m.append(sum(vals[rnd.randrange(n)] for _ in range(n)) / n)
    m.sort()
    return m[int(.025 * n_boot)], m[int(.975 * n_boot)]


def main():
    rows = load()
    days = defaultdict(list)
    for r in rows:
        days[r["date"]].append(r)
    for d in days:
        days[d].sort(key=lambda x: -x["conf"])

    # ---- how big a multiplier can one day even produce? ----
    maxmult = []
    for d, ps in days.items():
        m = 1.0
        for p in ps:
            m *= dec(p["ml"])
        maxmult.append((m, len(ps)))
    maxmult.sort(reverse=True)
    reach = sum(1 for m, _ in maxmult if m >= TARGET)
    print(f"days of picks: {len(days)}   avg picks/day: {len(rows)/len(days):.1f}")
    print(f"days where ALL picks combined still reach {TARGET:.0f}x: {reach} "
          f"({reach/len(days):.0%})")
    print(f"median max multiplier available in a day: "
          f"{sorted(m for m, _ in maxmult)[len(maxmult)//2]:.1f}x\n")

    # ---- rolling parlay: accumulate picks until the slip pays >= TARGET ----
    print(f"ROLLING {TARGET:.0f}x PARLAYS (accumulate picks in date order until "
          f"the slip pays {TARGET:.0f}x)")
    seq = sorted(rows, key=lambda r: (r["date"], -r["conf"]))
    slips, cur, mult, legs = [], [], 1.0, 0
    for r in seq:
        cur.append(r); mult *= dec(r["ml"]); legs += 1
        if mult >= TARGET:
            slips.append((mult, legs, all(x["won"] for x in cur),
                          math.prod(x["mkt"] for x in cur)))
            cur, mult, legs = [], 1.0, 0
    hits = sum(1 for _, _, w, _ in slips if w)
    profits = [STAKE * m - STAKE if w else -STAKE for m, _, w, _ in slips]
    lo, hi = boot(profits)
    avg_legs = sum(l for _, l, _, _ in slips) / len(slips)
    breakeven = 1.0 / (sum(m for m, _, _, _ in slips) / len(slips))
    print(f"  slips built              : {len(slips)}")
    print(f"  legs per slip (avg)      : {avg_legs:.1f}")
    print(f"  average payout multiple  : {sum(m for m,_,_,_ in slips)/len(slips):.1f}x")
    print(f"  break-even hit rate needed: {breakeven:.1%}")
    print(f"  ACTUAL hit rate          : {hits/len(slips):.1%}  ({hits}/{len(slips)})")
    print(f"  market's own implied rate : "
          f"{sum(p for _,_,_,p in slips)/len(slips):.1%}")
    print(f"  staked ${STAKE*len(slips):,.0f} -> profit ${sum(profits):+,.0f}"
          f"  ROI {sum(profits)/(STAKE*len(slips)):+.1%}")
    print(f"  95% CI on ROI            : [{lo/STAKE:+.0%}, {hi/STAKE:+.0%}]\n")

    # ---- how EV decays as you add legs to chase a bigger payout ----
    print("EV DECAY: what chasing a bigger payout costs you")
    print(f"{'legs':<6}{'typical payout':>16}{'our hit rate':>15}"
          f"{'break-even':>13}{'EV per $50':>13}")
    hi_conf = [r for r in rows if r["conf"] >= 0.85]
    if hi_conf:
        actual = sum(r["won"] for r in hi_conf) / len(hi_conf)
        implied = sum(r["mkt"] for r in hi_conf) / len(hi_conf)
        avg_dec = sum(dec(r["ml"]) for r in hi_conf) / len(hi_conf)
        for n in (2, 4, 6, 8, 10, 12, 15):
            payout = avg_dec ** n
            p_hit = actual ** n
            be = 1.0 / payout
            ev = STAKE * (p_hit * payout - 1)
            print(f"{n:<6}{payout:>15.1f}x{p_hit:>15.2%}{be:>13.2%}{ev:>+13.2f}")
        print(f"\n  (legs priced at avg {avg_dec:.3f} decimal = {implied:.1%} implied;"
              f" we actually win {actual:.1%})")
        print(f"  every leg multiplies expected value by "
              f"{actual/implied:.3f} -- compounding DOWNWARD")


if __name__ == "__main__":
    main()
