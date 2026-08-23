"""
Printable tracking sheet for a paper beta test of the model.

This is a RECORD sheet, not a slate of wagers. Each row carries the pick and
its calibrated chance, plus blank columns for what actually happened, so the
model can be tested against reality at zero cost. That is what a beta test is:
if the picks are profitable, a filled-in sheet will show it; if they are not,
nothing was lost proving it.

The "chance" column is NOT the model's raw confidence. Each pick is shown at
the rate its tier has actually hit IN ITS SITUATION -- see calibration.py,
which splits football into early-season and main-season because ratings
entering a season still describe last year's roster. A value marked * is
inherited rather than measured.

    python betsheet.py          # next 7 days
    python betsheet.py 3        # next 3 days
"""
import datetime as dt, os, sys
from collections import defaultdict
from newsletter import load_history, build_ratings, slate, rate, FETCH_ERRORS
from config import OUT

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle, Paragraph,
                                Spacer, PageBreak)

import calibration

INK = colors.HexColor("#12161C")
TEAL = colors.HexColor("#0A5F63")
MUTE = colors.HexColor("#5C6773")
LINE = colors.HexColor("#C9D0D8")
BAND = colors.HexColor("#EEF3F4")
SAND = colors.HexColor("#8C7A4F")


def calibrated(conf, lg, date="2026-01-01"):
    """Hit rate for this pick IN ITS SITUATION -- see calibration.py. Returns
    (rate, thin) where thin marks an inherited rather than measured estimate."""
    rate, n, src = calibration.chance(lg, date, conf)
    return rate, not src.startswith("measured")


def collect(days):
    today = dt.date.today()
    hist = load_history(today.isoformat())
    elo, cnt, form = build_ratings(hist)
    picks = []
    for d in range(days):
        day = (today + dt.timedelta(d)).isoformat()
        for p in rate(slate(day), elo, cnt, form):
            p["date"] = day
            picks.append(p)
    return today, hist, picks


def span_name(today, days):
    """Name files by the window they cover, so a 7-day and a 10-day sheet
    never collide (and so an open viewer holding one file cannot block the
    other)."""
    end = today + dt.timedelta(days - 1)
    return f"betsheet_{today.isoformat()}_to_{end.isoformat()}"


def build_pdf(today, days, picks, hist):
    end = today + dt.timedelta(days - 1)
    path = os.path.join(OUT, span_name(today, days) + ".pdf")
    doc = SimpleDocTemplate(path, pagesize=letter,
                            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            title="Edge Report - Tracking Sheet",
                            author="The Edge Report")
    ss = getSampleStyleSheet()
    h1 = ParagraphStyle("h1", parent=ss["Title"], fontName="Times-Bold",
                        fontSize=22, textColor=INK, alignment=0, spaceAfter=2)
    sub = ParagraphStyle("sub", parent=ss["Normal"], fontName="Helvetica",
                         fontSize=9, textColor=MUTE, spaceAfter=10)
    h2 = ParagraphStyle("h2", parent=ss["Normal"], fontName="Times-Bold",
                        fontSize=13, textColor=INK, spaceBefore=14, spaceAfter=5)
    body = ParagraphStyle("body", parent=ss["Normal"], fontName="Helvetica",
                          fontSize=8.6, textColor=INK, leading=12)
    note = ParagraphStyle("note", parent=body, textColor=SAND,
                          fontName="Helvetica-Oblique", leftIndent=8)

    story = [
        Paragraph("The Edge Report &mdash; Tracking Sheet", h1),
        Paragraph(f"Week of {today.strftime('%B %d')} &ndash; "
                  f"{end.strftime('%B %d, %Y')} &nbsp;&middot;&nbsp; "
                  f"{len(picks)} games rated &nbsp;&middot;&nbsp; "
                  f"ratings built from {len(hist):,} completed games", sub),
        Paragraph(
            "<b>This is a record sheet for a paper test, not a slate of wagers.</b> "
            "Fill in the result column as games finish. After 200+ rows you will "
            "have a real answer about whether these picks are worth money &mdash; "
            "and it will have cost nothing to find out.", body),
        Spacer(1, 4),
        Paragraph(
            "The <b>Chance</b> column is not the model's raw confidence &mdash; the "
            "model is overconfident, saying 82% where it delivers 74%. Each pick is "
            "shown instead at the rate its tier has actually hit <i>in the situation "
            "this pick is being made in</i>. That distinction matters most for "
            "football: college football's top tier hits 96% from week four onward, "
            "but only about 63% of that edge is present in an opening week, when the "
            "ratings still describe last season's roster.", body),
        Spacer(1, 3),
        Paragraph(
            "A Chance marked <b>*</b> is inherited rather than measured &mdash; too "
            "few graded picks exist for that exact tier and situation, so the figure "
            "is shrunk toward a related one. Treat starred rows as the softest "
            "numbers on the sheet.", body),
    ]

    # Instructions go BEFORE the table. They are read once, up front -- and
    # putting them after the rows left a near-empty trailing page whenever the
    # table happened to orphan a row or two.
    story.append(Paragraph("How to run the test", h2))
    for line in [
        "1. Print this sheet, or keep it open, at the start of the week.",
        "2. As each game finishes, mark <b>Won?</b> with Y or N. Do not skip losses.",
        "3. Record the odds offered in <b>Notes</b> if you can &mdash; without them "
        "this measures accuracy only, never profit.",
        "4. At week's end, compare each confidence group against its Chance column. "
        "That is the whole test.",
        "5. Keep sheets. A verdict needs 200+ rows, not one week.",
    ]:
        story.append(Paragraph(line, body))
    story.append(Spacer(1, 5))
    story.append(Paragraph(
        "<b>What this sheet cannot tell you:</b> whether the picks make money. "
        "Accuracy and profit are different questions &mdash; graded against real "
        "prices, these picks returned &minus;5.5% per bet, because the market "
        "prices them at least as well as the model does.", body))
    story.append(Spacer(1, 2))
    story.append(Paragraph(
        "Not betting advice. This sheet exists so the model can be judged on "
        "evidence rather than on a hunch.", note))

    story.append(Paragraph("Picks, strongest first", h2))
    rows = [["Date", "Matchup", "Pick", "Model", "Chance", "Won?", "Notes"]]
    for p in sorted(picks, key=lambda x: -x["conf"]):
        rows.append([
            dt.date.fromisoformat(p["date"]).strftime("%a %m/%d"),
            p["matchup"][:38],
            p["pick"][:22],
            f"{p['conf']:.0%}",
            (lambda rt: f"{rt[0]:.0%}" + ("*" if rt[1] else ""))(
                calibrated(p["conf"], p["lg"], p["date"])),
            "", "",
        ])
    t = Table(rows, colWidths=[0.62 * inch, 2.5 * inch, 1.45 * inch, 0.5 * inch,
                               0.52 * inch, 0.45 * inch, 1.3 * inch], repeatRows=1)
    style = [
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.4),
        ("TEXTCOLOR", (0, 0), (-1, 0), MUTE),
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, INK),
        ("FONT", (0, 1), (-1, -1), "Helvetica", 8.2),
        ("FONT", (2, 1), (2, -1), "Helvetica-Bold", 8.2),
        ("FONT", (3, 1), (4, -1), "Courier", 8.4),
        ("TEXTCOLOR", (4, 1), (4, -1), TEAL),
        ("ALIGN", (3, 1), (4, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LINEBELOW", (0, 1), (-1, -1), 0.25, LINE),
        ("BOX", (5, 1), (6, -1), 0.4, LINE),
        ("INNERGRID", (5, 1), (6, -1), 0.25, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 2.4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.4),
    ]
    for i in range(1, len(rows)):
        if i % 2 == 0:
            style.append(("BACKGROUND", (0, i), (4, i), BAND))
    t.setStyle(TableStyle(style))
    story.append(t)

    doc.build(story)
    return path


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    today, hist, picks = collect(days)
    print(f"rated {len(picks)} games over {days} days from {len(hist)} history")
    if FETCH_ERRORS:
        print(f"  !! {len(FETCH_ERRORS)} source(s) unreachable:")
        for lbl, err in FETCH_ERRORS:
            print(f"     {lbl} ({err})")
        if not picks:
            raise SystemExit(
                "ABORTED: no picks AND failed fetches -- that is a network "
                "failure, not an empty week. A sheet built now would be blank "
                "for the wrong reason. Re-run when the sources respond.")
    if not picks:
        raise SystemExit("No games scheduled in this window; nothing to track.")
    path = build_pdf(today, days, picks, hist)
    print(f"wrote {path}")
    # machine-readable twin: filling the CSV is what score_sheet.py reads back
    import csv as _csv
    cpath = os.path.join(OUT, span_name(today, days) + ".csv")
    with open(cpath, "w", newline="", encoding="utf-8") as f:
        w = _csv.writer(f)
        w.writerow(["date", "league", "matchup", "pick", "model_conf",
                    "chance", "won", "odds", "notes"])
        for p_ in sorted(picks, key=lambda x: -x["conf"]):
            w.writerow([p_["date"], p_["lg"], p_["matchup"], p_["pick"],
                        f"{p_['conf']:.4f}",
                        f"{calibrated(float(p_['conf']), p_['lg'], p_['date'])[0]:.4f}",
                        "", "", ""])
    print(f"wrote {cpath}  (fill the 'won' column with Y/N, then run score_sheet.py)")


if __name__ == "__main__":
    main()
