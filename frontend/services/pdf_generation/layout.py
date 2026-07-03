"""
Infraestrutura Platypus para documentos A4.

Princípios de design (corrigidos):
  - Hierarquia por PESO (negrito vs. normal) e tamanho — NUNCA por cor cinza.
    Todo texto é preto.
  - Cabeçalho: nome em negrito + linhas de contato EMPILHADAS (uma por linha).
    Endereço nunca é fatiado com separadores.
  - Título do documento com respiro generoso acima e abaixo.
  - Campos como lista de definição: rótulo em negrito, valor normal.
  - Linhas sempre SÓLIDAS e pretas.
  - QR em uma caixa deliberada no rodapé (não jogado solto).
"""
from __future__ import annotations

from io import BytesIO
from typing import Any, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, HRFlowable, PageTemplate,
    Paragraph, Spacer, Table, TableStyle,
)

BLACK = colors.HexColor("#000000")
INK   = colors.HexColor("#111111")

A4_W, A4_H = A4
MARGIN     = 18 * mm
CONTENT_W  = A4_W - 2 * MARGIN


# ---------------------------------------------------------------------------
# Estilos — tudo preto, hierarquia por peso/tamanho
# ---------------------------------------------------------------------------
def _styles() -> dict[str, ParagraphStyle]:
    base = ParagraphStyle("base", fontName="Helvetica", fontSize=9.5,
                          leading=13, textColor=INK)
    return {
        "company":  ParagraphStyle("company", parent=base, fontName="Helvetica-Bold",
                                   fontSize=17, leading=20),
        "contact":  ParagraphStyle("contact", parent=base, fontSize=9.5, leading=13.5),
        "doctitle": ParagraphStyle("doctitle", parent=base, fontName="Helvetica-Bold",
                                   fontSize=16, leading=19, alignment=TA_CENTER),
        "docmeta":  ParagraphStyle("docmeta", parent=base, fontSize=10, leading=14,
                                   alignment=TA_CENTER),
        "section":  ParagraphStyle("section", parent=base, fontName="Helvetica-Bold",
                                   fontSize=10.5, leading=14, spaceBefore=2, spaceAfter=6),
        "field":    ParagraphStyle("field", parent=base, fontSize=10, leading=16),
        "body":     ParagraphStyle("body", parent=base, fontSize=9.5, leading=14.5,
                                   alignment=4),  # JUSTIFY
        "th":       ParagraphStyle("th", parent=base, fontName="Helvetica-Bold",
                                   fontSize=8.5, leading=11),
        "th_r":     ParagraphStyle("th_r", parent=base, fontName="Helvetica-Bold",
                                   fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "td":       ParagraphStyle("td", parent=base, fontSize=9.5, leading=12.5),
        "td_r":     ParagraphStyle("td_r", parent=base, fontSize=9.5, leading=12.5,
                                   alignment=TA_RIGHT),
        "total_l":  ParagraphStyle("total_l", parent=base, fontName="Helvetica-Bold",
                                   fontSize=12, leading=15),
        "total_r":  ParagraphStyle("total_r", parent=base, fontName="Helvetica-Bold",
                                   fontSize=12, leading=15, alignment=TA_RIGHT),
        "tot_lbl":  ParagraphStyle("tot_lbl", parent=base, fontSize=10, leading=14),
        "footer":   ParagraphStyle("footer", parent=base, fontSize=7.5, leading=10,
                                   alignment=TA_CENTER),
        "sign":     ParagraphStyle("sign", parent=base, fontSize=9, leading=12.5,
                                   alignment=TA_CENTER),
    }


S = _styles()


# ---------------------------------------------------------------------------
# Cabeçalho
# ---------------------------------------------------------------------------
def header(company: dict[str, Any], title: Optional[str],
           doc_meta: Optional[list[str]] = None) -> list:
    """
    Nome da empresa em negrito, seguido das linhas de contato EMPILHADAS
    (atividade, endereço, RUC, telefone) — cada uma na sua própria linha.
    Régua sólida. Depois o título com respiro generoso.
    """
    flow: list = [Paragraph(str(company.get("name", "")).upper(), S["company"])]

    def line(label: str, value: Any):
        if value and str(value).strip() and str(value) != "-":
            flow.append(Paragraph(f"<b>{label}:</b> {value}", S["contact"])
                        if label else Paragraph(str(value), S["contact"]))

    # Atividade económica é omitida — só faz sentido em facturas legales (nota fiscal).
    line("Dirección", company.get("address"))
    line("RUC", company.get("ruc"))
    line("Teléfono", company.get("phone"))

    flow.append(Spacer(1, 8))
    flow.append(HRFlowable(width="100%", thickness=1.2, color=BLACK,
                           spaceBefore=0, spaceAfter=0))
    if title:
        flow.append(Spacer(1, 22))           # respiro generoso: título bem abaixo do cabeçalho
        flow.append(Paragraph(title.upper(), S["doctitle"]))
        for m in (doc_meta or []):
            flow.append(Paragraph(m, S["docmeta"]))
        flow.append(Spacer(1, 14))           # respiro abaixo do título
    else:
        flow.append(Spacer(1, 10))
    return flow


def rule(thickness: float = 0.8, space_before: float = 6, space_after: float = 8) -> HRFlowable:
    return HRFlowable(width="100%", thickness=thickness, color=BLACK,
                      spaceBefore=space_before, spaceAfter=space_after)


def section(title: str) -> Table:
    """Cabeçalho de seção corporativo: rótulo em negrito + filete fino abaixo."""
    p = Paragraph(title.upper(), S["section"])
    t = Table([[p]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 14),    # respiro acima da seção
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -1), 0.5, BLACK),
    ]))
    return t


# ---------------------------------------------------------------------------
# Campos (lista de definição): rótulo negrito + valor normal
# ---------------------------------------------------------------------------
_FULL_WIDTH_LABELS = {"dirección", "direccion"}

_GAP = "&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;"  # separador inline entre pares (só espaço)


def inline(pairs: list[tuple[str, Any]], per_line: int = 2) -> Paragraph:
    """
    Campos INLINE: vários pares 'rótulo: valor' por linha, fluindo no texto.
    Rótulo em negrito, valor normal, separados apenas por espaço (sem pontos).
    Campos longos (Dirección) ocupam a sua própria linha inteira.
    """
    lines: list[str] = []
    cur: list[str] = []

    def flush():
        if cur:
            lines.append(_GAP.join(cur))
            cur.clear()

    for label, value in pairs:
        v = value if value not in (None, "") else "-"
        seg = f"<b>{label}:</b> {v}"
        if str(label).strip().lower() in _FULL_WIDTH_LABELS:
            flush()
            lines.append(seg)
        else:
            cur.append(seg)
            if len(cur) >= per_line:
                flush()
    flush()
    return Paragraph("<br/>".join(lines), S["field"])


def fields(pairs: list[tuple[str, Any]], ncols: int = 2,
           total_width: Optional[float] = None) -> Table:
    if total_width is None:
        total_width = CONTENT_W

    rows: list[list] = []
    span_rows: list[int] = []
    cur: list = []

    def flush():
        if cur:
            while len(cur) < ncols:
                cur.append("")
            rows.append(list(cur))
            cur.clear()

    def cell(label: str, value: Any) -> Paragraph:
        v = value if value not in (None, "") else "-"
        return Paragraph(f"<b>{label}:</b>&nbsp; {v}", S["field"])

    for label, value in pairs:
        if str(label).strip().lower() in _FULL_WIDTH_LABELS:
            flush()
            rows.append([cell(label, value)] + [""] * (ncols - 1))
            span_rows.append(len(rows) - 1)
        else:
            cur.append(cell(label, value))
            if len(cur) == ncols:
                flush()
    flush()

    col_w = total_width / ncols
    t = Table(rows, colWidths=[col_w] * ncols)
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]
    for r in span_rows:
        style.append(("SPAN", (0, r), (ncols - 1, r)))
    t.setStyle(TableStyle(style))
    return t


# ---------------------------------------------------------------------------
# Tabela de itens
# ---------------------------------------------------------------------------
def items_table(items: list[dict], total_width: Optional[float] = None) -> Table:
    from services.pdf_generation.styles import format_gs
    if total_width is None:
        total_width = CONTENT_W
    head = [Paragraph("DESCRIPCIÓN", S["th"]),
            Paragraph("CANT.", S["th_r"]),
            Paragraph("P. UNIT.", S["th_r"]),
            Paragraph("SUBTOTAL", S["th_r"])]
    data = [head]
    for it in items:
        data.append([
            Paragraph(str(it.get("descripcion", "-")), S["td"]),
            Paragraph(str(it.get("cantidad", 1)), S["td_r"]),
            Paragraph(format_gs(it.get("precio_unitario", 0)), S["td_r"]),
            Paragraph(format_gs(it.get("subtotal", 0)), S["td_r"]),
        ])
    c1 = total_width * 0.52
    c2 = total_width * 0.12
    c3 = total_width * 0.18
    c4 = total_width - c1 - c2 - c3
    t = Table(data, colWidths=[c1, c2, c3, c4], repeatRows=1)
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 1.0, BLACK),    # sob o cabeçalho
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, BLACK),   # entre linhas
        ("LINEBELOW", (0, -1), (-1, -1), 1.0, BLACK),  # fecha a tabela
    ]))
    return t


def totals_block(rows: list[tuple[str, str]], total_row: tuple[str, str],
                 total_width: Optional[float] = None) -> Table:
    if total_width is None:
        total_width = CONTENT_W
    block_w = 80 * mm
    data = []
    for label, value in rows:
        data.append([Paragraph(label, S["tot_lbl"]), Paragraph(value, S["td_r"])])
    data.append([Paragraph(total_row[0], S["total_l"]), Paragraph(total_row[1], S["total_r"])])
    n = len(data)
    inner = Table(data, colWidths=[block_w * 0.52, block_w * 0.48])
    inner.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEABOVE", (0, n - 1), (-1, n - 1), 1.0, BLACK),
        ("TOPPADDING", (0, n - 1), (-1, n - 1), 6),
    ]))
    outer = Table([["", inner]], colWidths=[total_width - block_w, block_w])
    outer.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return outer


# ---------------------------------------------------------------------------
# Assinaturas — espaço de assinatura, linha sólida, rótulo abaixo
# ---------------------------------------------------------------------------
def signatures(items: list[tuple[str, Optional[str]]],
               space: float = 26 * mm, total_width: Optional[float] = None) -> Table:
    """
    items: lista de (rol, nome|None).

    Layout (2 linhas): vão em branco PARA ASSINAR  →  linha sólida  →  rótulo.
    A linha sólida é desenhada como LINEABOVE da segunda linha, ficando entre
    o vão em branco (linha 0) e o rótulo (linha 1).
    """
    if total_width is None:
        total_width = CONTENT_W

    def cell(rol: str, name: Optional[str]) -> Paragraph:
        txt = f"<b>{rol.upper()}</b>"
        if name:
            txt += f"<br/>{name}"
        return Paragraph(txt, S["sign"])

    n = len(items)
    if n == 1:
        rol, name = items[0]
        line_w = min(90 * mm, total_width * 0.6)
        side = (total_width - line_w) / 2
        widths = [side, line_w, side]
        bottom_row = ["", cell(rol, name), ""]
        line_cols = [1]
    else:
        # Colunas de assinatura intercaladas com colunas de gap, para que cada
        # linha de assinatura fique SEPARADA das demais.
        gap = 12 * mm
        sig_w = (total_width - gap * (n - 1)) / n
        widths = []
        bottom_row = []
        line_cols = []
        for i, (r, nm) in enumerate(items):
            if i > 0:
                widths.append(gap)
                bottom_row.append("")          # coluna de gap (sem linha)
            line_cols.append(len(bottom_row))  # índice desta coluna de assinatura
            widths.append(sig_w)
            bottom_row.append(cell(r, nm))

    ncol = len(widths)
    data = [[""] * ncol, bottom_row]
    t = Table(data, colWidths=widths, rowHeights=[space, None])
    style = [
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 1), (-1, 1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]
    for i in line_cols:
        style.append(("LINEABOVE", (i, 1), (i, 1), 0.8, BLACK))
    t.setStyle(TableStyle(style))
    return t


# ---------------------------------------------------------------------------
# QR + footer (partes fixas — onPage)
# ---------------------------------------------------------------------------
def _draw_qr(canvas, url: str, x: float, y: float, size: float):
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode import qr
    from reportlab.graphics.shapes import Drawing
    widget = qr.QrCodeWidget(url)
    widget.barBorder = 0   # sem zona de silêncio interna: topo dos módulos = topo do desenho
    b = widget.getBounds()
    w, h = b[2] - b[0], b[3] - b[1]
    d = Drawing(size, size, transform=[size / w, 0, 0, size / h, 0, 0])
    d.add(widget)
    renderPDF.draw(d, canvas, x, y)


_QR_NOTICE = (
    "Este documento ha sido emitido y validado electrónicamente por el sistema "
    "administrativo de la institución. El código QR adjunto permite verificar la "
    "autenticidad, integridad y vigencia de la información aquí consignada. La "
    "reproducción total o parcial, así como cualquier alteración no autorizada del "
    "presente documento, carecen de validez. Ante cualquier divergencia, prevalecerán "
    "los registros oficiales obrantes en la administración."
)


_QR_NOTICE_STYLE = ParagraphStyle(
    "qr_notice", fontName="Helvetica", fontSize=7.2, leading=10.2,
    textColor=INK, alignment=4)  # JUSTIFY

_QR_GAP = 7 * mm     # espaço horizontal entre texto e QR
_QR_BOTTOM = 14 * mm  # base da faixa (QR e texto) acima da borda da página


def _qr_notice_para() -> Paragraph:
    return Paragraph(f"<b>Verificación de autenticidad.</b> {_QR_NOTICE}", _QR_NOTICE_STYLE)


def _qr_geometry() -> tuple[float, float]:
    """
    QR quadrado com altura = altura do bloco de texto disponível.
    Itera até convergir (qr_size depende da largura do texto, que depende de qr_size).
    Retorna (qr_size, text_w).
    """
    qr_size = 16 * mm
    for _ in range(6):
        text_w = CONTENT_W - qr_size - _QR_GAP
        _, h = _qr_notice_para().wrap(text_w, 10_000)
        qr_size = h
    return qr_size, CONTENT_W - qr_size - _QR_GAP


def _make_on_page(footer_text: str, qr_url: Optional[str]):
    qr_size, text_w = _qr_geometry() if qr_url else (0.0, 0.0)

    def on_page(canvas, doc):
        canvas.saveState()
        left = doc.leftMargin
        right = left + doc.width

        if qr_url:
            band_top = _QR_BOTTOM + qr_size   # topo comum do QR e da 1ª linha do texto

            canvas.setStrokeColor(BLACK)
            canvas.setLineWidth(0.6)
            canvas.line(left, band_top + 6 * mm, right, band_top + 6 * mm)

            # QR à direita; texto à esquerda. Mesma altura, topo e base alinhados.
            _draw_qr(canvas, qr_url, right - qr_size, _QR_BOTTOM, qr_size)
            para = _qr_notice_para()
            para.wrap(text_w, qr_size)
            para.drawOn(canvas, left, _QR_BOTTOM)

        if footer_text:
            fy = 13 * mm
            canvas.setStrokeColor(BLACK)
            canvas.setLineWidth(0.6)
            canvas.line(left, fy + 4 * mm, right, fy + 4 * mm)
            canvas.setFillColor(INK)
            canvas.setFont("Helvetica", 7.5)
            canvas.drawCentredString((left + right) / 2, fy, footer_text)
        canvas.restoreState()
    return on_page


def build_a4(flowables: list, *, footer_text: str = "",
             qr_url: Optional[str] = None, qr_caption: str = "") -> bytes:
    buf = BytesIO()
    if qr_url:
        qr_size, _ = _qr_geometry()
        # Limite do rodapé acompanha a altura real da faixa (QR = texto) + folga.
        bottom = _QR_BOTTOM + qr_size + 12 * mm
    else:
        bottom = 22 * mm
    doc = BaseDocTemplate(
        buf, pagesize=A4,
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=16 * mm, bottomMargin=bottom,
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height,
                  id="main", leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id="main", frames=[frame],
                                       onPage=_make_on_page(footer_text, qr_url))])
    doc.build(flowables)
    pdf = buf.getvalue()
    buf.close()
    return pdf
