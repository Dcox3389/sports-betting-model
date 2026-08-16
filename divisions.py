"""
College football division awareness.

Elo assumes one connected pool of teams. College football isn't: FBS and FCS
are separate tiers that meet in only ~14% of games, so ratings never calibrate
the gap between them. Left alone, an FCS team that dominates FCS opponents
climbs above real FBS powers -- North Dakota State was rating 8th nationally,
ahead of Georgia.

The gap is measured, not assumed. Across 404 cross-division games in the
cached seasons, FBS beat FCS 372 times (92.1%) by an average of 28.8 points.
A 92.1% win rate implies ~426 Elo of separation; net of the ~60-point home
edge FBS teams enjoy (they almost always host these games) the true tier gap
is ~366 Elo.

So FCS teams start there instead of at 1500. Elo then adjusts each team
normally from a starting point that reflects the tier it plays in.

Rebuild the division map with:  python divisions.py
"""
import json, os, re, urllib.request
from config import DATA

MAP = os.path.join(DATA, "cfb_divisions.json")
FCS_START = 1500 - 366          # measured; see module docstring
SEASON = 2025

CORE = ("https://sports.core.api.espn.com/v2/sports/football/leagues/"
        "college-football/seasons/{}/types/2/groups/{}/teams?limit=400")
SITE = ("https://site.api.espn.com/apis/site/v2/sports/football/"
        "college-football/teams?limit=900")


def _get(url):
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.loads(r.read())


def build():
    """Fetch the FBS/FCS rosters. ESPN only exposes real division membership
    on the core API -- the `groups` query param is silently ignored on the
    site API's teams and scoreboard endpoints, which return every division."""
    ids = {}
    for grp, label in ((80, "FBS"), (81, "FCS")):
        d = _get(CORE.format(SEASON, grp))
        ids[label] = {re.search(r"/teams/(\d+)", i["$ref"]).group(1) for i in d["items"]}
    names = {x["team"]["id"]: x["team"]["displayName"]
             for x in _get(SITE)["sports"][0]["leagues"][0]["teams"]}
    out = {lab: sorted(names[i] for i in s if i in names) for lab, s in ids.items()}
    json.dump(out, open(MAP, "w"))
    return out


_LOADED = None


def _load():
    global _LOADED
    if _LOADED is None:
        _LOADED = json.load(open(MAP)) if os.path.exists(MAP) else build()
    return _LOADED


def _key(name):
    """Normalise for matching: ESPN is not perfectly consistent between the
    scoreboard's displayName and the teams endpoint's."""
    return re.sub(r"[^a-z ]", "", name.lower()).strip()


def division(team):
    """'FBS' | 'FCS' | None. Unknown teams are treated as FBS by the caller --
    misfiling a small school as FBS costs a few points that Elo corrects,
    while misfiling a real FBS team as FCS would hand it a wrong 366-point
    penalty it may never shed."""
    d = _load()
    if not hasattr(division, "_idx"):
        idx = {}
        for lab in ("FBS", "FCS"):
            for t in d[lab]:
                idx[_key(t)] = lab
                idx[_key(t).split()[-1]] = idx.get(_key(t).split()[-1], lab)
        division._idx = idx
    k = _key(team)
    if k in division._idx:
        return division._idx[k]
    tail = k.split()[-1] if k.split() else ""
    return division._idx.get(tail)


def start_rating(league, team):
    """Opening Elo for a team. Only college football differs from 1500."""
    if league != "cfb":
        return 1500.0
    return FCS_START if division(team) == "FCS" else 1500.0


if __name__ == "__main__":
    out = build()
    print(f"FBS: {len(out['FBS'])}   FCS: {len(out['FCS'])}")
    for t in ("Ohio State Buckeyes", "North Dakota State Bison",
              "Appalachian State Mountaineers", "Georgia Bulldogs"):
        print(f"  {t:<34}{division(t) or 'unknown -> treated as FBS'}"
              f"   start {start_rating('cfb', t):.0f}")
