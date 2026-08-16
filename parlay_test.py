"""
What do parlays do to this strategy?

Parlays are sold as "low entry, high return." The math is that they multiply
the legs together -- which multiplies the EDGE together too. When each leg is
already negative, stacking them compounds the loss instead of the profit.

This builds real parlays out of our real graded picks at real DraftKings
prices, so the answer is measured rather than argued.

For each day we take the N highest-confidence picks, combine them, stake $10,
and grade. Straight-bet the same legs for comparison.
"""
import csv, os, random
from collections import defaultdict
from config import OUT

STAKE = 10.0


def dec(ml):
    """American -> decimal odds (includes stake)."""
    return 1 + (100 / -ml if ml < 0 else ml / 100)


def load():
    path = os.path.join(OUT, "odds_backtest.csv")
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        rows.append(dict(date=r["date"], conf=float(r["conf"]), ml=float(r["ml"]),
                         won=int(r["won"]), pick=r["pick"], lg=r["lg"]))
    return rows


def boot(vals, n_boot=4000, seed=11):
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
    print(f"graded picks: {len(rows)} across {len(days)} days\n")

    print(f"{'legs':<6}{'parlays':>9}{'hit%':>8}{'staked':>10}{'returned':>11}"
          f"{'profit':>11}{'ROI':>9}{'95% CI':>22}")

    results = {}
    for n in range(1, 7):
        profits, hits = [], 0
        for d, picks in days.items():
            if len(picks) < n:
                continue
            legs = picks[:n]
            odds = 1.0
            for L in legs:
                odds *= dec(L["ml"])
            won = all(L["won"] for L in legs)
            hits += won
            profits.append(STAKE * odds - STAKE if won else -STAKE)
        if len(profits) < 20:
            continue
        staked = STAKE * len(profits)
        prof = sum(profits)
        lo, hi = boot(profits)
        results[n] = profits
        print(f"{n:<6}{len(profits):>9}{hits/len(profits):>8.1%}{staked:>10,.0f}"
              f"{staked+prof:>11,.0f}{prof:>+11,.0f}{prof/staked:>+9.1%}"
              f"{f'[{lo/STAKE:+.0%}, {hi/STAKE:+.0%}]':>22}")

    # --- same legs, bet straight instead of parlayed ---
    print("\nsame picks, bet STRAIGHT instead of parlayed:")
    print(f"{'legs used':<12}{'bets':>8}{'staked':>10}{'profit':>11}{'ROI':>9}")
    for n in (2, 4, 6):
        prof, cnt = 0.0, 0
        for d, picks in days.items():
            if len(picks) < n:
                continue
            for L in picks[:n]:
                cnt += 1
                prof += (STAKE * (dec(L["ml"]) - 1)) if L["won"] else -STAKE
        if cnt:
            print(f"top {n:<8}{cnt:>8}{STAKE*cnt:>10,.0f}{prof:>+11,.0f}"
                  f"{prof/(STAKE*cnt):>+9.1%}")

    # --- what actually happens to a bankroll ---
    print("\n$10/day for the full period -- where do you end up?")
    print(f"{'legs':<6}{'end bankroll':>15}{'worst drawdown':>17}{'days profitable':>18}")
    for n, profits in results.items():
        bank, peak, dd, up = 0.0, 0.0, 0.0, 0
        for p in profits:
            bank += p
            peak = max(peak, bank)
            dd = min(dd, bank - peak)
            up += (bank > 0)
        print(f"{n:<6}{bank:>+15,.0f}{dd:>+17,.0f}{up/len(profits):>18.0%}")

    # --- probability of ending ahead, resampling the real results ---
    print("\nchance of finishing ahead (4,000 reshuffles of the real outcomes):")
    rnd = random.Random(5)
    for n, profits in results.items():
        wins = 0
        for _ in range(4000):
            tot = sum(profits[rnd.randrange(len(profits))] for _ in range(len(profits)))
            wins += (tot > 0)
        print(f"  {n}-leg: {wins/4000:>6.1%}")

    # --- the lottery framing, made concrete ---
    print("\n'low entry, high return' on a $10 stake:")
    for n, profits in results.items():
        if n == 1:
            continue
        best = max(profits)
        hitrate = sum(1 for p in profits if p > 0) / len(profits)
        print(f"  {n}-leg: biggest single win ${best:,.0f}, "
              f"hits {hitrate:.1%} of the time, "
              f"expected value {sum(profits)/len(profits):+.2f} per $10")


if __name__ == "__main__":
    main()
