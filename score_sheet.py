"""
Score a filled-in tracking sheet.

Reads the CSV twin written by betsheet.py once the `won` column is filled
(Y/N, y/n, 1/0, true/false), and asks the only question that matters: did each
confidence tier hit at the rate it claimed?

    python score_sheet.py                       # newest sheet in out/
    python score_sheet.py out/betsheet_....csv  # a specific one
    python score_sheet.py out/*.csv             # pool several weeks

Wilson intervals are shown because a single week is far too small to conclude
anything -- a tier can miss its claim by 15 points on 6 rows and mean nothing.
The verdict line tells you whether the sample is even large enough to speak.
"""
import csv, glob, math, os, sys
from collections import defaultdict
from config import OUT

TIERS = [("Headline (85%+)", 0.85, 1.01),
         ("Strong (70-85%)", 0.70, 0.85),
         ("Lean (60-70%)", 0.60, 0.70),
         ("Coin-flip (<60%)", 0.00, 0.60)]
YES = {"y", "yes", "1", "true", "w", "win", "won"}
NO = {"n", "no", "0", "false", "l", "loss", "lost"}


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - m), min(1.0, c + m)


def load(paths):
    rows, blank, bad = [], 0, 0
    for path in paths:
        for r in csv.DictReader(open(path, encoding="utf-8")):
            raw = (r.get("won") or "").strip().lower()
            if not raw:
                blank += 1
                continue
            if raw in YES:
                won = 1
            elif raw in NO:
                won = 0
            else:
                bad += 1
                continue
            try:
                rows.append(dict(conf=float(r["model_conf"]),
                                 chance=float(r["chance"]),
                                 lg=r.get("league", "?"), won=won,
                                 pick=r.get("pick", ""), date=r.get("date", ""),
                                 odds=(r.get("odds") or "").strip()))
            except (ValueError, KeyError):
                bad += 1
    return rows, blank, bad


def main():
    args = [a for a in sys.argv[1:] if a.endswith(".csv")]
    paths = args or sorted(glob.glob(os.path.join(OUT, "betsheet_*.csv")))[-1:]
    if not paths:
        raise SystemExit("No sheet found. Run betsheet.py first.")
    print("scoring:", ", ".join(os.path.basename(p) for p in paths))

    rows, blank, bad = load(paths)
    if not rows:
        raise SystemExit(f"No results filled in yet ({blank} blank rows). "
                         "Put Y or N in the 'won' column first.")
    msg = f"  {len(rows)} graded, {blank} still blank"
    if bad:
        msg += f", {bad} unreadable"
    print(msg)

    n = len(rows)
    hits = sum(r["won"] for r in rows)
    expect = sum(r["chance"] for r in rows)
    print(f"\noverall: {hits}/{n} = {hits/n:.1%}   "
          f"expected {expect/n:.1%}   diff {(hits/n - expect/n)*100:+.1f}pp")

    print(f"\n{'tier':<18}{'n':>5}{'won':>6}{'actual':>9}{'claimed':>9}"
          f"{'95% CI':>18}  verdict")
    for name, lo, hi in TIERS:
        sub = [r for r in rows if lo <= r["conf"] < hi]
        if not sub:
            continue
        k = sum(r["won"] for r in sub)
        claim = sum(r["chance"] for r in sub) / len(sub)
        lo_ci, hi_ci = wilson(k, len(sub))
        if len(sub) < 25:
            v = "too few to judge"
        elif lo_ci <= claim <= hi_ci:
            v = "consistent"
        elif claim < lo_ci:
            v = "BEATING claim"
        else:
            v = "MISSING claim"
        print(f"{name:<18}{len(sub):>5}{k:>6}{k/len(sub):>9.1%}{claim:>9.1%}"
              f"{f'[{lo_ci:.0%}, {hi_ci:.0%}]':>18}  {v}")

    by = defaultdict(list)
    for r in rows:
        by[r["lg"]].append(r)
    if len(by) > 1:
        print(f"\n{'league':<8}{'n':>5}{'won':>6}{'actual':>9}{'claimed':>9}")
        for lg in sorted(by, key=lambda x: -len(by[x])):
            s = by[lg]
            print(f"{lg:<8}{len(s):>5}{sum(r['won'] for r in s):>6}"
                  f"{sum(r['won'] for r in s)/len(s):>9.1%}"
                  f"{sum(r['chance'] for r in s)/len(s):>9.1%}")

    priced = [r for r in rows if r["odds"]]
    print(f"\n{len(priced)} of {n} rows recorded odds.", end=" ")
    if len(priced) < n:
        print("Without odds this measures ACCURACY only, never profit.")
    else:
        print("Odds present -- profitability can be computed.")

    print(f"\nsample size: {n} graded.", end=" ")
    if n < 200:
        print(f"A verdict needs 200+. {200-n} to go; treat everything above as "
              "provisional.")
    else:
        print("Large enough to draw a conclusion from.")


if __name__ == "__main__":
    main()
