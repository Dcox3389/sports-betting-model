"""
Issue archive: how did every newsletter actually do?

Back-issues are reconstructed with the SAME walk-forward rule the live
newsletter uses -- ratings for an issue dated D only ever see games played
before D. So a back-issue is exactly what the newsletter would have printed
that morning, not a hindsight rewrite.

    python archive.py            # rebuild archive from 2026-06-01
    python archive.py 2026-07-01 # from a different start

Writes out/archive.html and out/archive_picks.csv
"""
import csv, json, math, os, sys, datetime as dt
from collections import defaultdict
from config import OUT, ELO
from newsletter import load_history, TIERS, tier_of, DEAD_BAND, esc

BACKFILL_FROM = "2026-06-01"
TODAY = dt.date.today()   # never hardcode: it silently truncates the archive


def grade(history, start):
    """Replay day by day. Rate each day's games using only prior games."""
    elo, cnt, form = defaultdict(lambda: 1500.0), defaultdict(int), defaultdict(list)
    by_day = defaultdict(list)
    for g in history:
        by_day[g["date"]].append(g)

    issues = []
    for day in sorted(by_day):
        picks = []
        if day >= start:
            for g in by_day[day]:
                lg = g["lg"]; _, hfa, minp = ELO[lg]
                if cnt[(lg, g["home"])] < minp or cnt[(lg, g["away"])] < minp:
                    continue
                rh, ra = elo[(lg, g["home"])], elo[(lg, g["away"])]
                p = 1 / (1 + 10 ** (-((rh + hfa) - ra) / 400))
                pick, conf = (g["home"], p) if p >= .5 else (g["away"], 1 - p)
                won = (g["hs"] > g["as_"]) == (pick == g["home"])
                picks.append(dict(date=day, lg=lg, pick=pick, conf=conf,
                                  matchup=f"{g['away']} @ {g['home']}",
                                  score=f"{g['as_']}-{g['hs']}", hit=int(won),
                                  tier=tier_of(conf)[0]))
        # update ratings AFTER the day is graded
        for g in by_day[day]:
            lg = g["lg"]; K, hfa, _ = ELO[lg]
            rh, ra = elo[(lg, g["home"])], elo[(lg, g["away"])]
            p = 1 / (1 + 10 ** (-((rh + hfa) - ra) / 400))
            hw = g["hs"] > g["as_"]
            d = K * math.log(abs(g["hs"] - g["as_"]) + 1) * ((1.0 if hw else 0.0) - p)
            elo[(lg, g["home"])] += d; elo[(lg, g["away"])] -= d
            cnt[(lg, g["home"])] += 1; cnt[(lg, g["away"])] += 1
        if picks:
            picks.sort(key=lambda x: -x["conf"])
            issues.append(dict(date=day, picks=picks))
    return issues


def stats(picks):
    n = len(picks)
    return (n, sum(p["hit"] for p in picks) / n if n else 0.0)


def render_html(issues, allp):
    n, acc = stats(allp)
    tiers = []
    for name, lo, claimed in TIERS:
        sub = [p for p in allp if p["tier"] == name]
        if sub:
            tiers.append((name, int(claimed.rstrip("%")) / 100, stats(sub)[1], len(sub), lo))
    rows = [(i["date"], len(i["picks"]), sum(p["hit"] for p in i["picks"]),
             stats(i["picks"])[1]) for i in issues]

    # ---- dot plot: claimed vs delivered, position-encoded (axis 45-90) ----
    # Absolute units on an 800-wide canvas so the SVG scales proportionally.
    # (A percentage/preserveAspectRatio="none" layout stretches the text.)
    W, LO, HI = 800, 0.45, 0.90
    PAD_L, PLOT_W = 132, 596
    def x(v):
        return PAD_L + (v - LO) / (HI - LO) * PLOT_W
    dp_h = 46 * len(tiers) + 40
    dp = []
    for g in (0.5, 0.6, 0.7, 0.8, 0.9):
        dp.append(f'<line class="axis" x1="{x(g):.1f}" y1="10" x2="{x(g):.1f}" y2="{dp_h-26}"/>')
        dp.append(f'<text class="ax" x="{x(g):.1f}" y="{dp_h-10}" '
                  f'text-anchor="middle">{g:.0%}</text>')
    for i, (name, claimed, actual, cnt_, _) in enumerate(tiers):
        y = 30 + i * 46
        xa, xc = x(actual), x(claimed)
        dp.append(f'<line class="connect" x1="{min(xa,xc):.1f}" y1="{y}" '
                  f'x2="{max(xa,xc):.1f}" y2="{y}"/>')
        dp.append(f'<line class="tick" x1="{xc:.1f}" y1="{y-10}" x2="{xc:.1f}" y2="{y+10}">'
                  f'<title>{esc(name)}: claimed {claimed:.0%}</title></line>')
        dp.append(f'<circle class="dot" cx="{xa:.1f}" cy="{y}" r="6.5">'
                  f'<title>{esc(name)}: delivered {actual:.0%} on {cnt_} picks</title></circle>')
        dp.append(f'<text class="lbl-l" x="0" y="{y-3}">{esc(name)}</text>')
        dp.append(f'<text class="lbl-n" x="0" y="{y+14}">{cnt_} picks</text>')
        anchor = "start" if xa >= xc else "end"
        off = 13 if xa >= xc else -13
        dp.append(f'<text class="val" x="{xa+off:.1f}" y="{y+4}" '
                  f'text-anchor="{anchor}">{actual:.0%}</text>')

    # ---- per-issue deviation from a coin flip ----
    st_h, mid, SL, SW = 170, 78, 40, 720
    bw = SW / max(1, len(rows))
    st = []
    for gl, lab in ((0.75, "75%"), (0.5, "50%"), (0.25, "25%")):
        gy = mid - (gl - 0.5) * 150
        if gl != 0.5:
            st.append(f'<line class="axis" x1="{SL}" y1="{gy:.1f}" x2="{SL+SW}" y2="{gy:.1f}"/>')
            st.append(f'<text class="ax" x="{SL-8}" y="{gy+4:.1f}" text-anchor="end">{lab}</text>')
    for i, (d, cnt_, hits, r) in enumerate(rows):
        px = SL + i * bw
        h = (r - 0.5) * 150
        cls = "up" if r >= 0.5 else "down"
        st.append(f'<rect class="dev {cls}" x="{px:.1f}" y="{(mid-h if h>=0 else mid):.1f}" '
                  f'width="{max(bw*0.66,1.4):.1f}" height="{max(abs(h),1.2):.1f}" rx="1">'
                  f'<title>{esc(d)} &mdash; {hits}/{cnt_} ({r:.0%})</title></rect>')
    st.append(f'<line class="base" x1="{SL}" y1="{mid}" x2="{SL+SW}" y2="{mid}"/>')
    st.append(f'<text class="ax" x="{SL-8}" y="{mid+4}" text-anchor="end">50%</text>')
    st.append(f'<text class="ax" x="{SL}" y="{st_h-6}">{esc(rows[0][0])}</text>')
    st.append(f'<text class="ax" x="{SL+SW}" y="{st_h-6}" '
              f'text-anchor="end">{esc(rows[-1][0])}</text>')

    recent = rows[::-1][:14]
    trs = "\n".join(
        f'<tr><td class="d">{esc(d)}</td><td class="rec">{h}/{c}</td>'
        f'<td class="pc {"good" if r>=0.5 else "bad"}">{r:.0%}</td></tr>'
        for d, c, h, r in recent)

    wn = [p for p in allp if p["lg"] == "wnba"]
    mb = [p for p in allp if p["lg"] == "mlb"]
    # A one-game day isn't an issue -- ranking on it yields a meaningless 100%/0%.
    MIN_ISSUE = 4
    sized = [r for r in rows if r[1] >= MIN_ISSUE] or rows
    best = max(sized, key=lambda r: (r[3], r[1]))
    worst = min(sized, key=lambda r: (r[3], -r[1]))

    return f"""<title>The Edge Report &mdash; Archive</title>
<style>
:root {{
  --ink:#12161C; --paper:#ECEEF1; --card:#FFFFFF; --line:#C9D0D8; --mute:#5C6773;
  --signal:#0F8F94; --signal-deep:#0A5F63; --sand:#8C7A4F; --down:#B4423F; --grid:#DFE4E9;
}}
@media (prefers-color-scheme: dark) {{
  :root {{ --ink:#E6EAEF; --paper:#0E1217; --card:#161C24; --line:#2A333E; --mute:#8895A4;
    --signal:#2BB3B8; --signal-deep:#7FD6D9; --sand:#C0A868; --down:#E07572; --grid:#232C36; }}
}}
:root[data-theme="dark"] {{
  --ink:#E6EAEF; --paper:#0E1217; --card:#161C24; --line:#2A333E; --mute:#8895A4;
  --signal:#2BB3B8; --signal-deep:#7FD6D9; --sand:#C0A868; --down:#E07572; --grid:#232C36;
}}
:root[data-theme="light"] {{
  --ink:#12161C; --paper:#ECEEF1; --card:#FFFFFF; --line:#C9D0D8; --mute:#5C6773;
  --signal:#0F8F94; --signal-deep:#0A5F63; --sand:#8C7A4F; --down:#B4423F; --grid:#DFE4E9;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }}
.wrap {{ max-width:860px; margin:0 auto; padding:40px 22px 80px;
  display:flex; flex-direction:column; gap:36px; }}
.mast {{ border-bottom:2px solid var(--ink); padding-bottom:16px;
  display:flex; flex-direction:column; gap:9px; }}
h1 {{ font-family:Georgia,"Times New Roman",serif; font-size:clamp(32px,6vw,50px);
  line-height:1.03; letter-spacing:-.025em; margin:0; text-wrap:balance; }}
.dateline {{ font-family:ui-monospace,Consolas,Menlo,monospace; font-size:12px;
  letter-spacing:.13em; text-transform:uppercase; color:var(--mute); }}
h2 {{ font-family:Georgia,serif; font-size:22px; margin:0 0 5px; letter-spacing:-.01em; }}
.sub {{ color:var(--mute); font-size:14.5px; margin:0 0 16px; max-width:64ch; }}
section {{ display:flex; flex-direction:column; }}
.tiles {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:1px; background:var(--line); border:1px solid var(--line); }}
.tiles div {{ background:var(--card); padding:13px 15px; }}
.tiles .k {{ font-family:ui-monospace,Consolas,monospace; font-size:10.5px;
  letter-spacing:.11em; text-transform:uppercase; color:var(--mute); }}
.tiles .v {{ font-family:ui-monospace,Consolas,monospace; font-size:25px; font-weight:600;
  font-variant-numeric:tabular-nums; color:var(--signal-deep); line-height:1.25; }}
.tiles .s {{ font-size:12.5px; color:var(--mute); }}
figure {{ margin:0; background:var(--card); border:1px solid var(--line); padding:16px 18px 10px; }}
svg {{ display:block; width:100%; height:auto; }}
.dot {{ fill:var(--signal); }}
.tick {{ stroke:var(--ink); stroke-width:2.5; }}
.connect {{ stroke:var(--mute); stroke-width:1.5; stroke-dasharray:2 3; }}
.axis {{ stroke:var(--grid); stroke-width:1; }}
.ax {{ fill:var(--mute); font-size:10.5px; font-family:ui-monospace,Consolas,monospace; }}
.lbl-l {{ fill:var(--ink); font-size:13px; font-weight:640; }}
.lbl-n {{ fill:var(--mute); font-size:11px; font-family:ui-monospace,Consolas,monospace; }}
.val {{ fill:var(--ink); font-size:12.5px; font-weight:650;
  font-family:ui-monospace,Consolas,monospace; }}
.legend {{ display:flex; gap:20px; align-items:center; padding:8px 0 2px;
  font-size:12.5px; color:var(--mute); flex-wrap:wrap; }}
.legend span {{ display:inline-flex; align-items:center; gap:7px; }}
.sw-dot {{ width:12px; height:12px; border-radius:50%; background:var(--signal); }}
.sw-tick {{ width:3px; height:14px; background:var(--ink); }}
.dev {{ fill:var(--signal); }}
.dev.down {{ fill:var(--down); }}
.dev:hover {{ opacity:.65; }}
.base {{ stroke:var(--ink); stroke-width:1.5; }}
table {{ width:100%; border-collapse:collapse; font-size:14.5px; }}
th {{ font-family:ui-monospace,Consolas,monospace; font-size:10.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--mute); text-align:left; font-weight:500;
  padding:0 10px 7px 0; border-bottom:1px solid var(--line); }}
td {{ padding:8px 10px 8px 0; border-bottom:1px solid var(--line); }}
.d, .rec, .pc {{ font-family:ui-monospace,Consolas,monospace;
  font-variant-numeric:tabular-nums; }}
.pc {{ font-weight:650; }} .pc.good {{ color:var(--signal-deep); }} .pc.bad {{ color:var(--down); }}
.scroll {{ overflow-x:auto; }}
.note {{ border-left:3px solid var(--sand); padding:2px 0 2px 16px; }}
.note b {{ color:var(--sand); }}
.foot {{ border-top:2px solid var(--ink); padding-top:16px; display:flex;
  flex-direction:column; gap:15px; font-size:14.5px; }}
:focus-visible {{ outline:2px solid var(--signal); outline-offset:2px; }}
@media (prefers-reduced-motion:reduce) {{ * {{ transition:none !important; }} }}
</style>

<div class="wrap">
  <header class="mast">
    <div class="dateline">The Edge Report &middot; Performance archive</div>
    <h1>Every pick we've published</h1>
    <div class="dateline">{len(issues)} issues &middot; {n:,} graded picks &middot;
      through {esc(rows[-1][0])}</div>
  </header>

  <section>
    <div class="tiles">
      <div><div class="k">Issues</div><div class="v">{len(issues)}</div></div>
      <div><div class="k">Picks graded</div><div class="v">{n:,}</div></div>
      <div><div class="k">Overall</div><div class="v">{acc:.1%}</div></div>
      <div><div class="k">Best issue</div><div class="v">{best[3]:.0%}</div>
        <div class="s">{esc(best[0])} &middot; {best[2]}/{best[1]}</div></div>
      <div><div class="k">Worst issue</div><div class="v">{worst[3]:.0%}</div>
        <div class="s">{esc(worst[0])} &middot; {worst[2]}/{worst[1]}</div></div>
    </div>
  </section>

  <section>
    <h2>Do the tier labels hold up?</h2>
    <p class="sub">Every issue prints a confidence tier. This is what each tier
      promised against what it actually delivered, graded one day at a time.</p>
    <figure>
      <svg viewBox="0 0 {W} {dp_h}" role="img"
           aria-label="Delivered versus claimed hit rate by confidence tier">
        {chr(10).join(dp)}
      </svg>
      <div class="legend">
        <span><span class="sw-dot"></span>Delivered</span>
        <span><span class="sw-tick"></span>Claimed on the tier label</span>
      </div>
    </figure>
  </section>

  <section>
    <h2>Issue by issue</h2>
    <p class="sub">Each bar is one issue, measured against a coin flip. Above the
      line beat 50%, below it didn't. The spread is the point &mdash; single days
      are noisy even when the aggregate is stable.</p>
    <figure>
      <svg viewBox="0 0 {W} {st_h}" role="img"
           aria-label="Per-issue hit rate relative to 50 percent">
        {chr(10).join(st)}
      </svg>
      <div class="legend">
        <span><span class="sw-dot"></span>Beat a coin flip</span>
        <span><span class="sw-dot" style="background:var(--down)"></span>Did not</span>
        <span>Baseline = 50%</span>
      </div>
    </figure>
  </section>

  <section>
    <h2>By league</h2>
    <div class="tiles">
      <div><div class="k">WNBA</div><div class="v">{stats(wn)[1]:.1%}</div>
        <div class="s">{len(wn)} picks</div></div>
      <div><div class="k">MLB</div><div class="v">{stats(mb)[1]:.1%}</div>
        <div class="s">{len(mb)} picks</div></div>
    </div>
  </section>

  <section>
    <h2>Recent issues</h2>
    <div class="scroll"><table>
      <thead><tr><th>Issue</th><th>Record</th><th>Hit rate</th></tr></thead>
      <tbody>{trs}</tbody>
    </table></div>
  </section>

  <footer class="foot">
    <p class="note"><b>Back-issues aren't rewritten.</b> Ratings for an issue dated
      D only ever see games played before D, so each back-issue is what the
      newsletter would have printed that morning &mdash; not a hindsight edit.</p>
    <p class="note"><b>MLB is dragging the average, on purpose.</b> Baseball is
      {stats(mb)[1]:.1%} across {len(mb)} picks and we publish it anyway, because
      a picks sheet that quietly drops its worst sport isn't a track record.</p>
    <p style="color:var(--mute);font-size:13.5px">Not betting advice. Against real
      closing moneylines these picks lose about 5.5% per bet.</p>
  </footer>
</div>"""


def main():
    start = sys.argv[1] if len(sys.argv) > 1 else BACKFILL_FROM
    hist = load_history(TODAY.isoformat())
    print(f"history: {len(hist)} completed games")
    issues = grade(hist, start)
    allp = [p for i in issues for p in i["picks"]]
    n, acc = stats(allp)
    print(f"issues: {len(issues)}   graded picks: {n}   overall: {acc:.1%}\n")

    print(f"{'tier':<12}{'picks':>7}{'hit':>8}{'claimed':>10}")
    for name, lo, claimed in TIERS:
        sub = [p for p in allp if p["tier"] == name]
        if sub:
            print(f"{name:<12}{len(sub):>7}{stats(sub)[1]:>8.1%}{claimed:>10}")

    print(f"\n{'league':<8}{'picks':>7}{'hit':>8}")
    for lg in ("wnba", "mlb"):
        sub = [p for p in allp if p["lg"] == lg]
        if sub:
            print(f"{lg:<8}{len(sub):>7}{stats(sub)[1]:>8.1%}")

    # best and worst issues
    scored = [(stats(i["picks"])[1], len(i["picks"]), i["date"]) for i in issues
              if len(i["picks"]) >= 4]
    scored.sort(reverse=True)
    print(f"\nbest issue : {scored[0][2]}  {scored[0][0]:.0%} of {scored[0][1]}")
    print(f"worst issue: {scored[-1][2]}  {scored[-1][0]:.0%} of {scored[-1][1]}")

    path = os.path.join(OUT, "archive_picks.csv")
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(allp[0].keys()))
        w.writeheader(); w.writerows(allp)
    print(f"\nwrote {path}")
    json.dump(issues, open(os.path.join(OUT, "archive_issues.json"), "w"))
    hp = os.path.join(OUT, "archive.html")
    open(hp, "w", encoding="utf-8").write(render_html(issues, allp))
    print(f"wrote {hp}")
    return issues


if __name__ == "__main__":
    main()
