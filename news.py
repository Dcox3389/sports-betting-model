"""
Injury and news feed -- the one input the model has never had.

Every market test in this project ended the same way: the model predicts
winners well but cannot beat closing lines, because the book already knows
what we know. The information it has that we don't is roster news -- who is
out, who just got hurt, who is questionable.

This module closes part of that gap using two zero-key sources:

  * RSS/Atom league feeds  -> breaking headlines
  * Jina Reader (r.jina.ai) -> the full ESPN injury table as markdown

Both approaches are taken from Agent-Reach (MIT, Panniantong/Agent-Reach),
which routes a URL to whichever backend can read it. Jina Reader matters
here for a second reason: it reads ESPN's public pages instead of its API,
so it sidesteps the API throttling that blocked the MLB/NHL edge test.

    python news.py            # today's injury news across active leagues
    python news.py nfl        # one league

Nothing here feeds the ratings yet -- it is reporting only. See the caveat
at the bottom of the module before wiring it into picks.
"""
import re, sys, urllib.request, urllib.parse
from config import OUT

FEEDS = {
    "nfl":  ("https://www.espn.com/espn/rss/nfl/news", "https://www.espn.com/nfl/injuries"),
    "cfb":  ("https://www.espn.com/espn/rss/ncf/news", None),
    "mlb":  ("https://www.espn.com/espn/rss/mlb/news", "https://www.espn.com/mlb/injuries"),
    "wnba": ("https://www.espn.com/espn/rss/wnba/news", None),
}

# words that mark a headline as roster news rather than colour commentary
INJURY = re.compile(
    r"\b(injur\w*|out for|miss(?:es|ing|ed)? (?:time|game|season)|questionable|doubtful|"
    r"placed on IR|torn|sprain\w*|strain\w*|fracture\w*|surgery|concussion|"
    r"day-to-day|activated|return\w*|suspend\w*|ruled out)\b", re.I)

# Statuses meaning the player is unavailable. Leagues word this differently --
# the NFL says "Out" / "Injured Reserve", MLB says "10-Day-IL" / "60-Day-IL".
# Matching only NFL vocabulary silently returned zero MLB absences.
# (Named UNAVAILABLE, not OUT: `OUT` is already the output directory here.)
UNAVAILABLE = re.compile(r"\bout\b|injured reserve|\bIR\b|\bIL\b|doubtful|suspend", re.I)


def read_url(url, timeout=45):
    """Fetch a page as markdown via Jina Reader -- no key, no API quota."""
    req = urllib.request.Request(
        "https://r.jina.ai/" + url,
        headers={"User-Agent": "Mozilla/5.0 (compatible; sports-model/1.0)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", "replace")
    except Exception as e:
        return f"(could not read {url}: {type(e).__name__})"


def headlines(league):
    try:
        import feedparser
    except ImportError:
        return [], "feedparser not installed -- pip install feedparser"
    url = FEEDS[league][0]
    f = feedparser.parse(url)
    out = []
    for e in f.entries:
        title = getattr(e, "title", "")
        out.append(dict(title=title, link=getattr(e, "link", ""),
                        when=getattr(e, "published", "")[:16],
                        roster=bool(INJURY.search(title))))
    return out, None


def injury_table(league):
    """ESPN's injury page, parsed into (team, player, pos, status) rows."""
    url = FEEDS[league][1]
    if not url:
        return []
    md = read_url(url)
    rows, team = [], None
    # ESPN's team header arrives glued to a logo image on one line, e.g.
    #   ![Image 2: ESPN](blob:...)Atlanta Falcons
    # so the name has to be pulled out from after the image markdown.
    team_re = re.compile(r"^(?:!\[[^\]]*\]\([^)]*\))?\s*([A-Z][A-Za-z0-9 .'&-]{2,39})$")
    for line in md.splitlines():
        line = line.strip()
        if not line:
            continue
        if not line.startswith("|"):
            m = team_re.match(line)
            if m:
                team = m.group(1).strip()
            continue
        if line.startswith("|") and team and "---" not in line:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) >= 4 and cells[0].upper() != "NAME":
                name = re.sub(r"\[([^\]]+)\][^)]*\)?", r"\1", cells[0])
                rows.append(dict(team=team, player=name.strip(),
                                 pos=cells[1], status=cells[3] if len(cells) > 3 else "",
                                 note=cells[4] if len(cells) > 4 else ""))
    return rows


_CACHE = {}


def injuries_by_team(league):
    """{team name -> [players currently out]}. Cached per run; one page fetch."""
    if league in _CACHE:
        return _CACHE[league]
    out = {}
    for r in injury_table(league):
        if UNAVAILABLE.search(r["status"]):
            out.setdefault(r["team"], []).append(
                dict(player=r["player"], pos=r["pos"], status=r["status"]))
    _CACHE[league] = out
    return out


def annotate(picks, league_of=lambda p: p["lg"]):
    """Attach injury context to picks. Reporting only -- never touches ratings.

    Adds `out_pick` / `out_opp` counts and `key_out`, so a reader can see when a
    pick is carrying absences. The model's confidence is deliberately unchanged:
    the market prices these reports faster than we can read them, so folding
    them into the rating would add stale information dressed up as signal.
    """
    tables = {}
    for p in picks:
        lg = league_of(p)
        if lg not in FEEDS or not FEEDS[lg][1]:
            continue
        if lg not in tables:
            tables[lg] = injuries_by_team(lg)
        inj = tables[lg]

        def find(team):
            if not team:
                return []
            for k, v in inj.items():
                if k.lower() in team.lower() or team.lower() in k.lower():
                    return v
            # fall back on the last word (nickname), e.g. "Falcons"
            tail = team.split()[-1].lower()
            for k, v in inj.items():
                if k.split()[-1].lower() == tail:
                    return v
            return []

        mine = find(p.get("pick"))
        opp = find(p.get("opponent"))
        p["out_pick"] = len(mine)
        p["out_opp"] = len(opp)
        p["key_out"] = ", ".join(f"{m['player']} ({m['pos']})" for m in mine[:3])
    return picks


def main():
    leagues = [sys.argv[1]] if len(sys.argv) > 1 else ["nfl", "cfb", "mlb", "wnba"]
    for lg in leagues:
        if lg not in FEEDS:
            print(f"unknown league {lg}"); continue
        print("=" * 66)
        print(f"{lg.upper()}")
        print("=" * 66)
        hl, err = headlines(lg)
        if err:
            print(" ", err); continue
        roster = [h for h in hl if h["roster"]]
        print(f"  {len(hl)} headlines, {len(roster)} look like roster news\n")
        for h in roster[:8]:
            print(f"   * {h['title'][:92]}")
        if not roster:
            print("   (nothing roster-related in the current feed)")
        tbl = injury_table(lg)
        if tbl:
            print(f"\n  ESPN injury table: {len(tbl)} listed across "
                  f"{len({r['team'] for r in tbl})} teams")
            gone = [r for r in tbl if UNAVAILABLE.search(r["status"])]
            print(f"  {len(gone)} currently unavailable. First few:")
            for r in gone[:6]:
                print(f"   - {r['team'][:22]:<22} {r['player'][:20]:<20} "
                      f"{r['pos']:<4} {r['status'][:18]}")
        print()

    print("CAVEAT: this is reporting only. Injury news is NOT in the ratings, and")
    print("wiring it in naively would likely make things worse -- the market has")
    print("already priced these reports, usually faster than we can read them.")
    print("The measurable question is whether a pick moves BEFORE the line does;")
    print("that needs line-movement data this project does not yet collect.")


if __name__ == "__main__":
    main()
