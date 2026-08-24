"""
Attach live market prices to a tracking sheet.

Fills the `odds` column of a betsheet CSV with DraftKings moneylines for the
side we picked, then compares our calibrated chance against the market's
de-vigged probability. That difference is the only number that has ever
mattered in this project: being right is not the same as being priced wrong.

    python price_sheet.py                    # newest sheet in out/
    python price_sheet.py out/betsheet_....csv

Source limitation, stated plainly: ESPN exposes exactly ONE book
(DraftKings) and gives no timestamp on the quote. There is no line shopping
here and no way to know how far the price will move before kickoff. The red
team flagged both (T1, T2); the same caveats apply to everything below.
"""
import csv, glob, json, os, re, sys, urllib.request
import concurrent.futures as cf
from collections import defaultdict
from config import OUT

BASE = "https://site.api.espn.com/apis/site/v2/sports/"
PATHS = {"mlb": "baseball/mlb", "wnba": "basketball/wnba",
         "nfl": "football/nfl", "cfb": "football/college-football"}
WORKERS = 2      # ESPN refuses everything above ~4; be gentle on 175 calls


# Failures must never look like "no odds posted" -- that mistake has now
# appeared three times in this project. Count them and report separately.
FAILS = []


def get(url, timeout=40):
    import time
    delay = 0.6
    last = None
    for _ in range(4):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception as e:
            last = e
            time.sleep(delay)
            delay *= 2
    FAILS.append(type(last).__name__ if last else "?")
    return None


def norm(s):
    return re.sub(r"[^a-z]", "", (s or "").lower())


def am_prob(ml):
    return (-ml) / (-ml + 100) if ml < 0 else 100 / (ml + 100)


def collect_odds(rows):
    """{(league, normalised away, normalised home): {team -> moneyline}}"""
    want = defaultdict(set)
    for r in rows:
        want[r["league"]].add(r["date"])

    events = []
    for lg, dates in want.items():
        if lg not in PATHS:
            continue
        for d in sorted(dates):
            sb = get(f"{BASE}{PATHS[lg]}/scoreboard?dates={d.replace('-','')}&limit=80")
            for e in (sb or {}).get("events", []):
                try:
                    c = e["competitions"][0]
                    if c["status"]["type"].get("completed"):
                        continue
                    cs = c["competitors"]
                    h = next(x for x in cs if x["homeAway"] == "home")
                    a = next(x for x in cs if x["homeAway"] == "away")
                    events.append((lg, e["id"], e["date"][:10],
                                   a["team"]["displayName"], h["team"]["displayName"]))
                except Exception:
                    continue
    print(f"  {len(events)} scheduled events found")

    urls = [f"{BASE}{PATHS[lg]}/summary?event={eid}" for lg, eid, _, _, _ in events]
    out = {}
    done = 0
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for (lg, eid, day, away, home), s in zip(events, ex.map(get, urls)):
            done += 1
            if done % 50 == 0:
                print(f"    priced {done}/{len(events)}")
            for pc in (s or {}).get("pickcenter", []):
                ho = (pc.get("homeTeamOdds") or {}).get("moneyLine")
                ao = (pc.get("awayTeamOdds") or {}).get("moneyLine")
                if ho and ao:
                    out[(lg, day, norm(away), norm(home))] = {
                        norm(home): float(ho), norm(away): float(ao),
                        "_book": pc.get("provider", {}).get("name", "?")}
                    break
    bydate = defaultdict(lambda: [0, 0])
    for (lg, eid, day, away, home) in events:
        bydate[day][0] += 1
    for (lg, day, a, h) in out:
        bydate[day][1] += 1
    print("  coverage by date (books post close to game time):")
    for day in sorted(bydate):
        tot, got = bydate[day]
        print(f"    {day}  {got:>3}/{tot:<3} {got/tot:>4.0%}")
    reached = len(events) - len(FAILS)
    print(f"  requests failed: {len(FAILS)} of {len(events)}")
    print(f"  {len(out)} events carry a moneyline "
          f"({len(out)/max(1,reached):.0%} of the {reached} actually reached)")
    if len(FAILS) > len(events) * 0.2:
        print("  !! heavy request failure -- coverage below is a throttling")
        print("     artifact, not a statement about what the book posts")
    return out


def main():
    args = [a for a in sys.argv[1:] if a.endswith(".csv")]
    path = (args or sorted(glob.glob(os.path.join(OUT, "betsheet_*.csv")))[-1:])[0]
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    print(f"sheet: {os.path.basename(path)}  ({len(rows)} picks)")
    # Wipe any prior pricing first. Only matched rows get rewritten, so
    # values from an earlier (possibly buggy) run would otherwise survive and
    # silently poison the sheet.
    stale = sum(1 for r in rows if r.get("odds"))
    if stale:
        print(f"  clearing {stale} previously-priced rows before repricing")
    for r in rows:
        r["odds"] = ""
        r["notes"] = ""

    # Prefer the multi-book feed (gives Caesars, the Nevada operator). Fall
    # back to ESPN's single DraftKings quote when no API key is configured.
    import odds_api
    multi, why = odds_api.fetch(sorted({r["league"] for r in rows}))
    if multi:
        print(f"  multi-book feed: {len(multi)} events"
              f"   quota {odds_api.QUOTA.get('x-requests-remaining','?')} left")
        odds = {}
        for (lg, day, away, home), books in multi.items():
            bk, prices = odds_api.pick_book(books)
            if not prices:
                continue
            conv = {norm(t): v for t, v in prices.items()}
            conv["_book"] = bk
            conv["_all"] = books
            odds[(lg, day, norm(away), norm(home))] = conv
    else:
        print(f"  {why}")
        odds = collect_odds(rows)

    matched, edges = 0, []
    for r in rows:
        m = re.match(r"(.+?)\s+@\s+(.+)$", r["matchup"])
        if not m:
            continue
        key = (r["league"], r["date"], norm(m.group(1)), norm(m.group(2)))
        book = odds.get(key)
        if not book:
            continue
        ml = book.get(norm(r["pick"]))
        if ml is None:
            continue
        matched += 1
        r["odds"] = f"{int(ml):+d}"
        raw_pick = am_prob(ml)
        other = [v for k, v in book.items()
                 if k not in ("_book", "_all") and k != norm(r["pick"])]
        vig = raw_pick + am_prob(other[0]) if other else 1.0
        fair = raw_pick / vig if vig else raw_pick
        ours = float(r["chance"])
        note = f"{book.get('_book','?')} mkt {fair:.0%} vig {vig-1:.1%}"
        allb = book.get("_all")
        if allb:
            import odds_api as _oa
            # find the pick's display name as the feed spells it
            disp = next((t for t in next(iter(allb.values())) if norm(t) == norm(r["pick"])), None)
            if disp:
                bp, who = _oa.best_price(allb, disp)
                if bp is not None and who and who != book.get("_book"):
                    note += f" | best {int(bp):+d} @ {who}"
        r["notes"] = note
        edges.append((ours - fair, ours, fair, ml, r))

    print(f"\nmatched prices to {matched} of {len(rows)} picks")
    if not edges:
        raise SystemExit("No prices matched -- nothing to compare.")

    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)
    print(f"wrote odds back into {os.path.basename(path)}")

    avg_vig = sum(1 for _ in edges)
    pos = [e for e in edges if e[0] > 0]
    print(f"\nour chance vs the market's de-vigged number:")
    print(f"  picks priced          {len(edges)}")
    print(f"  we are HIGHER on      {len(pos)} ({len(pos)/len(edges):.0%})")
    print(f"  mean edge             {sum(e[0] for e in edges)/len(edges):+.2%}")
    print(f"  median edge           "
          f"{sorted(e[0] for e in edges)[len(edges)//2]:+.2%}")

    print(f"\n{'edge':>7}{'ours':>7}{'mkt':>7}{'price':>8}  pick / matchup")
    for d, ours, fair, ml, r in sorted(edges, key=lambda e: -e[0])[:10]:
        print(f"{d:>+7.1%}{ours:>7.0%}{fair:>7.0%}{int(ml):>+8}  "
              f"{r['pick'][:22]:<23}{r['matchup'][:34]}")

    print("\nCAVEATS")
    print("  One book (DraftKings), one untimed quote, no line shopping.")
    print("  A positive number here is NOT a proven edge -- every retrospective")
    print("  test in this project produced apparent edges that vanished or")
    print("  inverted out of sample. Treat this as a column to record, then")
    print("  grade later with score_sheet.py.")


if __name__ == "__main__":
    main()
