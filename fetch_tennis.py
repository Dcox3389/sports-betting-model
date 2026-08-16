"""
Pull ATP/WTA singles results from ESPN.

A scoreboard query on any date inside a tournament returns that whole
tournament, so rather than scraping every day we step adaptively: query a
date, then jump past the end of whatever tournaments came back. That covers
the full calendar in roughly 60 requests per tour per 18 months.

Note: ESPN tennis athletes carry `guid`, NOT `id`. Keying on `id` silently
drops every match.
"""
import json, os, datetime as dt, urllib.request
from collections import Counter
from config import DATA, HISTORY_START, EVAL_START, EVAL_END

URL = "https://site.api.espn.com/apis/site/v2/sports/tennis/{}/scoreboard?dates={}"


def get(tour, d):
    for _ in range(3):
        try:
            with urllib.request.urlopen(URL.format(tour, d.strftime("%Y%m%d")),
                                        timeout=90) as r:
                return json.loads(r.read())
        except Exception:
            pass
    return None


def main():
    start = dt.date.fromisoformat(HISTORY_START)
    end = dt.date.fromisoformat(EVAL_END)
    matches = {}

    for tour in ("atp", "wta"):
        d, nq = start, 0
        while d <= end:
            data = get(tour, d)
            nq += 1
            jump = None
            for ev in (data or {}).get("events", []):
                ed = ev.get("endDate")
                if ed:
                    try:
                        e = dt.date.fromisoformat(ed[:10])
                        jump = max(jump, e) if jump else e
                    except Exception:
                        pass
                for grp in ev.get("groupings", []):
                    gname = grp.get("grouping", {}).get("displayName", "")
                    if "Singles" not in gname:
                        continue
                    for c in grp.get("competitions", []):
                        if c.get("status", {}).get("type", {}).get("name") != "STATUS_FINAL":
                            continue
                        cs = c.get("competitors", [])
                        if len(cs) != 2:
                            continue
                        try:
                            w = next(x for x in cs if x.get("winner"))
                            l = next(x for x in cs if not x.get("winner"))
                        except StopIteration:
                            continue
                        wa, la = w.get("athlete") or {}, l.get("athlete") or {}
                        wid = wa.get("guid") or wa.get("fullName")
                        lid = la.get("guid") or la.get("fullName")
                        if not wid or not lid:
                            continue
                        rnd = (c.get("round") or {}).get("displayName", "")
                        matches[c["id"]] = dict(
                            date=(c.get("date") or ev.get("date") or "")[:10],
                            tour=tour, tournament=ev.get("name", "?"),
                            slam=bool(ev.get("major")), grouping=gname, round=rnd,
                            qualifying=("Qualif" in rnd),
                            wid=wid, wname=wa.get("displayName", "?"),
                            lid=lid, lname=la.get("displayName", "?"))
            nxt = (jump + dt.timedelta(days=1)) if jump else None
            d = nxt if (nxt and nxt > d) else d + dt.timedelta(days=3)
        print(f"  {tour}: {nq} queries")

    rows = sorted([m for m in matches.values() if m["date"]], key=lambda x: x["date"])
    with open(os.path.join(DATA, "tennis_matches.json"), "w") as f:
        json.dump(rows, f)

    ev = [m for m in rows if EVAL_START <= m["date"] <= EVAL_END]
    print(f"tennis total: {len(rows)} singles matches "
          f"({rows[0]['date']}..{rows[-1]['date']})" if rows else "tennis: none")
    print(f"  in eval window: {len(ev)}")
    print(f"  men/women: {Counter('M' if 'Men' in m['grouping'] else 'W' for m in ev)}")
    return rows


if __name__ == "__main__":
    main()
