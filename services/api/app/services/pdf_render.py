"""Pure-Python PDF rendering (fpdf2) for serverless hosts without Pango/Cairo.

WeasyPrint needs OS libraries (libpango, cairo) that are absent on Vercel
Functions, so PDFs are drawn directly with fpdf2 using the bundled Korean font.
Layouts mirror the former HTML/CSS documents (A4 landscape, same colors).
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from fpdf import FPDF

FONT_PATH = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "NanumGothic-Regular.ttf"
FONT = "NanumGothic"

INK = (0x17, 0x35, 0x1F)
MUTED = (0x64, 0x70, 0x66)
LINE = (0xD9, 0xDD, 0xCE)
CARD = (0xF7, 0xF2, 0xE5)
HEADER = (0xDF, 0xEE, 0xDB)
LEDGER_INK = (0x14, 0x35, 0x1F)
LEDGER_LINE = (0xD9, 0xE8, 0xDC)


def _document(margin_mm: float) -> FPDF:
    pdf = FPDF(orientation="L", unit="mm", format="A4")
    pdf.set_margins(margin_mm, margin_mm, margin_mm)
    pdf.set_auto_page_break(True, margin=margin_mm)
    pdf.add_font(FONT, "", str(FONT_PATH))
    # Only a regular weight is bundled; map bold onto it so styled text never fails.
    pdf.add_font(FONT, "B", str(FONT_PATH))
    pdf.add_page()
    return pdf


def _px(value: float) -> float:
    """CSS px (96dpi) to pt, matching the former WeasyPrint sizes."""
    return value * 0.75


def _output(pdf: FPDF) -> bytes:
    return bytes(pdf.output())


def render_settlement_pdf(
    *,
    period: str,
    supplier: tuple[str, str],
    recipient: tuple[str, str],
    amounts: tuple[int, int, int],
    rows: Iterable[list[str]],
) -> bytes:
    """매출 정산서: title, 3x2 summary cards, 11-column transaction table."""
    pdf = _document(16 + 6.35)  # @page 16mm + body margin 24px
    width = pdf.epw
    pdf.set_text_color(*INK)
    pdf.set_font(FONT, "B", _px(24))
    pdf.cell(0, 11, "매출 정산서", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)

    supply, vat, total = amounts
    cards = [
        ("정산 기간", period, ""),
        ("공급자", supplier[0], supplier[1]),
        ("공급받는자", recipient[0], recipient[1]),
        ("공급가액", f"{supply:,}원", ""),
        ("부가세", f"{vat:,}원", ""),
        ("합계", f"{total:,}원", ""),
    ]
    gap, card_h = 2.6, 17.0
    card_w = (width - gap * 2) / 3
    top = pdf.get_y()
    for index, (label, value, sub) in enumerate(cards):
        x = pdf.l_margin + (index % 3) * (card_w + gap)
        y = top + (index // 3) * (card_h + gap)
        pdf.set_fill_color(*CARD)
        pdf.set_draw_color(*LINE)
        pdf.rect(x, y, card_w, card_h, style="FD", round_corners=True, corner_radius=2)
        pdf.set_xy(x + 2.6, y + 2.2)
        pdf.set_font(FONT, "", _px(10))
        pdf.set_text_color(*MUTED)
        pdf.cell(card_w - 5.2, 4, label)
        pdf.set_xy(x + 2.6, y + 6.8)
        pdf.set_font(FONT, "B", _px(12))
        pdf.set_text_color(*INK)
        pdf.cell(card_w - 5.2, 5, value)
        if sub:
            pdf.set_xy(x + 2.6, y + 11.4)
            pdf.set_font(FONT, "", _px(12))
            pdf.cell(card_w - 5.2, 5, sub)
    pdf.set_y(top + card_h * 2 + gap + 8.5)

    headers = ["거래 날짜", "거래 시간", "이름", "부서", "사번", "구분", "내역", "공급가액", "부가세", "합계", "거래번호"]
    money = 24.0  # fixed right-aligned money columns
    widths = [25, 21, 30, 18, 14, 12, 0, money, money, money, 30]
    widths[6] = width - sum(widths)
    _table(pdf, headers, list(rows), widths, right_aligned={7, 8, 9},
           empty="해당 정산 기간의 사용 내역이 없습니다.")
    return _output(pdf)


def _table(pdf: FPDF, headers: list[str], rows: list[list[str]], widths: list[float],
           *, right_aligned: set[int], empty: str) -> None:
    line_h = 4.4
    pdf.set_font(FONT, "", _px(12))
    pdf.set_draw_color(*LINE)

    def header() -> None:
        pdf.set_fill_color(*HEADER)
        pdf.set_text_color(*INK)
        for index, (label, w) in enumerate(zip(headers, widths)):
            x, y = pdf.get_x(), pdf.get_y()
            pdf.rect(x, y, w, 8, style="F")
            pdf.line(x, y + 8, x + w, y + 8)
            pdf.set_xy(x + 1.85, y)
            pdf.cell(w - 3.7, 8, label, align="R" if index in right_aligned else "L")
            pdf.set_xy(x + w, y)
        pdf.ln()

    header()
    if not rows:
        pdf.cell(sum(widths), 13, empty, border="B", align="C", new_x="LMARGIN", new_y="NEXT")
        return
    for row in rows:
        lines = [pdf.multi_cell(w - 3.7, line_h, str(v), dry_run=True, output="LINES") for v, w in zip(row, widths)]
        height = max(len(item) for item in lines) * line_h + 3.7
        if pdf.will_page_break(height):
            pdf.add_page()
            header()
        y = pdf.get_y()
        x = pdf.l_margin
        for index, (value, w) in enumerate(zip(row, widths)):
            pdf.set_xy(x + 1.85, y + 1.85)
            pdf.multi_cell(w - 3.7, line_h, str(value), align="R" if index in right_aligned else "L")
            x += w
        pdf.set_xy(pdf.l_margin, y + height)
        pdf.line(pdf.l_margin, y + height, pdf.l_margin + sum(widths), y + height)


def render_line_document(lines: list[str]) -> bytes:
    """Vendor 청구서: first four lines emphasized, then ruled rows (former div list)."""
    pdf = _document(18)
    pdf.set_text_color(*LEDGER_INK)
    pdf.set_draw_color(*LEDGER_LINE)
    for index, line in enumerate(lines):
        emphasized = index < 4
        pdf.set_font(FONT, "B" if emphasized else "", _px(13 if emphasized else 10))
        pdf.multi_cell(0, 5.2 if emphasized else 4.2, line, new_x="LMARGIN", new_y="NEXT")
        if not emphasized:
            y = pdf.get_y() + 0.8
            pdf.line(pdf.l_margin, y, pdf.l_margin + pdf.epw, y)
            pdf.set_y(y + 0.8)
        else:
            pdf.ln(1.6)
    return _output(pdf)


def settlement_rows(transactions: list[dict[str, Any]], *, date_time, kind_label, text, amount) -> list[list[str]]:
    rows = []
    for row in transactions:
        transaction_date, transaction_time = date_time(row.get("created_at"))
        rows.append([
            text(transaction_date), text(transaction_time), text(row.get("employee_name")),
            text(row.get("department")), text(row.get("employee_no")), text(kind_label(row)),
            text(row.get("item")), f"{amount(row.get('supply_amount')):,}", f"{amount(row.get('vat_amount')):,}",
            f"{amount(row.get('total_amount')):,}", text(row.get("tx_code")),
        ])
    return rows
