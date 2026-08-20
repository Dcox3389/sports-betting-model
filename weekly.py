"""
Weekly report across every active league, with a rigorous parlay section.

The parlay math here does NOT use the model's raw confidence. The model is
overconfident below its top tier -- it says 82% and delivers 74% -- so raw
numbers would inflate every parlay estimate. Legs are priced instead at the
hit rate each tier ACTUALLY delivered across 1,111 graded picks in the
archive, plus the 96.6% college-football headline rate from football.py.

    python weekly.py            # next 7 days
    python weekly.py 14         # next 14 days
"""
import datetime as dt, json, math, sys
from collections import defaultdict
from newsletter import (load_history, build_ratings, slate, rate, TIERS, tier_of)
from config import OUT as OUT_DIR

# Measured hit rates, not model confidence. Sources:
#   archive.py (1,111 graded picks) and football.py (out-of-sample 2025 season)
CALIBRATED = [
    (0.85, 0.846, "Headline"),
    (0.70, 0.737, "Strong"),
    (0.60, 0.613, "Lean"),
    (0.00, 0.551, "Coin-flip"),
]
CFB_HEADLINE = 0.966          # college football, 85%+ tier, 87 picks
VIG = 0.0426                  # average book hold measured in odds_backtest.py


def true_rate(conf, league=None):
    """What a pick at this confidence has historically actually hit."""
    if league == "cfb" and conf >= 0.85:
        return CFB_HEADLINE
    for lo, actual, _ in CALIBRATED:
        if conf >= lo:
            return actual
    return 0.551


def parlay_table(legs_pool):
    """For each leg count, the honest win probability and what it pays."""
    out = []
    for n in range(1, 11):
        if len(legs_pool) < n:
            break
        legs = legs_pool[:n]
        p = 1.0
        fair_dec = 1.0
        for r in legs:
            tp = true_rate(r["conf"], r["lg"])
            p *= tp
            fair_dec *= 1.0 / tp                      # fair price for that leg
        # what a book would actually pay: fair price shaded by the hold, per leg
        book_dec = 1.0
        for r in legs:
            tp = true_rate(r["conf"], r["lg"])
            book_dec *= (1.0 / tp) / (1.0 + VIG)
        out.append(dict(n=n, hit=p, fair=fair_dec, book=book_dec,
                        ev_fair=p * fair_dec - 1, ev_book=p * book_dec - 1))
    return out


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    today = dt.date.today()
    print(f"building weekly report {today} .. {today + dt.timedelta(days-1)}")
    hist = load_history(today.isoformat())
    elo, cnt, form = build_ratings(hist)
    print(f"  ratings from {len(hist)} completed games")

    byday = {}
    allpicks = []
    for d in range(days):
        day = (today + dt.timedelta(d)).isoformat()
        games = slate(day)
        picks = rate(games, elo, cnt, form)
        for p in picks:
            p["date"] = day
        byday[day] = picks
        allpicks.extend(picks)
    print(f"  rated {len(allpicks)} games across {days} days\n")

    print("=" * 74)
    print(f"WEEKLY REPORT  {today.strftime('%b %d')} - "
          f"{(today + dt.timedelta(days-1)).strftime('%b %d, %Y')}")
    print("=" * 74)

    bylg = defaultdict(list)
    for p in allpicks:
        bylg[p["lg"]].append(p)
    print(f"\n{'league':<8}{'games':>7}{'>=85%':>8}{'>=70%':>8}{'>=60%':>8}")
    for lg in sorted(bylg, key=lambda l: -len(bylg[l])):
        s = bylg[lg]
        print(f"{lg:<8}{len(s):>7}{sum(1 for p in s if p['conf']>=.85):>8}"
              f"{sum(1 for p in s if p['conf']>=.70):>8}"
              f"{sum(1 for p in s if p['conf']>=.60):>8}")

    ranked = sorted(allpicks, key=lambda p: -p["conf"])
    print(f"\n--- STRONGEST 12 PICKS OF THE WEEK ---")
    print(f"{'date':<12}{'conf':>6}{'hit rate':>10}  {'pick':<26}{'matchup'}")
    for p in ranked[:12]:
        tr = true_rate(p["conf"], p["lg"])
        print(f"{p['date']:<12}{p['conf']:>6.0%}{tr:>10.1%}  {p['pick'][:25]:<26}{p['matchup'][:40]}")

    print(f"\n--- DAY BY DAY ---")
    for day in sorted(byday):
        ps = byday[day]
        if not ps:
            continue
        best = max(ps, key=lambda x: x["conf"])
        strong = sum(1 for p in ps if p["conf"] >= .70)
        print(f"  {dt.date.fromisoformat(day).strftime('%a %b %d')}  "
              f"{len(ps):>2} games, {strong} at 70%+   best: "
              f"{best['pick'][:24]} ({best['conf']:.0%})")

    # ---------------- the parlay question ----------------
    print("\n" + "=" * 74)
    print("PARLAY ANALYSIS  -- can a parlay sustain an 80%+ win ratio?")
    print("=" * 74)
    print("Legs priced at MEASURED tier hit rates, not model confidence.\n")

    tbl = parlay_table(ranked)
    print(f"{'legs':<6}{'win rate':>10}{'fair pays':>11}{'book pays':>11}"
          f"{'EV (fair)':>11}{'EV (book)':>11}")
    for r in tbl:
        flag = "  <- clears 80%" if r["hit"] >= 0.80 else ""
        print(f"{r['n']:<6}{r['hit']:>10.1%}{r['fair']:>10.2f}x{r['book']:>10.2f}x"
              f"{r['ev_fair']:>+11.1%}{r['ev_book']:>+11.1%}{flag}")

    clears = [r for r in tbl if r["hit"] >= 0.80]
    print(f"\n  This week's board sustains 80%+ up to {len(clears)} leg(s).")

    # what a 96.6% CFB tier would allow, for comparison
    print("\n  For comparison -- college football headline picks (96.6% measured),")
    print("  available from Aug 29:")
    print(f"  {'legs':<6}{'win rate':>10}{'fair pays':>11}{'EV (book)':>11}")
    cfb_rows = []
    for n in range(2, 9):
        p = CFB_HEADLINE ** n
        fair = (1 / CFB_HEADLINE) ** n
        book = ((1 / CFB_HEADLINE) / (1 + VIG)) ** n
        cfb_rows.append((n, p, fair, p * book - 1))
        flag = "  <- clears 80%" if p >= 0.80 else ""
        print(f"  {n:<6}{p:>10.1%}{fair:>10.2f}x{p*book-1:>+11.1%}{flag}")

    import os, weekly_html
    html = weekly_html.render(today, days, bylg, ranked, byday, tbl,
                              cfb_rows, true_rate, len(allpicks))
    path = os.path.join(OUT_DIR, "weekly.html")
    open(path, "w", encoding="utf-8").write(html)
    print(f"\n  wrote {path}")


if __name__ == "__main__":
    main()
