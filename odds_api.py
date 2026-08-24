"""
Multi-book odds via the-odds-api.com.

ESPN exposes exactly one book (DraftKings), which the red team flagged as a
real limitation (T2). This module reads many, including the two keys that
matter for a Nevada bettor:

    caesars         the operator behind Nevada's former William Hill books
    williamhill_us  the legacy key, carried forward by the API

Quota is charged as [markets] x [regions] per call, and the response headers
report what is left. One call covers a whole league's slate, so a daily run
across four leagues costs 4 of the free monthly allowance.

SETUP -- the key has to come from you; this module will not create an account:

    1. Get a free key at https://the-odds-api.com  (email only)
    2. Save it either way:
         setx ODDS_API_KEY your_key_here          (Windows, new shell after)
       or drop it in a file next to this one named  .odds_api_key
    3. python odds_api.py     to verify and see the quota

The key file is gitignored. Do not paste a key into source.
"""
import json, os, sys, urllib.request, urllib.error
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(HERE, ".odds_api_key")
BASE = "https://api.the-odds-api.com/v4"

# our league code -> the API's sport key
SPORTS = {"mlb": "baseball_mlb", "wnba": "basketball_wnba",
          "nfl": "americanfootball_nfl", "cfb": "americanfootball_ncaaf"}

# Books to read, in the order we prefer them for a Nevada bettor.
PREFERRED = ["caesars", "williamhill_us", "draftkings", "fanduel", "betmgm"]

QUOTA = {}          # populated from response headers on each call


def api_key():
    k = os.environ.get("ODDS_API_KEY", "").strip()
    if k:
        return k
    if os.path.exists(KEY_FILE):
        k = open(KEY_FILE, encoding="utf-8").read().strip()
        if k:
            return k
    return None


def _get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            for h in ("x-requests-remaining", "x-requests-used"):
                if r.headers.get(h):
                    QUOTA[h] = r.headers.get(h)
            return json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read())
            return None, f"HTTP {e.code}: {body.get('message', '')}"
        except Exception:
            return None, f"HTTP {e.code}"
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def fetch(leagues=("mlb", "wnba", "cfb", "nfl"), regions="us"):
    """{(league, date, away, home): {book_key: {team: american_odds}}}

    Returns ({}, reason) when no key is configured, so callers can fall back
    to the single-book ESPN path rather than crash.
    """
    key = api_key()
    if not key:
        return {}, ("no ODDS_API_KEY configured -- see the setup notes in "
                    "odds_api.py; falling back to ESPN/DraftKings")
    out, errors = {}, []
    for lg in leagues:
        sport = SPORTS.get(lg)
        if not sport:
            continue
        url = (f"{BASE}/sports/{sport}/odds/?regions={regions}&markets=h2h"
               f"&oddsFormat=american&dateFormat=iso&apiKey={key}")
        data, err = _get(url)
        if err:
            errors.append(f"{lg}: {err}")
            continue
        for ev in data or []:
            day = (ev.get("commence_time") or "")[:10]
            home, away = ev.get("home_team"), ev.get("away_team")
            if not (day and home and away):
                continue
            books = {}
            for b in ev.get("bookmakers", []):
                for m in b.get("markets", []):
                    if m.get("key") != "h2h":
                        continue
                    prices = {o["name"]: float(o["price"])
                              for o in m.get("outcomes", [])
                              if o.get("name") and o.get("price") is not None}
                    if len(prices) >= 2:
                        books[b["key"]] = prices
            if books:
                out[(lg, day, away, home)] = books
    return out, ("; ".join(errors) if errors else None)


def pick_book(books):
    """(book_key, prices) for the most relevant book we actually got."""
    for k in PREFERRED:
        if k in books:
            return k, books[k]
    if books:
        k = sorted(books)[0]
        return k, books[k]
    return None, None


def best_price(books, team):
    """Best available American price for `team` across all books, and who."""
    best, who = None, None
    for k, prices in books.items():
        p = prices.get(team)
        if p is None:
            continue
        # higher American odds always pays more, whether + or -
        if best is None or p > best:
            best, who = p, k
    return best, who


def main():
    if not api_key():
        print("No API key configured.\n")
        print(__doc__.split("SETUP")[1].strip())
        raise SystemExit(1)
    data, err = fetch()
    if err:
        print("errors:", err)
    print(f"events with odds: {len(data)}")
    seen = defaultdict(int)
    for books in data.values():
        for k in books:
            seen[k] += 1
    print("books returned:", dict(sorted(seen.items(), key=lambda x: -x[1])))
    print("quota:", QUOTA or "(not reported)")
    for (lg, day, away, home), books in list(data.items())[:5]:
        bk, prices = pick_book(books)
        print(f"  {lg} {day}  {away} @ {home}  [{bk}] {prices}")


if __name__ == "__main__":
    main()
