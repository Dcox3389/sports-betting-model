"""HTML renderer for the weekly report. Shares the newsletter's design tokens."""
import datetime as dt
from newsletter import esc, bar

CSS = """
:root { --ink:#12161C; --paper:#ECEEF1; --card:#FFFFFF; --line:#C9D0D8; --mute:#5C6773;
  --signal:#0F8F94; --signal-deep:#0A5F63; --sand:#8C7A4F; --neg:#B4423F; --dead:#9AA5B1; }
@media (prefers-color-scheme: dark) { :root { --ink:#E6EAEF; --paper:#0E1217; --card:#161C24;
  --line:#2A333E; --mute:#8895A4; --signal:#2BB3B8; --signal-deep:#7FD6D9; --sand:#C0A868;
  --neg:#E07572; --dead:#4A5561; } }
:root[data-theme="dark"] { --ink:#E6EAEF; --paper:#0E1217; --card:#161C24; --line:#2A333E;
  --mute:#8895A4; --signal:#2BB3B8; --signal-deep:#7FD6D9; --sand:#C0A868; --neg:#E07572;
  --dead:#4A5561; }
:root[data-theme="light"] { --ink:#12161C; --paper:#ECEEF1; --card:#FFFFFF; --line:#C9D0D8;
  --mute:#5C6773; --signal:#0F8F94; --signal-deep:#0A5F63; --sand:#8C7A4F; --neg:#B4423F;
  --dead:#9AA5B1; }
* { box-sizing:border-box; }
body { margin:0; background:var(--paper); color:var(--ink);
  font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif; }
.wrap { max-width:840px; margin:0 auto; padding:40px 22px 80px; display:flex;
  flex-direction:column; gap:34px; }
.mast { border-bottom:2px solid var(--ink); padding-bottom:16px; display:flex;
  flex-direction:column; gap:8px; }
h1 { font-family:Georgia,serif; font-size:clamp(31px,6vw,48px); line-height:1.03;
  letter-spacing:-.025em; margin:0; text-wrap:balance; }
.dateline { font-family:ui-monospace,Consolas,monospace; font-size:12px; letter-spacing:.13em;
  text-transform:uppercase; color:var(--mute); }
h2 { font-family:Georgia,serif; font-size:22px; margin:0 0 5px; letter-spacing:-.01em; }
.sub { color:var(--mute); font-size:14.5px; margin:0 0 14px; max-width:66ch; }
section { display:flex; flex-direction:column; }
table { width:100%; border-collapse:collapse; font-size:14.5px; }
th { font-family:ui-monospace,Consolas,monospace; font-size:10.5px; letter-spacing:.1em;
  text-transform:uppercase; color:var(--mute); text-align:left; font-weight:500;
  padding:0 10px 7px 0; border-bottom:1px solid var(--line); white-space:nowrap; }
td { padding:8px 10px 8px 0; border-bottom:1px solid var(--line); vertical-align:middle; }
.mu { color:var(--mute); } .pk { font-weight:640; white-space:nowrap; }
.l10 { font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums; }
.neg { color:var(--neg); }
tr.ok td { background:rgba(15,143,148,.10); }
.cf { display:flex; align-items:center; gap:9px; min-width:130px; }
.meter { display:block; width:70px; height:7px; background:var(--line); flex:none; }
.fill { display:block; height:100%; background:var(--signal); }
.fill.hot { background:var(--signal-deep); } .fill.dead { background:var(--dead); }
.num { font-family:ui-monospace,Consolas,monospace; font-variant-numeric:tabular-nums;
  font-weight:600; font-size:13.5px; } .num.muted { color:var(--mute); font-weight:400; }
.scroll { overflow-x:auto; }
.note { border-left:3px solid var(--sand); padding:2px 0 2px 16px; }
.note b { color:var(--sand); }
.verdict { border:1px solid var(--line); background:var(--card); padding:17px 19px;
  display:flex; flex-direction:column; gap:7px; }
.verdict .big { font-family:ui-monospace,Consolas,monospace; font-size:27px; font-weight:600;
  color:var(--signal-deep); line-height:1.1; }
.foot { border-top:2px solid var(--ink); padding-top:16px; display:flex;
  flex-direction:column; gap:14px; font-size:14.5px; }
"""


def render(today, days, bylg, ranked, byday, tbl, cfb_rows, true_rate, n_games):
    end = today + dt.timedelta(days - 1)
    span = f"{today.strftime('%b %d')} &ndash; {end.strftime('%b %d, %Y')}"
    clears = [r for r in tbl if r["hit"] >= 0.80]

    lg_rows = "\n".join(
        f'<tr><td class="pk">{esc(lg.upper())}</td><td class="l10">{len(s)}</td>'
        f'<td class="l10">{sum(1 for p in s if p["conf"] >= .85)}</td>'
        f'<td class="l10">{sum(1 for p in s if p["conf"] >= .70)}</td>'
        f'<td class="l10">{sum(1 for p in s if p["conf"] >= .60)}</td></tr>'
        for lg, s in sorted(bylg.items(), key=lambda x: -len(x[1])))

    top = "\n".join(
        f'<tr><td class="l10">{esc(dt.date.fromisoformat(p["date"]).strftime("%a %d"))}</td>'
        f'<td class="pk">{esc(p["pick"])}</td>'
        f'<td class="mu">{esc(p["matchup"])}</td>'
        f'<td class="cf">{bar(p["conf"])}</td>'
        f'<td class="l10">{true_rate(p["conf"], p["lg"]):.0%}</td></tr>'
        for p in ranked[:10])

    par = "\n".join(
        f'<tr class="{"ok" if r["hit"] >= 0.80 else ""}">'
        f'<td class="pk">{r["n"]}</td><td class="l10"><b>{r["hit"]:.1%}</b></td>'
        f'<td class="l10">{r["fair"]:.2f}x</td>'
        f'<td class="l10 neg">{r["ev_book"]:+.1%}</td></tr>' for r in tbl[:8])

    cfb = "\n".join(
        f'<tr class="{"ok" if h >= 0.80 else ""}"><td class="pk">{n}</td>'
        f'<td class="l10"><b>{h:.1%}</b></td><td class="l10">{f:.2f}x</td>'
        f'<td class="l10 neg">{ev:+.1%}</td></tr>' for n, h, f, ev in cfb_rows)

    dayrows = "\n".join(
        f'<tr><td class="pk">{esc(dt.date.fromisoformat(d).strftime("%a %b %d"))}</td>'
        f'<td class="l10">{len(ps)}</td>'
        f'<td class="l10">{sum(1 for p in ps if p["conf"] >= .70)}</td>'
        f'<td class="mu">{esc(max(ps, key=lambda x: x["conf"])["pick"])} '
        f'({max(ps, key=lambda x: x["conf"])["conf"]:.0%})</td></tr>'
        for d, ps in sorted(byday.items()) if ps)

    return f"""<title>Weekly Report &mdash; {span}</title>
<style>{CSS}</style>
<div class="wrap">
  <header class="mast">
    <div class="dateline">The Edge Report &middot; Weekly</div>
    <h1>Week of {span}</h1>
    <div class="dateline">{n_games} games rated across {len(bylg)} leagues</div>
  </header>

  <section>
    <h2>The board</h2>
    <div class="scroll"><table>
      <thead><tr><th>League</th><th>Games</th><th>85%+</th><th>70%+</th><th>60%+</th></tr></thead>
      <tbody>{lg_rows}</tbody></table></div>
  </section>

  <section>
    <h2>Strongest picks of the week</h2>
    <p class="sub">Confidence is what the model says. Tier hits is what that band has
      actually delivered across 1,111 graded picks &mdash; the second number is the one
      to trust.</p>
    <div class="scroll"><table>
      <thead><tr><th>Day</th><th>Pick</th><th>Matchup</th><th>Confidence</th>
        <th>Tier hits</th></tr></thead>
      <tbody>{top}</tbody></table></div>
  </section>

  <section>
    <h2>Day by day</h2>
    <div class="scroll"><table>
      <thead><tr><th>Day</th><th>Games</th><th>70%+</th><th>Best call</th></tr></thead>
      <tbody>{dayrows}</tbody></table></div>
  </section>

  <section>
    <h2>Parlays: can one hold an 80%+ win rate?</h2>
    <p class="sub">Legs priced at measured tier hit rates, not model confidence. The
      model is overconfident below its top tier, so raw numbers would inflate every
      estimate here. Highlighted rows clear 80%.</p>
    <div class="verdict">
      <div class="dateline">This week&rsquo;s board sustains 80%+ up to</div>
      <div class="big">{len(clears)} leg</div>
      <div class="mu">A single top pick hits 84.6%. Adding one more leg drops the slip
        to 71.6% &mdash; under the bar before you have even built a parlay.</div>
    </div>
    <div class="scroll" style="margin-top:14px"><table>
      <thead><tr><th>Legs</th><th>Win rate</th><th>Fair payout</th>
        <th>EV at book prices</th></tr></thead>
      <tbody>{par}</tbody></table></div>
  </section>

  <section>
    <h2>Where 80%+ parlays actually exist</h2>
    <p class="sub">College football headline picks hit 96.6% out-of-sample last season
      across 87 picks. That is high enough to stack. Season opens Aug 29.</p>
    <div class="scroll"><table>
      <thead><tr><th>Legs</th><th>Win rate</th><th>Fair payout</th>
        <th>EV at book prices</th></tr></thead>
      <tbody>{cfb}</tbody></table></div>
  </section>

  <footer class="foot">
    <p class="note"><b>The catch is the payout column.</b> A six-leg college football
      parlay clears 80% &mdash; and pays 1.23x. Fifty dollars returns about sixty-two.
      The win rate is real; the money is not, because the market prices those
      favourites correctly.</p>
    <p class="note"><b>The vig compounds at roughly 4% per leg.</b> That is parlays in
      one line: one leg is &minus;4.1%, six legs &minus;22.1%, ten legs &minus;34.1%.
      Every leg multiplies expected value downward.</p>
    <p style="color:var(--mute);font-size:13.5px">Not betting advice. Graded against real
      closing moneylines these picks return &minus;5.5% per bet. The model predicts
      winners well and does not beat prices &mdash; those are separate skills.</p>
  </footer>
</div>"""
