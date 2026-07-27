"""
Financial PDF generators (Platypus — sem cores, com título).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf_generation import layout as L
from services.pdf_generation.base import PDFGenerator
from services.pdf_generation.company import draw_company_header_p80, extract_company, normalize_company
from services.pdf_generation.styles import (
    PdfColors, PdfStyles, draw_h_rule, format_date, format_gs, format_local_datetime,
)

G = PdfStyles.GAP - 1.5 * mm   # 4.5mm — mesmo passo compacto do recibo P80


def _f(value: Any) -> float:
    """Valor monetário como float; 0 quando ausente ou ilegível."""
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _wrap(c, text: str, font: tuple, max_width: float) -> list[str]:
    """Quebra texto livre na largura útil do papel (sem cortar palavra)."""
    lines, cur = [], []
    for word in str(text).split():
        if c.stringWidth(" ".join(cur + [word]), font[0], font[1]) <= max_width or not cur:
            cur.append(word)
        else:
            lines.append(" ".join(cur))
            cur = [word]
    if cur:
        lines.append(" ".join(cur))
    return lines


class FinanceReportGenerator(PDFGenerator):
    """A4 informe financiero (resumen + tabla de movimientos)."""

    def __init__(self):
        super().__init__(page_size=A4)

    def generate(self, data: dict[str, Any]) -> bytes:
        company   = extract_company(data)
        summary   = data.get("summary", {})
        movements = data.get("movements", []) or []
        period    = data.get("period", {})
        period_label = data.get("period_label") or \
            f"{period.get('start', '-')} a {period.get('end', '-')}"

        story = L.header(company, "Informe Financiero",
                         doc_meta=[f"Período: {period_label}"])

        story.append(L.section("Resumen"))
        story.append(L.inline([
            ("Entradas", format_gs(summary.get("total_entradas", 0))),
            ("Salidas",  format_gs(summary.get("total_saidas", 0))),
            ("Saldo del período", format_gs(summary.get("saldo_periodo", 0))),
        ], per_line=3))

        story.append(L.section("Movimientos"))
        story.append(self._movements_table(movements))

        return L.build_a4(story)

    def _movements_table(self, movements: list[dict]) -> Table:
        tw = L.A4_W - 2 * L.MARGIN
        th_r = ParagraphStyle("thr", parent=L.S["th"], alignment=TA_RIGHT)
        head = [Paragraph("FECHA", L.S["th"]), Paragraph("TIPO", L.S["th"]),
                Paragraph("CATEGORÍA", L.S["th"]), Paragraph("DESCRIPCIÓN", L.S["th"]),
                Paragraph("VALOR", th_r)]
        data = [head]
        for m in movements:
            data.append([
                Paragraph(format_local_datetime(m.get("fecha")), L.S["td"]),
                Paragraph(str(m.get("tipo", "-")), L.S["td"]),
                Paragraph(str(m.get("categoria", "-")).replace("_", " "), L.S["td"]),
                Paragraph(str(m.get("descripcion", "-")), L.S["td"]),
                Paragraph(format_gs(m.get("valor", 0)), L.S["td_r"]),
            ])
        widths = [tw * 0.20, tw * 0.12, tw * 0.22, tw * 0.28, tw * 0.18]
        t = Table(data, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LINEBELOW", (0, 0), (-1, 0), 1.0, L.BLACK),
            ("LINEBELOW", (0, 1), (-1, -2), 0.4, L.BLACK),
            ("LINEBELOW", (0, -1), (-1, -1), 1.0, L.BLACK),
        ]))
        return t


class EmployeePaymentGenerator(PDFGenerator):
    """A4 comprobante de pago de personal."""

    def __init__(self):
        super().__init__(page_size=A4)

    def generate(self, data: dict[str, Any]) -> bytes:
        company        = extract_company(data)
        employee_name  = data.get("employee_name", "-")
        treasurer_name = data.get("tesoureiro_nome") or data.get("treasurer_name") or "-"
        president_name = data.get("presidente_nome") or data.get("president_name") or "-"
        periodo = f"{int(data.get('mes_referencia', 0) or 0):02d}/{data.get('ano_referencia', '-')}"

        story = L.header(company, "Comprobante de Pago — Personal")
        story.append(L.inline([
            ("Funcionario", str(employee_name)),
            ("Período",     periodo),
            ("Tipo",        data.get("tipo", "-")),
            ("Fecha",       format_local_datetime(data.get("fecha_pago") or datetime.utcnow())),
        ], per_line=2))

        story.append(L.section("Valores"))
        story.append(L.totals_block(
            [("Valor base", format_gs(data.get("valor_base", 0))),
             ("Descuentos", format_gs(data.get("descontos", 0)))],
            ("VALOR LÍQUIDO", format_gs(data.get("valor_liquido", 0))),
        ))
        story.append(Spacer(1, 6))
        story.append(L.signatures([
            ("Colaborador", str(employee_name)),
            ("Tesorero",    str(treasurer_name)),
            ("Presidente",  str(president_name)),
        ], space=30 * mm))

        return L.build_a4(story)


class CierreCajaP80Generator(PDFGenerator):
    """Comprobante de cierre de turno (80mm) — o que o cajero assina e entrega."""

    def __init__(self):
        super().__init__(page_size=(80 * mm, 210 * mm))

    _PROBE_H = 300 * mm   # papel folgado da 1ª passada (só para medir)

    def generate(self, sesion: dict[str, Any]) -> bytes:
        """
        Duas passadas: a 1ª desenha num papel folgado só para medir onde o
        conteúdo termina; a 2ª desenha de novo na altura exata. As linhas são
        condicionais (métodos não usados, estornos, observações de tamanho
        livre), então estimar a altura por contagem de linhas erra e corta o
        rodapé — medir não erra.
        """
        M = PdfStyles.P80_MARGIN
        probe = self.create_canvas(page_size=(80 * mm, self._PROBE_H))
        y_end = self._draw(probe, 80 * mm, self._PROBE_H - M, sesion)
        altura = (self._PROBE_H - y_end) + M

        c = self.create_canvas(page_size=(80 * mm, altura))
        self._draw(c, 80 * mm, altura - M, sesion)
        return self.finalize(c)

    def _draw(self, c, width: float, y: float, sesion: dict[str, Any]) -> float:
        """Desenha o comprobante a partir de `y`; devolve o y final (rodapé)."""
        company = normalize_company(extract_company(sesion))
        obs = str(sesion.get("observaciones") or "").strip()
        M  = PdfStyles.P80_MARGIN
        cx = width / 2
        iw = width - 2 * M

        y = draw_company_header_p80(c, width=width, margin=M, y=y,
                                    title="Cierre de Caja", company=company,
                                    meta_color=PdfColors.DARK)

        def row(label: str, value: str, bold: bool = False):
            nonlocal y
            c.setFont(*(PdfStyles.P80_FONT_TOTAL if bold else PdfStyles.P80_FONT_BODY))
            c.setFillColor(PdfColors.DARK)   # tudo preto: térmico gasto não perdoa cinza
            c.drawString(M, y, label)
            c.drawRightString(width - M, y, value)
            y -= G

        def rule(thickness: float = 0.4):
            nonlocal y
            draw_h_rule(c, M, y, iw, thickness=thickness)
            y -= G

        # --- Identificação do turno ---
        c.setFont(*PdfStyles.P80_FONT_DOCTYPE)
        c.setFillColor(PdfColors.DARK)
        # numero_fmt já vem como "Caja 07" — não prefixar de novo.
        c.drawCentredString(cx, y, str(sesion.get("numero_fmt") or "-").upper())
        y -= G

        row("Operador:", str(sesion.get("operador", "-"))[:24])
        row("Apertura:", format_local_datetime(sesion.get("fecha_apertura")))
        row("Cierre:", format_local_datetime(sesion.get("fecha_cierre") or datetime.utcnow()))
        rule()

        # --- Movimento do turno ---
        row("Monto inicial:", format_gs(sesion.get("monto_inicial", 0)))
        row(f"Cobros en efectivo ({int(sesion.get('cantidad_pagos', 0) or 0)}):",
            format_gs(sesion.get("ingresos_efectivo", 0)))
        if _f(sesion.get("ingresos_transferencia")):
            row("Transferencias:", format_gs(sesion.get("ingresos_transferencia")))
        if _f(sesion.get("ingresos_cheque")):
            row("Cheques:", format_gs(sesion.get("ingresos_cheque")))
        if _f(sesion.get("estornos_efectivo_previos")):
            row("Anulaciones:", f"- {format_gs(sesion.get('estornos_efectivo_previos'))}")
        rule()

        # --- Conferência da gaveta ---
        row("Efectivo esperado:", format_gs(sesion.get("efectivo_esperado", 0)))
        row("Efectivo contado:", format_gs(sesion.get("efectivo_fisico", 0)))
        rule()

        dif = _f(sesion.get("diferencia"))
        if dif == 0:
            dif_label, dif_valor = "CUADRA EXACTO", format_gs(0)
        elif dif > 0:
            dif_label, dif_valor = "SOBRA", format_gs(dif)
        else:
            dif_label, dif_valor = "FALTA", format_gs(abs(dif))
        row(dif_label + ":", dif_valor, bold=True)
        rule(thickness=0.8)

        if obs:
            c.setFont(*PdfStyles.P80_FONT_SMALL)
            c.setFillColor(PdfColors.DARK)
            c.drawString(M, y, "Observaciones:")
            y -= G * 0.75
            c.setFillColor(PdfColors.DARK)
            for line in _wrap(c, obs, PdfStyles.P80_FONT_SMALL, iw)[:4]:
                c.drawString(M, y, line)
                y -= G * 0.7
            y -= G * 0.4

        # --- Firma ---
        firma_h = 18 * mm
        firma_y = y - firma_h
        c.setStrokeColor(PdfColors.DARK)
        c.setLineWidth(0.6)
        c.rect(M, firma_y, iw, firma_h, stroke=1, fill=0)
        c.setLineWidth(1)
        c.setFont(*PdfStyles.P80_FONT_SMALL)
        c.setFillColor(PdfColors.DARK)
        c.drawCentredString(cx, firma_y + firma_h - 5 * mm, "Firma del cajero")

        y = firma_y - G * 1.4
        c.setFont("Helvetica", 6)
        c.setFillColor(PdfColors.DARK)
        c.drawCentredString(cx, y, "COMPROBANTE INTERNO - NO VÁLIDO COMO FACTURA LEGAL")

        return y - 2 * mm   # folga abaixo da última linha


class ExpenseReceiptGenerator(PDFGenerator):
    """A4 comprobante de gasto."""

    def __init__(self):
        super().__init__(page_size=A4)

    def generate(self, data: dict[str, Any]) -> bytes:
        company = extract_company(data)
        items   = data.get("items", []) or []

        story = L.header(company, "Comprobante de Gasto")
        story.append(L.section("Datos del proveedor"))
        story.append(L.inline([
            ("Proveedor", data.get("proveedor_nombre", "-")),
            ("RUC",       data.get("proveedor_ruc", "-")),
            ("Factura",   data.get("numero_factura", "-")),
            ("Categoría", data.get("categoria", "-")),
            ("Fecha",     format_local_datetime(data.get("fecha_pago") or datetime.utcnow())),
        ], per_line=2))

        story.append(L.section("Detalle"))
        story.append(L.items_table(items))
        story.append(Spacer(1, 12))
        story.append(L.totals_block([], ("TOTAL", format_gs(data.get("valor_total", 0)))))

        story.append(Spacer(1, 6))
        story.append(L.signatures([("Firma responsable", None)], space=28 * mm))

        return L.build_a4(story)
