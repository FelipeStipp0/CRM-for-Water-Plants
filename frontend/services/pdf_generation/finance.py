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
from services.pdf_generation.company import extract_company
from services.pdf_generation.styles import format_date, format_gs


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
                Paragraph(format_date(m.get("fecha"), include_time=True), L.S["td"]),
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
            ("Fecha",       format_date(data.get("fecha_pago") or datetime.utcnow(), include_time=True)),
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
            ("Fecha",     format_date(data.get("fecha_pago") or datetime.utcnow(), include_time=True)),
        ], per_line=2))

        story.append(L.section("Detalle"))
        story.append(L.items_table(items))
        story.append(Spacer(1, 12))
        story.append(L.totals_block([], ("TOTAL", format_gs(data.get("valor_total", 0)))))

        story.append(Spacer(1, 6))
        story.append(L.signatures([("Firma responsable", None)], space=28 * mm))

        return L.build_a4(story)
