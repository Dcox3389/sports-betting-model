"""
Football stat check: is the Elo engine worth pointing at the 2026 season?

Pulls three seasons of NFL and college football, warms ratings on the older
two, and grades the most recent season out-of-sample -- the same walk-forward
rule the newsletter uses.

Football needs two things the other leagues didn't:
  * season carryover -- 17 NFL games a year is far too few to rebuild a rating
    from 1500 each fall, so ratings persist and regress 1/3 toward the mean
  * neutral-site handling -- bowl games and neutral kickoffs get no home edge

Preseason (season.type 1) is excluded: starters barely play and the results
are close to noise.
"""
import json, math, os, sys
import concurrent.futures as cf
from collections import defaultdict
from config import DATA, OUT
from fetch_espn import get, split, TEAM_SPAN, WORKERS
from divisions import start_rating

BASE = "https://site.api.espn.com/apis/site/v2/sports/"
LEAGUES = {
    # NFL home edge is ~35 Elo, derived from the 55.2% home win rate over the
    # warm-up seasons -- NOT tuned on the held-out season. An earlier 60 was
    # borrowed from basketball and cost ~2 points of accuracy.
    "nfl": ("football/nfl", [("20230901", "20240220"), ("20240901", "20250220"),
                             ("20250901", "20260220")], 20.0, 35.0, 8),
    "cfb": ("football/college-football",
            [("20230820", "20240125"), ("20240820", "20250125"),
             ("20250820", "20260125")], 26.0, 60.0, 8),
}
EVAL_FROM = {"nfl": "2025-09-01", "cfb": "2025-08-20"}
CARRY = 1 / 3.0   # fraction regressed toward 1500 between seasons
TIERS = [("Headline", 0.85), ("Strong", 0.70), ("Lean", 0.60), ("Coin-flip", 0.0)]


def fetch(lg):
    path, rngs, _, _, _ = LEAGUES[lg]
    cache = os.path.join(DATA, f"{lg}_games.json")
    if os.path.exists(cache):
        return json.load(open(cache))
    jobs = [f"{BASE}{path}/scoreboard?dates={a}-{b}&limit=1000"
            for r in rngs for a, b in split(*r, TEAM_SPAN)]
    out, seen = [], set()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for data in ex.map(get, jobs):
            for ev in (data or {}).get("events", []):
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                if (ev.get("season") or {}).get("type") not in (2, 3):
                    continue          # skip preseason
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
                    out.append(dict(date=ev["date"][:10],
                                    season=(ev.get("season") or {}).get("year"),
                                    home=h["team"]["displayName"],
                                    away=a["team"]["displayName"],
                                    hs=hs, as_=as_,
                                    neutral=bool(c.get("neutralSite"))))
                except Exception:
                    continue
    out.sort(key=lambda x: x["date"])
    json.dump(out, open(cache, "w"))
    return out


def run(lg, games):
    _, _, K, HFA, MINP = LEAGUES[lg]
    # FCS teams open ~366 Elo below FBS -- see divisions.py. Without it, Elo
    # never learns the tier gap and FCS teams outrank real FBS powers.
    elo, cnt = {}, defaultdict(int)

    def R(t):
        if t not in elo:
            elo[t] = start_rating(lg, t)
        return elo[t]
    rows, cur_season = [], None

    for g in games:
        if cur_season is not None and g["season"] != cur_season:
            for t in list(elo):                     # new season: regress to own baseline
                base = start_rating(lg, t)
                elo[t] = base + (elo[t] - base) * (1 - CARRY)
        cur_season = g["season"]

        adv = 0.0 if g["neutral"] else HFA
        rh, ra = R(g["home"]), R(g["away"])
        p = 1 / (1 + 10 ** (-((rh + adv) - ra) / 400))
        hw = g["hs"] > g["as_"]

        if g["date"] >= EVAL_FROM[lg] and cnt[g["home"]] >= MINP and cnt[g["away"]] >= MINP:
            pick_home = p >= .5
            rows.append(dict(date=g["date"], conf=p if pick_home else 1 - p,
                             hit=int(pick_home == hw), neutral=int(g["neutral"]),
                             margin=abs(g["hs"] - g["as_"]),
                             pick=g["home"] if pick_home else g["away"],
                             matchup=f"{g['away']} @ {g['home']}"))

        d = K * math.log(abs(g["hs"] - g["as_"]) + 1) * ((1.0 if hw else 0.0) - p)
        elo[g["home"]] += d; elo[g["away"]] -= d
        cnt[g["home"]] += 1; cnt[g["away"]] += 1
    return rows, elo, cnt


def main():
    print(f"{'':<6}{'games':>8}{'home win%':>11}{'avg margin':>12}{'implied HFA':>13}")
    store = {}
    for lg in LEAGUES:
        games = fetch(lg)
        store[lg] = games
        nonneutral = [g for g in games if not g["neutral"]]
        hw = sum(1 for g in nonneutral if g["hs"] > g["as_"]) / len(nonneutral)
        marg = sum(g["hs"] - g["as_"] for g in nonneutral) / len(nonneutral)
        # Elo points that reproduce the observed home win rate
        hfa_elo = -400 * math.log10(1 / hw - 1)
        print(f"{lg:<6}{len(games):>8}{hw:>11.1%}{marg:>+12.2f}{hfa_elo:>13.0f}")

    print("\n--- out-of-sample accuracy (most recent season graded, "
          "prior seasons only warm the ratings) ---")
    print(f"{'':<6}{'graded':>8}{'accuracy':>10}   tiers")
    allrows = {}
    for lg in LEAGUES:
        rows, elo, cnt = run(lg, store[lg])
        allrows[lg] = (rows, elo, cnt)
        acc = sum(r["hit"] for r in rows) / len(rows)
        print(f"{lg:<6}{len(rows):>8}{acc:>10.1%}")
        for name, lo in TIERS:
            hi = {"Headline": 1.01, "Strong": .85, "Lean": .70, "Coin-flip": .60}[name]
            sub = [r for r in rows if lo <= r["conf"] < hi]
            if len(sub) >= 15:
                print(f"        {name:<11}{len(sub):>5} picks"
                      f"{sum(r['hit'] for r in sub)/len(sub):>8.1%}"
                      f"   ({len(sub)/len(rows):.0%} of slate)")

    print("\n--- how much of the slate clears the newsletter's 85% bar? ---")
    for lg in LEAGUES:
        rows = allrows[lg][0]
        for th in (0.70, 0.80, 0.85, 0.90):
            sub = [r for r in rows if r["conf"] >= th]
            if len(sub) >= 10:
                print(f"  {lg} conf>={th:.0%}: {len(sub):>4} picks "
                      f"({len(sub)/len(rows):>4.0%} of slate)  hit {sum(r['hit'] for r in sub)/len(sub):.1%}")
        print()

    for lg in LEAGUES:
        rows, elo, cnt = allrows[lg]
        rated = sorted(((t, r) for t, r in elo.items() if cnt[t] >= 10),
                       key=lambda x: -x[1])
        print(f"top 8 {lg} ratings entering 2026:")
        for t, r in rated[:8]:
            print(f"   {t:<32}{r:7.0f}")
        print()


if __name__ == "__main__":
    main()
