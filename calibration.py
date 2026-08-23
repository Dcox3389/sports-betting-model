"""
What a pick at a given confidence has ACTUALLY hit, in the situation it is
being made in.

The sheet used to quote one hit rate per tier, measured across whole seasons.
That silently overstated season openers: college football's Headline tier hit
95.9% from week 4 onward but the model produced only TWO such picks in weeks
0-1, so quoting 96.6% on an August opener was borrowing a number from
November, when the ratings actually knew something.

Everything here is derived from the graded record, never hand-set:

  * archive_picks.csv supplies MLB and WNBA
  * football.py's cached seasons supply NFL and college football
  * football picks are split into EARLY (first two weeks of a season, when
    ratings are last year's roster regressed toward baseline) and MAIN

A cell with fewer than MIN_N graded picks is not trusted. It falls back to the
next-broadest bucket and is flagged `thin`, so the sheet can show that the
number is inherited rather than measured here.

    python calibration.py        # print the table
"""
import csv, datetime as dt, json, os
from collections import defaultdict
from config import DATA, OUT

MIN_N = 30            # below this a cell is inherited, not measured
EARLY_WEEKS = 2       # a football season's first two weeks

# First regular-season game of the current season. Update each year; football
# is the only sport where "early" means anything, because a 17- or 13-game
# season never gets long enough for ratings to forget the previous roster.
SEASON_START = {"nfl": "2026-09-10", "cfb": "2026-08-29"}

TIERS = [("headline", 0.85, 1.01), ("strong", 0.70, 0.85),
         ("lean", 0.60, 0.70), ("coin", 0.00, 0.60)]


def tier_of(conf):
    for name, lo, hi in TIERS:
        if lo <= conf < hi:
            return name
    return "coin"


def phase_of(league, date):
    """'early' only for football inside the opening fortnight."""
    if league not in SEASON_START:
        return "main"
    try:
        start = dt.date.fromisoformat(SEASON_START[league])
        d = dt.date.fromisoformat(date)
    except Exception:
        return "main"
    if d < start:
        return "early"                      # before kickoff = opening week
    return "early" if (d - start).days < EARLY_WEEKS * 7 else "main"


def _football_records():
    """Graded football picks, tagged by how deep into their own season they fell."""
    import football as F
    out = []
    for lg in ("nfl", "cfb"):
        p = os.path.join(DATA, f"{lg}_games.json")
        if not os.path.exists(p):
            continue
        rows, _, _ = F.run(lg, json.load(open(p)))
        starts = {}
        for r in rows:
            y = int(r["date"][:4])
            starts[y] = min(starts.get(y, r["date"]), r["date"])
        for r in rows:
            y = int(r["date"][:4])
            wk = (dt.date.fromisoformat(r["date"])
                  - dt.date.fromisoformat(starts[y])).days // 7
            out.append((lg, "early" if wk < EARLY_WEEKS else "main",
                        r["conf"], r["hit"]))
    return out


def _archive_records():
    p = os.path.join(OUT, "archive_picks.csv")
    if not os.path.exists(p):
        return []
    return [(r["lg"], "main", float(r["conf"]), int(r["hit"]))
            for r in csv.DictReader(open(p, encoding="utf-8"))]


def build():
    """{(league, phase, tier): (rate, n, source)}.

    Thin cells are NOT filled from the all-season bucket -- that bucket is
    dominated by mid-season games and re-imports the very optimism this module
    exists to remove (cfb/early/headline has n=2 and would inherit 96.5%).

    Instead a thin early-season cell is shrunk toward a prior built from the
    league's own MAIN-phase rate for that tier, scaled by how much of its skill
    actually survives into the opening fortnight. That factor is measured:

        factor = (early_overall - 0.5) / (main_overall - 0.5)

    i.e. what share of the model's edge over a coin flip is present in week 0.
    Then observed and prior are blended by sample size, so two observations
    move the number barely at all and thirty move it halfway.
    """
    recs = _archive_records() + _football_records()
    cells = defaultdict(lambda: [0, 0])          # hits, n
    overall = defaultdict(lambda: [0, 0])        # (lg, phase) -> hits, n
    for lg, phase, conf, hit in recs:
        cells[(lg, phase, tier_of(conf))][0] += hit
        cells[(lg, phase, tier_of(conf))][1] += 1
        cells[(lg, "any", tier_of(conf))][0] += hit
        cells[(lg, "any", tier_of(conf))][1] += 1
        cells[("any", "any", tier_of(conf))][0] += hit
        cells[("any", "any", tier_of(conf))][1] += 1
        overall[(lg, phase)][0] += hit
        overall[(lg, phase)][1] += 1

    def rate(key):
        h, n = cells.get(key, [0, 0])
        return (h / n, n) if n else (None, 0)

    # how much of each league's edge survives into the opening two weeks
    factor = {}
    for lg in {k[0] for k in overall}:
        eh, en = overall.get((lg, "early"), [0, 0])
        mh, mn = overall.get((lg, "main"), [0, 0])
        if en >= MIN_N and mn >= MIN_N and (mh / mn) > 0.5:
            factor[lg] = max(0.0, min(1.0, ((eh / en) - 0.5) / ((mh / mn) - 0.5)))

    table = {}
    for (lg, phase, tier), (hits, n) in cells.items():
        if lg == "any" or phase == "any":
            continue
        if n >= MIN_N:
            table[(lg, phase, tier)] = (hits / n, n, "measured")
            continue
        # --- thin: build a prior, then shrink the observation toward it ---
        main_rate, main_n = rate((lg, "main", tier))
        if phase == "early" and main_rate is not None and main_n >= MIN_N:
            f = factor.get(lg, 0.6)
            prior = 0.5 + (main_rate - 0.5) * f
            src = f"thin -> {lg} main x{f:.2f} early-factor"
        else:
            prior, pn = rate((lg, "any", tier))
            src = f"thin -> {lg} all-season"
            if prior is None or pn < MIN_N:
                prior, pn = rate(("any", "any", tier))
                src = "thin -> all leagues"
            if prior is None:
                prior, src = 0.55, "thin -> default"
        blended = (hits + MIN_N * prior) / (n + MIN_N)
        table[(lg, phase, tier)] = (blended, n, src)

    for tier in {k[2] for k in cells}:
        r, n = rate(("any", "any", tier))
        if r is not None and n >= MIN_N:
            table[("any", "any", tier)] = (r, n, "measured")
    return table


_TABLE = None


def chance(league, date, conf):
    """(rate, n, source) for a pick. Never invents precision it does not have."""
    global _TABLE
    if _TABLE is None:
        _TABLE = build()
    tier = tier_of(conf)
    key = (league, phase_of(league, date), tier)
    if key in _TABLE:
        return _TABLE[key]
    return _TABLE.get(("any", "any", tier), (0.55, 0, "thin -> default"))


def main():
    t = build()
    print(f"minimum sample for a measured cell: {MIN_N}\n")
    print(f"{'league':<8}{'phase':<8}{'tier':<10}{'rate':>7}{'n':>7}  source")
    for key in sorted(t, key=lambda k: (k[0], k[1], k[2])):
        rate, n, src = t[key]
        lg, phase, tier = key
        print(f"{lg:<8}{phase:<8}{tier:<10}{rate:>7.1%}{n:>7}  {src}")


if __name__ == "__main__":
    main()
