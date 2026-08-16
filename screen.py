"""
Cross-sport selective-prediction screen.

Core finding this implements: you cannot make games more predictable, you can
only choose predictable games. A walk-forward Elo rating is built per league,
then events are graded ONLY above a confidence threshold. Accuracy climbs from
~58% (predict everything) to 85%+ (predict the surest ~4%).

Every rating updates only after an event is scored, so all confidence figures
are genuinely out-of-sample.

Soccer draws are scored as MISSES -- you cannot cash "Team A wins" on a draw.
"""
import json, math, os, csv
from collections import defaultdict
from config import DATA, OUT, EVAL_START, EVAL_END, ELO, THRESHOLDS, SOCCER_KEYS


def wilson(k, n, z=1.96):
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    m = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - m, c + m


def load():
    ev = []
    p = os.path.join(DATA, "mlb_games.json")
    if os.path.exists(p):
        for g in json.load(open(p)):
            ev.append(dict(lg="mlb", date=g["date"], a=g["home"], b=g["away"],
                           margin=abs(g["hs"] - g["as_"]), a_won=g["hs"] > g["as_"],
                           draw=False, home=True))
    for fn in ("team_games.json", "soccer_games.json"):
        p = os.path.join(DATA, fn)
        if not os.path.exists(p):
            continue
        for lg, gs in json.load(open(p)).items():
            if lg not in ELO:
                continue
            for g in gs:
                ev.append(dict(lg=lg, date=g["date"], a=g["home"], b=g["away"],
                               margin=abs(g["hs"] - g["as_"]),
                               a_won=g["hs"] > g["as_"], draw=g["draw"], home=True))
    p = os.path.join(DATA, "tennis_matches.json")
    if os.path.exists(p):
        for m in json.load(open(p)):
            ev.append(dict(lg="tennis_m" if "Men" in m["grouping"] else "tennis_w",
                           date=m["date"], a=m["wid"], b=m["lid"],
                           an=m["wname"], bn=m["lname"], margin=1, a_won=True,
                           draw=False, home=False, tournament=m["tournament"],
                           qual=m["qualifying"]))
    ev.sort(key=lambda x: (x["date"], x["lg"]))
    return ev


def run(events):
    elo, cnt, rows = defaultdict(lambda: 1500.0), defaultdict(int), []
    for e in events:
        lg = e["lg"]
        K, hfa, minp = ELO[lg]
        ra, rb = elo[(lg, e["a"])], elo[(lg, e["b"])]
        adv = hfa if e["home"] else 0.0
        p = 1.0 / (1.0 + 10 ** (-((ra + adv) - rb) / 400.0))

        if (EVAL_START <= e["date"] <= EVAL_END
                and cnt[(lg, e["a"])] >= minp and cnt[(lg, e["b"])] >= minp):
            pick_a = p >= 0.5
            rows.append(dict(
                lg=lg, date=e["date"],
                conf=round(p if pick_a else 1 - p, 4),
                hit=0 if e["draw"] else int(pick_a == e["a_won"]),
                draw=int(e["draw"]),
                pick=(e.get("an", e["a"]) if pick_a else e.get("bn", e["b"])),
                a=e.get("an", e["a"]), b=e.get("bn", e["b"]),
                tournament=e.get("tournament", ""), qual=int(e.get("qual", False))))

        if lg.startswith("tennis"):
            ka = 250 / (cnt[(lg, e["a"])] + 5) ** 0.4
            kb = 250 / (cnt[(lg, e["b"])] + 5) ** 0.4
            elo[(lg, e["a"])] += ka * (1 - p)
            elo[(lg, e["b"])] -= kb * (1 - p)
        else:
            s = 0.5 if e["draw"] else (1.0 if e["a_won"] else 0.0)
            d = K * math.log(e["margin"] + 1) * (s - p)
            elo[(lg, e["a"])] += d
            elo[(lg, e["b"])] -= d
        cnt[(lg, e["a"])] += 1
        cnt[(lg, e["b"])] += 1
    return rows


def acc(rs):
    return sum(r["hit"] for r in rs) / len(rs) if rs else 0.0


def report(rows):
    import datetime as dt
    days = max(1, (dt.date.fromisoformat(EVAL_END) - dt.date.fromisoformat(EVAL_START)).days)
    print(f"\ngraded events {EVAL_START}..{EVAL_END}: {len(rows)}  ({days} days)\n")

    by = defaultdict(list)
    for r in rows:
        by[r["lg"]].append(r)
    print(f"{'league':<10}{'n':>7}{'all':>9}{'n>=85%':>9}{'acc>=85%':>10}")
    for lg in sorted(by, key=lambda l: -len(by[l])):
        rs = by[lg]
        hi = [x for x in rs if x["conf"] >= 0.85]
        s = f"{acc(hi):.1%}" if len(hi) >= 10 else "-"
        print(f"{lg:<10}{len(rs):>7}{acc(rs):>9.1%}{len(hi):>9}{s:>10}")

    print("\n" + "=" * 72)
    print("POOLED SELECTIVE SCREEN")
    print("=" * 72)
    print(f"{'threshold':<12}{'events':>8}{'accuracy':>11}{'95% CI':>20}{'per day':>10}")
    for th in THRESHOLDS:
        sub = [x for x in rows if x["conf"] >= th]
        if len(sub) < 10:
            continue
        k = sum(x["hit"] for x in sub)
        lo, hi = wilson(k, len(sub))
        print(f">= {th:<9.1%}{len(sub):>8}{k/len(sub):>11.1%}"
              f"{f'[{lo:.1%}, {hi:.1%}]':>20}{len(sub)/days:>10.2f}")

    print("\ncalibration (is stated confidence honest?)")
    print(f"{'band':<12}{'n':>7}{'stated':>9}{'actual':>9}")
    for lo_, hi_ in [(.5,.6),(.6,.7),(.7,.8),(.8,.85),(.85,.9),(.9,1.01)]:
        s = [x for x in rows if lo_ <= x["conf"] < hi_]
        if len(s) >= 20:
            print(f"{f'{lo_:.0%}-{hi_:.0%}':<12}{len(s):>7}"
                  f"{sum(x['conf'] for x in s)/len(s):>9.1%}{acc(s):>9.1%}")

    pool = [x for x in rows if x["conf"] >= 0.85]
    if pool:
        comp = defaultdict(list)
        for x in pool:
            comp[x["lg"]].append(x)
        print(f"\ncomposition of the >=85% pool (n={len(pool)}, acc {acc(pool):.1%}):")
        for lg in sorted(comp, key=lambda l: -len(comp[l])):
            rs = comp[lg]
            lo, hi = wilson(sum(x["hit"] for x in rs), len(rs))
            print(f"  {lg:<10}n={len(rs):<5} acc {acc(rs):>6.1%}  CI [{lo:.0%}, {hi:.0%}]")

    path = os.path.join(OUT, "screen_events.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\nwrote {path} ({len(rows)} rows)")


def main():
    events = load()
    print(f"events loaded: {len(events)}")
    rows = run(events)
    if not rows:
        print("no graded events -- check that the fetch scripts ran")
        return
    report(rows)


if __name__ == "__main__":
    main()
