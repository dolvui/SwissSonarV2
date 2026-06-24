"""
ui/pdf_export.py — Generate a PDF report using reportlab.

Contents:
  Page 1 — Cover / summary stats
  Page 2 — Top 10 tokens by score (bar chart)
  Page 3+ — Full token table (all tokens, paginated)
"""
import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable,
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics import renderPDF

# ── Colour palette ─────────────────────────────────────────────────────────────
C_DARK   = colors.HexColor("#0f1117")
C_ACCENT = colors.HexColor("#00d4ff")
C_GREEN  = colors.HexColor("#00c853")
C_RED    = colors.HexColor("#ff1744")
C_GREY   = colors.HexColor("#aaaaaa")
C_WHITE  = colors.white
C_LIGHT  = colors.HexColor("#1e2130")


# ── Styles ─────────────────────────────────────────────────────────────────────

def _styles():
    base = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CTitle", parent=base["Title"],
        fontSize=26, textColor=C_ACCENT, spaceAfter=6,
    )
    h1_style = ParagraphStyle(
        "CH1", parent=base["Heading1"],
        fontSize=16, textColor=C_ACCENT, spaceAfter=4,
    )
    h2_style = ParagraphStyle(
        "CH2", parent=base["Heading2"],
        fontSize=12, textColor=C_WHITE, spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "CBody", parent=base["Normal"],
        fontSize=9, textColor=C_GREY, spaceAfter=2,
    )
    return title_style, h1_style, h2_style, body_style


# ── Bar chart flowable ─────────────────────────────────────────────────────────

def _top10_chart(tokens: list) -> Drawing:
    top = tokens[:10]
    names  = [t.name[:12] for t in top]
    scores = [t.final_score for t in top]

    d = Drawing(500, 220)

    # Background rect
    bg = Rect(0, 0, 500, 220, fillColor=C_LIGHT, strokeColor=None)
    d.add(bg)

    bc = VerticalBarChart()
    bc.x = 40
    bc.y = 30
    bc.width  = 440
    bc.height = 160
    bc.data   = [scores]
    bc.categoryAxis.categoryNames = names
    bc.categoryAxis.labels.angle  = 30
    bc.categoryAxis.labels.dy     = -10
    bc.categoryAxis.labels.fontSize = 7
    bc.categoryAxis.labels.fillColor = C_GREY
    bc.valueAxis.valueMin = 0
    bc.valueAxis.valueMax = 100
    bc.valueAxis.labels.fontSize = 7
    bc.valueAxis.labels.fillColor = C_GREY
    bc.bars[0].fillColor = C_ACCENT
    bc.bars[0].strokeColor = None
    d.add(bc)
    return d


# ── Token table ────────────────────────────────────────────────────────────────

def _token_table(tokens: list, title_style, h2_style) -> list:
    """Return a list of flowables: heading + paginated table."""
    story = []
    story.append(Paragraph("All Tokens — Full Ranking", h2_style))
    story.append(Spacer(1, 0.3 * cm))

    headers = ["#", "Name", "Ticker", "Price (USD)", "24h %", "Market Cap",
               "Vol 24h", "Trend", "Reddit", "YouTube", "Score"]

    col_widths = [0.7*cm, 3.2*cm, 1.5*cm, 2.4*cm, 1.5*cm,
                  2.6*cm, 2.4*cm, 1.5*cm, 1.5*cm, 1.8*cm, 1.8*cm]

    def fmt(v, decimals=2, suffix=""):
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:,.{decimals}f}{suffix}"
        return str(v)

    def fmt_large(v):
        if v is None:
            return "—"
        if v >= 1e9:
            return f"${v/1e9:.1f}B"
        if v >= 1e6:
            return f"${v/1e6:.1f}M"
        return f"${v:,.0f}"

    rows = [headers]
    for i, t in enumerate(tokens, 1):
        change = t.change_24h or 0.0
        rows.append([
            str(i),
            t.name[:18],
            t.ticker,
            fmt(t.current_price, decimals=4),
            fmt(change, decimals=2, suffix="%"),
            fmt_large(t.market_cap),
            fmt_large(t.volume_24h),
            str(t.trend_score) if t.trend_score >= 0 else "—",
            str(t.reddit_mentions) if t.reddit_mentions >= 0 else "—",
            str(t.youtube_mentions) if t.youtube_mentions >= 0 else "—",
            fmt(t.final_score, decimals=1),
        ])

    tbl = Table(rows, colWidths=col_widths, repeatRows=1)

    style = TableStyle([
        # Header
        ("BACKGROUND",   (0, 0), (-1, 0), C_ACCENT),
        ("TEXTCOLOR",    (0, 0), (-1, 0), C_DARK),
        ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",     (0, 0), (-1, 0), 7),
        ("ALIGN",        (0, 0), (-1, 0), "CENTER"),
        # Body
        ("FONTSIZE",     (0, 1), (-1, -1), 6.5),
        ("TEXTCOLOR",    (0, 1), (-1, -1), C_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_DARK, C_LIGHT]),
        ("ALIGN",        (2, 1), (-1, -1), "RIGHT"),
        ("ALIGN",        (0, 1), (1, -1), "LEFT"),
        # Grid
        ("LINEBELOW",    (0, 0), (-1, 0), 0.5, C_ACCENT),
        ("LINEBELOW",    (0, 1), (-1, -1), 0.3, colors.HexColor("#2a2d3e")),
        ("TOPPADDING",   (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
        ("LEFTPADDING",  (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ])

    # Colour-code 24h% column
    for i, t in enumerate(tokens, 1):
        change = t.change_24h or 0.0
        col = C_GREEN if change >= 0 else C_RED
        style.add("TEXTCOLOR", (4, i), (4, i), col)

    tbl.setStyle(style)
    story.append(tbl)
    return story


# ── Public API ─────────────────────────────────────────────────────────────────

def build_pdf(tokens: list, last_run: str | None = None) -> bytes:
    """
    Build a complete PDF report and return it as bytes.

    tokens: list of Token objects, pre-sorted by final_score.
    last_run: ISO timestamp string of last data fetch.
    """
    buf = io.BytesIO()

    doc = SimpleDocTemplate(
        buf,
        pagesize=landscape(A4),
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
        title="Crypto Dashboard Report",
        author="Crypto Dashboard",
    )

    title_s, h1_s, h2_s, body_s = _styles()
    story = []

    # ── Cover ──────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("📊 Crypto Dashboard Report", title_s))
    story.append(HRFlowable(width="100%", color=C_ACCENT, thickness=1))
    story.append(Spacer(1, 0.4 * cm))

    ts = last_run or datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    story.append(Paragraph(f"Generated: {ts}", body_s))
    story.append(Paragraph(f"Total tokens tracked: {len(tokens)}", body_s))

    # Quick stats
    if tokens:
        top = tokens[0]
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Key Highlights", h2_s))
        story.append(Paragraph(f"Top ranked token: <b>{top.name} ({top.ticker})</b> — score {top.final_score:.1f}/100", body_s))

        gainers = sorted([t for t in tokens if (t.change_24h or 0) > 0],
                         key=lambda t: t.change_24h or 0, reverse=True)
        losers  = sorted([t for t in tokens if (t.change_24h or 0) < 0],
                         key=lambda t: t.change_24h or 0)
        if gainers:
            g = gainers[0]
            story.append(Paragraph(f"Best 24h performer: {g.name} (+{g.change_24h:.2f}%)", body_s))
        if losers:
            l = losers[0]
            story.append(Paragraph(f"Worst 24h performer: {l.name} ({l.change_24h:.2f}%)", body_s))

        new_tokens = [t for t in tokens if t.is_new]
        if new_tokens:
            names = ", ".join(t.name for t in new_tokens[:5])
            story.append(Paragraph(f"Newly listed tokens: {names}", body_s))

    story.append(PageBreak())

    # ── Top 10 chart ───────────────────────────────────────────────────────────
    story.append(Paragraph("Top 10 Tokens by Score", h1_s))
    story.append(HRFlowable(width="100%", color=C_ACCENT, thickness=0.5))
    story.append(Spacer(1, 0.3 * cm))
    story.append(_top10_chart(tokens))
    story.append(Spacer(1, 0.5 * cm))

    # Mini table for top 10
    top10_headers = ["#", "Name", "Ticker", "Score", "24h %", "Trend Score", "New?"]
    top10_rows = [top10_headers]
    for i, t in enumerate(tokens[:10], 1):
        top10_rows.append([
            str(i), t.name[:20], t.ticker,
            f"{t.final_score:.1f}",
            f"{t.change_24h:+.2f}%" if t.change_24h is not None else "—",
            str(t.trend_score) if t.trend_score >= 0 else "—",
            "🆕" if t.is_new else "",
        ])

    t10 = Table(top10_rows, colWidths=[1*cm, 4*cm, 2*cm, 2*cm, 2*cm, 2.5*cm, 1.5*cm])
    t10.setStyle(TableStyle([
        ("BACKGROUND",  (0, 0), (-1, 0), C_ACCENT),
        ("TEXTCOLOR",   (0, 0), (-1, 0), C_DARK),
        ("FONTNAME",    (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8),
        ("TEXTCOLOR",   (0, 1), (-1, -1), C_GREY),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_DARK, C_LIGHT]),
        ("ALIGN",       (3, 1), (-1, -1), "CENTER"),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0,0), (-1, -1), 4),
    ]))
    story.append(t10)
    story.append(PageBreak())

    # ── Full token table ───────────────────────────────────────────────────────
    story.extend(_token_table(tokens, title_s, h2_s))

    doc.build(story)
    return buf.getvalue()
