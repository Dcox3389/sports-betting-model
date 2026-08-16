"""
$50 -> $5,000 profit in two weeks. What are the actual odds?

Resamples the 168 real 16x-target slips we built from real picks at real
DraftKings prices (6 winners, 162 losers, avg multiplier 21.6x) and runs the
proposed plan 200,000 times.

Also tests the "play with the house's money" idea. There is no such thing in
expected-value terms: once you win it, it is your money, and the next bet has
exactly the same negative edge as the first. The simulation shows what that
means in practice.
"""
import csv, os, random, statistics
from collections import defaultdict
from config import OUT

TARGET_PROFIT = 5000.0
START = 50.0
DAYS = 14
TRIALS = 200_000


def dec(ml):
    return 1 + (100 / -ml if ml < 0 else ml / 100)


def build_slips():
    rows = [dict(date=r["date"], conf=float(r["conf"]), ml=float(r["ml"]),
                 won=int(r["won"]))
            for r in csv.DictReader(
                open(os.path.join(OUT, "odds_backtest.csv"), encoding="utf-8"))]
    rows.sort(key=lambda r: (r["date"], -r["conf"]))
    slips, cur, mult = [], [], 1.0
    for r in rows:
        cur.append(r); mult *= dec(r["ml"])
        if mult >= 16.0:
            slips.append((mult, all(x["won"] for x in cur)))
            cur, mult = [], 1.0
    return slips


def simulate(slips, mode, rnd):
    """Return (final_bankroll, hit_target). Ruin = bankroll below $1."""
    bank = START
    peak_target = START + TARGET_PROFIT
    for _ in range(DAYS):
        if bank < 1.0:
            return 0.0, False
        if bank >= peak_target:
            return bank, True
        if mode == "all_in":
            stake = bank
        elif mode == "half":
            stake = bank / 2
        elif mode == "flat50":
            stake = min(50.0, bank)
        else:  # house_money: risk only profit above the original $50
            stake = bank if bank <= START else bank - START
        mult, won = slips[rnd.randrange(len(slips))]
        bank = bank - stake + (stake * mult if won else 0.0)
    return bank, bank >= peak_target


def main():
    slips = build_slips()
    wins = sum(1 for _, w in slips if w)
    avg = sum(m for m, _ in slips) / len(slips)
    print(f"real slips: {len(slips)}  winners: {wins} ({wins/len(slips):.1%})  "
          f"avg payout {avg:.1f}x\n")

    print(f"GOAL: turn ${START:,.0f} into ${START+TARGET_PROFIT:,.0f} "
          f"(${TARGET_PROFIT:,.0f} profit) in {DAYS} days")
    print(f"{TRIALS:,} simulations per strategy\n")

    print(f"{'strategy':<26}{'hit $5k':>10}{'busted':>10}"
          f"{'median end':>13}{'mean end':>11}")
    for mode, label in (("all_in", "all-in each day"),
                        ("half", "half bankroll each day"),
                        ("house_money", "'play with house money'"),
                        ("flat50", "flat $50/day (no compounding)")):
        rnd = random.Random(20260808)
        hits, bust, ends = 0, 0, []
        for _ in range(TRIALS):
            end, hit = simulate(slips, mode, rnd)
            hits += hit
            bust += (end < 1.0)
            ends.append(end)
        print(f"{label:<26}{hits/TRIALS:>10.3%}{bust/TRIALS:>10.1%}"
              f"{statistics.median(ends):>13,.0f}{sum(ends)/TRIALS:>11,.0f}")

    # what it would actually take
    p = wins / len(slips)
    print(f"\nwhy: one slip hits {p:.1%} of the time.")
    need = 0
    bank = START
    while bank < START + TARGET_PROFIT:
        bank *= avg; need += 1
    print(f"  reaching ${START+TARGET_PROFIT:,.0f} needs {need} winning slips "
          f"(at {avg:.1f}x each)")
    print(f"  probability of {need} hits before any loss wipes the bankroll: "
          f"~{p**need:.4%}")
    print(f"  expected value of every slip: "
          f"{(p*avg-1):+.1%} of whatever you stake")


if __name__ == "__main__":
    main()
