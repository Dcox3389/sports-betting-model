"""
Pull team-sport and soccer results from ESPN's public scoreboard API.

Quirks this handles:
  * team sports report STATUS_FINAL, soccer reports STATUS_FULL_TIME, so we
    test status.type.completed instead of matching on a name
  * chunk size has to differ by sport, and the two constraints pull opposite
    ways: the soccer endpoint returns NOTHING for narrow ranges, while dense
    team schedules silently truncate at limit=1000 if the range is too wide.
    Hence TEAM_SPAN=45 days and SOCCER_SPAN=300 days.
  * ranges spanning ~12 months or more return HTTP 400 either way
"""
import json, os, time, urllib.request, concurrent.futures as cf
from collections import defaultdict
from config import DATA, ESPN_TEAM, ESPN_SOCCER

BASE = "https://site.api.espn.com/apis/site/v2/sports/"


TEAM_SPAN = 45     # dense schedules: keep each chunk under limit=1000 events
SOCCER_SPAN = 300  # soccer endpoint returns nothing for narrow ranges
WORKERS = 4          # ESPN throttles above this and starts refusing everything


def get(url):
    delay = 0.5
    for _ in range(5):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(delay)
            delay *= 2
    return None


def split(a, b, max_days):
    """Break a date range into chunks ESPN will accept."""
    import datetime as dt
    s = dt.datetime.strptime(a, "%Y%m%d").date()
    e = dt.datetime.strptime(b, "%Y%m%d").date()
    out = []
    while s <= e:
        c = min(e, s + dt.timedelta(days=max_days))
        out.append((s.strftime("%Y%m%d"), c.strftime("%Y%m%d")))
        s = c + dt.timedelta(days=1)
    return out


def parse(ev, lg):
    try:
        c = ev["competitions"][0]
        if not c["status"]["type"].get("completed"):
            return None
        cs = c["competitors"]
        if len(cs) != 2:
            return None
        h = next(x for x in cs if x.get("homeAway") == "home")
        a = next(x for x in cs if x.get("homeAway") == "away")
        hs, as_ = int(h["score"]), int(a["score"])
        return dict(lg=lg, date=ev["date"][:10],
                    home=h["team"]["displayName"], away=a["team"]["displayName"],
                    hs=hs, as_=as_, draw=(hs == as_))
    except Exception:
        return None


def pull(spec, label, max_span):
    jobs = [(lg, f"{BASE}{path}/scoreboard?dates={a2}-{b2}&limit=1000")
            for lg, (path, rngs) in spec.items()
            for a, b in rngs
            for a2, b2 in split(a, b, max_span)]
    out, seen = defaultdict(list), set()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for (lg, _), data in zip(jobs, ex.map(get, [u for _, u in jobs])):
            if not data:
                continue
            for ev in data.get("events", []):
                if ev["id"] in seen:
                    continue
                seen.add(ev["id"])
                g = parse(ev, lg)
                if g:
                    out[lg].append(g)
    total = 0
    for lg in spec:
        gs = sorted(out[lg], key=lambda x: x["date"])
        out[lg] = gs
        total += len(gs)
        span = f"({gs[0]['date']}..{gs[-1]['date']})" if gs else "(none)"
        print(f"  {lg:<8}{len(gs):>6}  {span}")
    print(f"{label} total: {total}")
    return dict(out)


def main():
    print("team sports:")
    teams = pull(ESPN_TEAM, "team", TEAM_SPAN)
    with open(os.path.join(DATA, "team_games.json"), "w") as f:
        json.dump(teams, f)

    print("\nsoccer:")
    soccer = pull(ESPN_SOCCER, "soccer", SOCCER_SPAN)
    with open(os.path.join(DATA, "soccer_games.json"), "w") as f:
        json.dump(soccer, f)


if __name__ == "__main__":
    main()
