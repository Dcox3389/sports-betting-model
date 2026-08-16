"""
Daily picks newsletter generator.

Refreshes ratings to the last completed game, rates tomorrow's slate, and
writes a newsletter as Markdown + HTML.

    python newsletter.py            # tomorrow
    python newsletter.py 2026-08-09 # a specific date

Confidence tiers come from what the backtest actually measured, not from
vibes -- see TIERS below. The 84% figure applies ONLY to the >=85% tier.
"""
import json, math, os, sys, datetime as dt, urllib.request
from collections import defaultdict
from config import DATA, OUT, ELO

MLB_API = ("https://statsapi.mlb.com/api/v1/schedule?sportId=1"
           "&startDate={}&endDate={}&gameType=R&hydrate=probablePitcher,team")
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/wnba/scoreboard?dates={}-{}&limit=300"

# tier -> (min confidence, measured hit rate from the 18,606-event backtest)
TIERS = [("Headline", 0.85, "84%"), ("Strong", 0.70, "71%"),
         ("Lean", 0.60, "64%"), ("Coin-flip", 0.00, "57%")]


def get(url, timeout=60):
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return json.loads(r.read())
        except Exception:
            pass
    return None


def load_history(today):
    """All completed games this season, for ratings. MLB via statsapi, WNBA via ESPN."""
    games = []
    d = get(MLB_API.format("2026-03-01", today))
    for blk in (d or {}).get("dates", []):
        for g in blk["games"]:
            if g["status"]["abstractGameState"] != "Final":
                continue
            h, a = g["teams"]["home"], g["teams"]["away"]
            if "score" not in h or "score" not in a or h["score"] == a["score"]:
                continue
            games.append(dict(lg="mlb", date=g["officialDate"],
                              home=h["team"]["name"], away=a["team"]["name"],
                              hs=h["score"], as_=a["score"]))
    w = get(ESPN.format("20260501", today.replace("-", "")))
    for ev in (w or {}).get("events", []):
        try:
            c = ev["competitions"][0]
            if not c["status"]["type"].get("completed"):
                continue
            cs = c["competitors"]
            h = next(x for x in cs if x["homeAway"] == "home")
            a = next(x for x in cs if x["homeAway"] == "away")
            if int(h["score"]) == int(a["score"]):
                continue
            games.append(dict(lg="wnba", date=ev["date"][:10],
                              home=h["team"]["displayName"],
                              away=a["team"]["displayName"],
                              hs=int(h["score"]), as_=int(a["score"])))
        except Exception:
            continue
    games.extend(football_history(today))
    games.sort(key=lambda x: x["date"])
    return games


FOOTBALL = ("nfl", "cfb")
FB_PATH = {"nfl": "football/nfl", "cfb": "football/college-football"}
CARRY = 1 / 3.0     # football ratings regress this far to the mean each new season


def football_history(today):
    """Prior seasons from football.py's cache, plus anything already played
    this season. Football needs the carryover: a 17-game NFL year is far too
    short to rebuild a rating from 1500 every autumn."""
    games = []
    for lg in FOOTBALL:
        p = os.path.join(DATA, f"{lg}_games.json")
        if os.path.exists(p):
            for g in json.load(open(p)):
                g = dict(g); g["lg"] = lg
                games.append(g)
        # current season to date (empty until kickoff, cheap either way)
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{FB_PATH[lg]}"
               f"/scoreboard?dates=20260801-{today.replace('-', '')}&limit=1000")
        for ev in (get(url) or {}).get("events", []):
            if (ev.get("season") or {}).get("type") not in (2, 3):
                continue                      # preseason is noise
            try:
                c = ev["competitions"][0]
                if not c["status"]["type"].get("completed"):
                    continue
                cs = c["competitors"]
                h = next(x for x in cs if x["homeAway"] == "home")
                a = next(x for x in cs if x["homeAway"] == "away")
                if int(h["score"]) == int(a["score"]):
                    continue
                games.append(dict(lg=lg, date=ev["date"][:10],
                                  season=(ev.get("season") or {}).get("year"),
                                  home=h["team"]["displayName"],
                                  away=a["team"]["displayName"],
                                  hs=int(h["score"]), as_=int(a["score"]),
                                  neutral=bool(c.get("neutralSite"))))
            except Exception:
                continue
    return games


def build_ratings(games):
    elo, cnt, form = defaultdict(lambda: 1500.0), defaultdict(int), defaultdict(list)
    season_of = {}
    for g in games:
        lg = g["lg"]; K, hfa, _ = ELO[lg]
        # season rollover (football only): regress toward the mean
        s = g.get("season")
        if s is not None and season_of.get(lg) not in (None, s):
            for key in [k for k in elo if k[0] == lg]:
                elo[key] = 1500 + (elo[key] - 1500) * (1 - CARRY)
        if s is not None:
            season_of[lg] = s

        adv = 0.0 if g.get("neutral") else hfa
        rh, ra = elo[(lg, g["home"])], elo[(lg, g["away"])]
        p = 1 / (1 + 10 ** (-((rh + adv) - ra) / 400))
        hw = g["hs"] > g["as_"]
        d = K * math.log(abs(g["hs"] - g["as_"]) + 1) * ((1.0 if hw else 0.0) - p)
        elo[(lg, g["home"])] += d; elo[(lg, g["away"])] -= d
        cnt[(lg, g["home"])] += 1; cnt[(lg, g["away"])] += 1
        form[(lg, g["home"])].append(1 if hw else 0)
        form[(lg, g["away"])].append(0 if hw else 1)
    return elo, cnt, form


def slate(target):
    out = []
    d = get(MLB_API.format(target, target))
    for blk in (d or {}).get("dates", []):
        for g in blk["games"]:
            if g["status"]["abstractGameState"] == "Final":
                continue
            h, a = g["teams"]["home"], g["teams"]["away"]
            hp = (h.get("probablePitcher") or {}).get("fullName")
            ap = (a.get("probablePitcher") or {}).get("fullName")
            out.append(dict(lg="mlb", home=h["team"]["name"], away=a["team"]["name"],
                            time=g["gameDate"], hp=hp, ap=ap))
    tgt = target.replace("-", "")
    for lg in FOOTBALL:
        url = (f"https://site.api.espn.com/apis/site/v2/sports/{FB_PATH[lg]}"
               f"/scoreboard?dates={tgt}&limit=300")
        for ev in (get(url) or {}).get("events", []):
            if (ev.get("season") or {}).get("type") not in (2, 3):
                continue
            try:
                c = ev["competitions"][0]
                if c["status"]["type"].get("completed"):
                    continue
                cs = c["competitors"]
                h = next(x for x in cs if x["homeAway"] == "home")
                a = next(x for x in cs if x["homeAway"] == "away")
                out.append(dict(lg=lg, home=h["team"]["displayName"],
                                away=a["team"]["displayName"], time=ev["date"],
                                hp=None, ap=None,
                                neutral=bool(c.get("neutralSite"))))
            except Exception:
                continue
    w = get(ESPN.format(tgt, tgt))
    for ev in (w or {}).get("events", []):
        try:
            c = ev["competitions"][0]
            if c["status"]["type"].get("completed"):
                continue
            cs = c["competitors"]
            h = next(x for x in cs if x["homeAway"] == "home")
            a = next(x for x in cs if x["homeAway"] == "away")
            out.append(dict(lg="wnba", home=h["team"]["displayName"],
                            away=a["team"]["displayName"], time=ev["date"],
                            hp=None, ap=None))
        except Exception:
            continue
    return out


def rate(games, elo, cnt, form):
    picks = []
    for g in games:
        lg = g["lg"]; _, hfa, _ = ELO[lg]
        rh, ra = elo[(lg, g["home"])], elo[(lg, g["away"])]
        if not cnt[(lg, g["home"])] or not cnt[(lg, g["away"])]:
            continue
        adv = 0.0 if g.get("neutral") else hfa
        p = 1 / (1 + 10 ** (-((rh + adv) - ra) / 400))
        pick, conf = (g["home"], p) if p >= .5 else (g["away"], 1 - p)
        opp = g["away"] if pick == g["home"] else g["home"]
        f = form[(lg, pick)][-10:]
        picks.append(dict(lg=lg, matchup=f"{g['away']} @ {g['home']}", pick=pick,
                          opponent=opp,
                          conf=conf, home=g["home"], away=g["away"],
                          elo_h=rh, elo_a=ra, time=g["time"],
                          hp=g["hp"], ap=g["ap"],
                          last10=f"{sum(f)}-{len(f)-sum(f)}" if f else "-"))
    picks.sort(key=lambda x: -x["conf"])
    return picks


def tier_of(c):
    for name, lo, hit in TIERS:
        if c >= lo:
            return name, hit
    return TIERS[-1][0], TIERS[-1][2]


def render(picks, target, asof):
    when = dt.date.fromisoformat(target).strftime("%A, %B %-d, %Y") \
        if os.name != "nt" else dt.date.fromisoformat(target).strftime("%A, %B %d, %Y")
    L = []
    L.append(f"# The Edge Report — {when}")
    L.append("")
    L.append(f"*{len(picks)} games rated. Ratings current through {asof}.*")
    L.append("")
    top = [p for p in picks if p["conf"] >= 0.60]
    if top:
        L.append("## Today's best calls")
        L.append("")
        L.append("| Confidence | Pick | Matchup | Tier |")
        L.append("|---|---|---|---|")
        for p in top[:8]:
            t, _ = tier_of(p["conf"])
            L.append(f"| **{p['conf']:.0%}** | **{p['pick']}** | {p['matchup']} | {t} |")
        L.append("")
    else:
        L.append("## No strong calls today")
        L.append("")
        L.append("Every game on the board rates under 60%. That is a real signal, "
                 "not a missing one — see the note at the bottom.")
        L.append("")
    for lg, label in (("cfb", "College Football"), ("nfl", "NFL"),
                      ("wnba", "WNBA"), ("mlb", "MLB")):
        sub = [p for p in picks if p["lg"] == lg]
        if not sub:
            continue
        L.append(f"## {label} — full slate")
        L.append("")
        L.append("| Matchup | Pick | Conf | Last 10 | Absences |")
        L.append("|---|---|---|---|---|")
        for p in sub:
            op, oo = p.get("out_pick"), p.get("out_opp")
            inj = "—" if op is None else f"{op} out / {oo} opp"
            L.append(f"| {p['matchup']} | {p['pick']} | {p['conf']:.0%} "
                     f"| {p['last10']} | {inj} |")
        L.append("")
    L.append("## How to read this")
    L.append("")
    L.append("| Tier | Confidence | Hit rate in testing |")
    L.append("|---|---|---|")
    for name, lo, hit in TIERS:
        L.append(f"| {name} | {lo:.0%}+ | {hit} |")
    L.append("")
    L.append("Those hit rates come from **18,606 games** graded out-of-sample "
             "between June 2025 and August 2026. Ratings only ever use games "
             "played before the one being predicted.")
    L.append("")
    L.append("**A word on MLB:** baseball games are close to coin flips. Across "
             "3,255 games the model hit 54.5%, and it has never once rated an MLB "
             "game above 85%. When every baseball pick here reads 52–58%, that is "
             "the honest number, not a hedge.")
    L.append("")
    L.append("**This is not betting advice.** Tested against real closing "
             "moneylines, these picks lose 5.5% per bet — the market prices them "
             "at least as well as the model does. It is good at predicting "
             "winners and bad at beating prices. Those are different skills.")
    return "\n".join(L)


DEAD_BAND = 0.58   # below this the model is not meaningfully differentiating


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def bar(conf):
    """Confidence rendered as edge over a coin flip: 50% empty, 100% full."""
    pct = max(0.0, min(1.0, (conf - 0.5) / 0.5)) * 100
    dead = conf < DEAD_BAND
    cls = "fill dead" if dead else ("fill hot" if conf >= 0.70 else "fill")
    return (f'<span class="meter"><span class="{cls}" style="width:{pct:.1f}%"></span></span>'
            f'<span class="num{" muted" if dead else ""}">{conf:.0%}</span>')


def render_html(picks, target, asof):
    when = dt.date.fromisoformat(target).strftime("%A, %B %d, %Y").replace(" 0", " ")
    top = [p for p in picks if p["conf"] >= 0.60][:6]
    wn = [p for p in picks if p["lg"] == "wnba"]
    mb = [p for p in picks if p["lg"] == "mlb"]
    fb = [p for p in picks if p["lg"] in ("nfl", "cfb")]
    noise = sum(1 for p in picks if p["conf"] < DEAD_BAND)

    def rows(sub):
        out = []
        for p in sub:
            op, oo = p.get("out_pick"), p.get("out_opp")
            if op is None:
                inj = '<span class="dim">&mdash;</span>'
            else:
                edge = "adv" if oo > op else ("dis" if op > oo else "")
                inj = (f'<span class="inj {edge}" title="{esc(p.get("key_out") or "none")}">'
                       f'{op}<span class="dim"> / {oo}</span></span>')
            out.append(
                f'<tr><td class="mu">{esc(p["matchup"])}</td>'
                f'<td class="pk">{esc(p["pick"])}</td>'
                f'<td class="cf">{bar(p["conf"])}</td>'
                f'<td class="l10">{esc(p["last10"])}</td>'
                f'<td class="l10">{inj}</td></tr>')
        return "\n".join(out)

    cards = "\n".join(
        f'<article class="card{" lead" if i == 0 else ""}">'
        f'<div class="cnum">{p["conf"]:.0%}</div>'
        f'<div class="cpick">{esc(p["pick"])}</div>'
        f'<div class="cmatch">{esc(p["matchup"])}</div>'
        f'<div class="ctier">{esc(tier_of(p["conf"])[0])} &middot; hits {esc(tier_of(p["conf"])[1])} in testing</div>'
        f'</article>' for i, p in enumerate(top))

    return f"""<title>The Edge Report &mdash; {esc(when)}</title>
<style>
:root {{
  --ink:#12161C; --paper:#ECEEF1; --card:#FFFFFF; --line:#C9D0D8;
  --mute:#5C6773; --signal:#0F8F94; --signal-deep:#0A5F63; --sand:#8C7A4F;
  --dead:#9AA5B1;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --ink:#E6EAEF; --paper:#0E1217; --card:#161C24; --line:#2A333E;
    --mute:#8895A4; --signal:#2BB3B8; --signal-deep:#7FD6D9; --sand:#C0A868;
    --dead:#4A5561; }}
}}
:root[data-theme="dark"] {{
  --ink:#E6EAEF; --paper:#0E1217; --card:#161C24; --line:#2A333E;
  --mute:#8895A4; --signal:#2BB3B8; --signal-deep:#7FD6D9; --sand:#C0A868;
  --dead:#4A5561;
}}
:root[data-theme="light"] {{
  --ink:#12161C; --paper:#ECEEF1; --card:#FFFFFF; --line:#C9D0D8;
  --mute:#5C6773; --signal:#0F8F94; --signal-deep:#0A5F63; --sand:#8C7A4F;
  --dead:#9AA5B1;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:820px; margin:0 auto; padding:40px 22px 80px;
  display:flex; flex-direction:column; gap:38px; }}
.mast {{ display:flex; flex-direction:column; gap:10px;
  border-bottom:2px solid var(--ink); padding-bottom:16px; }}
h1 {{ font-family:Georgia,"Times New Roman",serif; font-weight:700;
  font-size:clamp(34px,6.5vw,54px); line-height:1.02; letter-spacing:-.025em;
  margin:0; text-wrap:balance; }}
.dateline {{ font-family:ui-monospace,Consolas,Menlo,monospace; font-size:12px;
  letter-spacing:.13em; text-transform:uppercase; color:var(--mute); }}
h2 {{ font-family:Georgia,serif; font-size:23px; letter-spacing:-.01em;
  margin:0 0 14px; }}
section {{ display:flex; flex-direction:column; }}
.strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(132px,1fr));
  gap:1px; background:var(--line); border:1px solid var(--line); }}
.strip div {{ background:var(--card); padding:12px 14px; }}
.strip .k {{ font-family:ui-monospace,Consolas,monospace; font-size:11px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--mute); }}
.strip .v {{ font-family:ui-monospace,Consolas,monospace; font-size:20px;
  font-weight:600; font-variant-numeric:tabular-nums; color:var(--signal-deep); }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(228px,1fr)); gap:12px; }}
.card {{ background:var(--card); border:1px solid var(--line);
  border-left:3px solid var(--signal); padding:15px 17px;
  display:flex; flex-direction:column; gap:3px; }}
.card.lead {{ border-left-color:var(--signal-deep); }}
.cnum {{ font-family:ui-monospace,Consolas,monospace; font-size:31px; font-weight:600;
  font-variant-numeric:tabular-nums; color:var(--signal-deep); line-height:1; }}
.cpick {{ font-weight:650; font-size:17px; }}
.cmatch {{ color:var(--mute); font-size:13.5px; }}
.ctier {{ font-family:ui-monospace,Consolas,monospace; font-size:10.5px;
  letter-spacing:.07em; text-transform:uppercase; color:var(--mute); margin-top:5px; }}
.scroll {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:14.5px; }}
th {{ font-family:ui-monospace,Consolas,monospace; font-size:10.5px;
  letter-spacing:.1em; text-transform:uppercase; color:var(--mute);
  text-align:left; font-weight:500; padding:0 10px 7px 0;
  border-bottom:1px solid var(--line); white-space:nowrap; }}
td {{ padding:9px 10px 9px 0; border-bottom:1px solid var(--line); vertical-align:middle; }}
.mu {{ color:var(--mute); }}
.pk {{ font-weight:640; white-space:nowrap; }}
.cf {{ display:flex; align-items:center; gap:9px; min-width:132px; }}
.l10 {{ font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums;
  color:var(--mute); font-size:13px; }}
.meter {{ display:block; width:72px; height:7px; background:var(--line); flex:none; }}
.fill {{ display:block; height:100%; background:var(--signal); }}
.fill.hot {{ background:var(--signal-deep); }}
.fill.dead {{ background:var(--dead); }}
.num {{ font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums;
  font-weight:600; font-size:13.5px; }}
.num.muted {{ color:var(--mute); font-weight:400; }}
.dim {{ color:var(--mute); }}
.inj {{ font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums;
  font-weight:600; cursor:help; }}
.inj.adv {{ color:var(--signal-deep); }}
.inj.dis {{ color:var(--sand); }}
.note {{ border-left:3px solid var(--sand); padding:2px 0 2px 16px; color:var(--ink); }}
.note b {{ color:var(--sand); }}
.foot {{ border-top:2px solid var(--ink); padding-top:16px; display:flex;
  flex-direction:column; gap:16px; font-size:14.5px; }}
a {{ color:var(--signal-deep); }}
:focus-visible {{ outline:2px solid var(--signal); outline-offset:2px; }}
</style>

<div class="wrap">
  <header class="mast">
    <div class="dateline">Daily model picks &middot; Issue for {esc(when)}</div>
    <h1>The Edge Report</h1>
    <div class="dateline">{len(picks)} games rated &middot; ratings current through {esc(asof)}</div>
  </header>

  <section>
    <h2>What these numbers have actually done</h2>
    <div class="strip">
      <div><div class="k">Games graded</div><div class="v">18,606</div></div>
      <div><div class="k">85%+ tier</div><div class="v">84%</div></div>
      <div><div class="k">70%+ tier</div><div class="v">71%</div></div>
      <div><div class="k">Every game</div><div class="v">57%</div></div>
    </div>
  </section>

  <section>
    <h2>Today's best calls</h2>
    <div class="cards">{cards}</div>
  </section>

  <section>
    <h2>WNBA &mdash; full slate</h2>
    <div class="scroll"><table>
      <thead><tr><th>Matchup</th><th>Pick</th><th>Confidence</th><th>Last 10</th><th>Out / opp</th></tr></thead>
      <tbody>{rows(wn)}</tbody>
    </table></div>
  </section>

  <section>
    <h2>MLB &mdash; full slate</h2>
    <div class="scroll"><table>
      <thead><tr><th>Matchup</th><th>Pick</th><th>Confidence</th><th>Last 10</th><th>Out / opp</th></tr></thead>
      <tbody>{rows(mb)}</tbody>
    </table></div>
  </section>

  <footer class="foot">
    <p class="note"><b>The grey bars are the honest part.</b> {noise} of today's
    {len(picks)} games rate below 58% &mdash; close enough to a coin flip that the
    model is not really telling you anything. Baseball lives here almost every day:
    across 3,255 MLB games it hit 54.5%, and it has never rated one above 85%.</p>

    <p class="note"><b>This is not betting advice.</b> Graded against real closing
    moneylines, these picks lose about 5.5% per bet. The market prices them at least
    as well as the model does. Predicting winners and beating prices are different
    skills, and this only has the first one.</p>

    <p style="color:var(--mute);font-size:13.5px">Ratings are Elo, updated only after
    a game is played, so nothing here has seen its own result. Confidence bars show
    edge over a coin flip: an empty bar is 50%, a full bar is 100%.</p>
  </footer>
</div>"""


def main():
    today = dt.date.today()   # never hardcode: it silently dates the issue wrong
    target = sys.argv[1] if len(sys.argv) > 1 else (today + dt.timedelta(days=1)).isoformat()
    print(f"building newsletter for {target} ...")
    hist = load_history(today.isoformat())
    print(f"  history: {len(hist)} completed games")
    elo, cnt, form = build_ratings(hist)
    games = slate(target)
    print(f"  slate: {len(games)} games")
    picks = rate(games, elo, cnt, form)
    print(f"  rated: {len(picks)}")
    try:
        import news
        news.annotate(picks)
        print(f"  injury context attached for "
              f"{sum(1 for p in picks if p.get('out_pick') or p.get('out_opp'))} picks")
    except Exception as e:
        print(f"  (injury feed unavailable: {type(e).__name__})")
    md = render(picks, target, hist[-1]["date"] if hist else "n/a")
    asof = hist[-1]["date"] if hist else "n/a"
    path = os.path.join(OUT, f"newsletter_{target}.md")
    open(path, "w", encoding="utf-8").write(md)
    hpath = os.path.join(OUT, f"newsletter_{target}.html")
    open(hpath, "w", encoding="utf-8").write(render_html(picks, target, asof))
    # stable filename so the published issue keeps one URL across days
    latest = os.path.join(OUT, "newsletter_latest.html")
    open(latest, "w", encoding="utf-8").write(render_html(picks, target, asof))
    print(f"wrote {path}")
    print(f"wrote {hpath}")
    print(f"wrote {latest}  (stable URL target)")
    print("\n" + "=" * 60)
    print(md[:1800])


if __name__ == "__main__":
    main()
