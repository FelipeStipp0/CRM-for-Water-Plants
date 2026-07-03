"""
Shared styles/helpers for PDF generation.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.units import mm


class PdfColors:
    BLACK      = colors.HexColor("#000000")
    WHITE      = colors.HexColor("#ffffff")
    DARK       = colors.HexColor("#1a1a1a")   # texto principal
    GRAY       = colors.HexColor("#444444")   # labels / secundário
    LIGHT_GRAY = colors.HexColor("#888888")   # rodapé / muted
    RULE       = colors.HexColor("#cccccc")   # linhas de separação
    ROW_ALT    = colors.HexColor("#f5f5f5")   # zebra em tabelas


class PdfStyles:
    A4_MARGIN  = 18 * mm   # margem generosa para o A4 respirar
    P80_MARGIN =  5 * mm

    # Espaçamento vertical uniforme — use sempre GAP ou frações/múltiplos
    GAP        =  6 * mm   # unidade base de espaçamento
    ROW_PAD    =  2 * mm   # padding vertical interno em cada linha de tabela

    FONT_COMPANY  = ("Helvetica-Bold", 15)   # nome da empresa no header (cabe em 1 linha)
    FONT_DOCTYPE  = ("Helvetica-Bold", 12.5) # tipo de documento — centrado no corpo
    FONT_META     = ("Helvetica", 9)         # ruc/tel/endereço no header
    FONT_SECTION  = ("Helvetica-Bold", 9)    # label de seção (CLIENTE, etc.)
    FONT_LABEL    = ("Helvetica-Bold", 10)   # valor de par chave:valor
    FONT_BODY     = ("Helvetica", 10)        # texto corrido e label de par
    FONT_SMALL    = ("Helvetica", 8.5)       # rodapé / notas
    FONT_TOTAL    = ("Helvetica-Bold", 13)   # valor do total
    FONT_TH       = ("Helvetica-Bold", 8.5)  # cabeçalho de tabela

    # P80 — fontes compactas para 80mm
    P80_FONT_NAME    = ("Helvetica-Bold", 10.5)
    P80_FONT_DOCTYPE = ("Helvetica-Bold", 9)
    P80_FONT_BODY    = ("Helvetica", 8.5)
    P80_FONT_TOTAL   = ("Helvetica-Bold", 10.5)
    P80_FONT_SMALL   = ("Helvetica", 7.5)


def _to_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def format_gs(value: Any) -> str:
    amount = _to_decimal(value)
    return f"Gs. {amount:,.0f}".replace(",", ".")


def short_period(mes: Any, ano: Any) -> str:
    try:
        return f"{int(mes):02d}/{int(ano)}"
    except Exception:
        return "-/-"


def format_date(value: Any, include_time: bool = False) -> str:
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            try:
                dt = datetime.strptime(value, "%Y-%m-%d")
            except Exception:
                dt = None
    if dt is None:
        return "-"
    return dt.strftime("%d/%m/%Y %H:%M" if include_time else "%d/%m/%Y")


def draw_h_rule(c, x: float, y: float, w: float, color=None, thickness: float = 0.4):
    c.setStrokeColor(color or PdfColors.RULE)
    c.setLineWidth(thickness)
    c.line(x, y, x + w, y)
    c.setLineWidth(1)


def fill_row(c, x: float, y: float, w: float, h: float):
    """Fills a row background for zebra tables."""
    c.setFillColor(PdfColors.ROW_ALT)
    c.rect(x, y, w, h, stroke=0, fill=1)
    c.setFillColor(PdfColors.DARK)
