"""
Invoice PDF generators.

  - InvoiceA4Generator  → Platypus (documento A4 bem estruturado, com título).
  - InvoiceP80Generator → canvas (ticket térmico 80mm, altura dinâmica).
  - BulkInvoiceA4Generator → canvas (3 faturas por página em cards).
"""
from __future__ import annotations

from typing import Any

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import Spacer

from services.pdf_generation import layout as L
from services.pdf_generation.base import PDFGenerator
from services.pdf_generation.company import (
    draw_company_header_p80, extract_company, normalize_company,
)
from services.pdf_generation.styles import (
    PdfColors, PdfStyles, draw_h_rule, format_date, format_gs,
)

GAP = PdfStyles.GAP


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_period(invoice: dict[str, Any]) -> str:
    try:
        return f"{int(invoice.get('mes_referencia', 0) or 0):02d}/{invoice.get('ano_referencia', '-')}"
    except Exception:
        return "-/-"


def _safe_number(invoice: dict[str, Any]) -> str:
    n = invoice.get("numero_factura") or invoice.get("numero_fatura") or invoice.get("nro_factura")
    return str(n) if n not in (None, "") else "-"


def _client(payload: dict[str, Any]) -> dict[str, Any]:
    c = payload.get("client")
    return c if isinstance(c, dict) else {}


def _default_items(invoice: dict[str, Any]) -> list[dict]:
    return [{"descripcion": "Servicio de agua", "cantidad": 1,
             "precio_unitario": invoice.get("valor_total", 0),
             "subtotal": invoice.get("valor_total", 0)}]


# ---------------------------------------------------------------------------
# InvoiceA4Generator (Platypus)
# ---------------------------------------------------------------------------

class InvoiceA4Generator(PDFGenerator):
    def __init__(self):
        super().__init__(page_size=A4)

    def generate(self, invoice_payload: dict[str, Any]) -> bytes:
        invoice = invoice_payload.get("invoice", invoice_payload)
        client  = _client(invoice_payload)
        company = extract_company(invoice_payload)
        items   = invoice.get("items") or _default_items(invoice)

        valor_total = invoice.get("valor_total", 0)
        saldo       = invoice.get("saldo_pendiente_anterior", 0)
        total       = invoice.get("total_a_pagar") or invoice.get("saldo_devedor", 0) or valor_total

        story = L.header(company, "Factura de Consumo",
                         doc_meta=[f"N° {_safe_number(invoice)}"])

        story.append(L.section("Datos de la factura"))
        story.append(L.inline([
            ("Período",     _safe_period(invoice)),
            ("Emisión",     format_date(invoice.get("fecha_emision"))),
            ("Vencimiento", format_date(invoice.get("fecha_vencimiento"))),
        ], per_line=3))

        story.append(L.section("Cliente"))
        story.append(L.inline([
            ("Nombre",         str(client.get("name", "-"))),
            ("CI/RUC",         client.get("ci_ruc", "-")),
            ("Dirección",      str(client.get("address", "-"))),
            ("Manzana / Lote", f"{client.get('manzana', '-')} / {client.get('lote', '-')}"),
            ("Medidor",        client.get("meter", "-")),
        ], per_line=2))
        story.append(Spacer(1, 10))

        story.append(L.section("Detalle"))
        story.append(L.items_table(items))
        story.append(Spacer(1, 12))

        story.append(L.totals_block(
            [("Importe factura:", format_gs(valor_total)),
             ("Saldo anterior:",  format_gs(saldo))],
            ("TOTAL A PAGAR:",     format_gs(total)),
        ))

        return L.build_a4(story)


# ---------------------------------------------------------------------------
# InvoiceP80Generator (canvas — ticket térmico)
# ---------------------------------------------------------------------------

class InvoiceP80Generator(PDFGenerator):
    def __init__(self):
        super().__init__(page_size=(80 * mm, 190 * mm))

    def generate(self, invoice_payload: dict[str, Any]) -> bytes:
        invoice = invoice_payload.get("invoice", invoice_payload)
        client  = _client(invoice_payload)
        company = normalize_company(extract_company(invoice_payload))
        items   = invoice.get("items") or _default_items(invoice)

        dynamic_h = max(120, 95 + len(items) * 6)
        page_size = (80 * mm, dynamic_h * mm)
        c = self.create_canvas(page_size=page_size)
        width, height = page_size
        M  = PdfStyles.P80_MARGIN
        G  = GAP - 1.5 * mm   # GAP compacto para P80 (4.5mm)
        cx = width / 2
        iw = width - 2 * M
        y  = height - M

        y = draw_company_header_p80(c, width=width, margin=M, y=y,
                                    title="Factura de Consumo", company=company)

        # --- Info da fatura ---
        c.setFont(*PdfStyles.P80_FONT_BODY)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Periodo:")
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(width - M, y, f"{_safe_period(invoice)}   Nro: {_safe_number(invoice)}")
        y -= G
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Vencimiento:")
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(width - M, y, format_date(invoice.get('fecha_vencimiento')))
        y -= G

        draw_h_rule(c, M, y, iw)
        y -= G

        # --- Cliente ---
        c.setFont(*PdfStyles.P80_FONT_BODY)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Cliente:")
        c.setFillColor(PdfColors.GRAY)
        nombre = str(client.get('name', '-'))
        words = nombre.split()
        line1, line2 = [], []
        for w in words:
            if c.stringWidth(' '.join(line1 + [w]), PdfStyles.P80_FONT_BODY[0], PdfStyles.P80_FONT_BODY[1]) <= iw * 0.6:
                line1.append(w)
            else:
                line2.append(w)
        c.drawRightString(width - M, y, ' '.join(line1))
        if line2:
            y -= G * 0.75
            c.drawRightString(width - M, y, ' '.join(line2))
        y -= G
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "CI/RUC:")
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(width - M, y, str(client.get('ci_ruc', '-')))
        y -= G
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Estado:")
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(width - M, y, invoice.get('status', '-'))
        y -= G

        draw_h_rule(c, M, y, iw)
        y -= G

        # --- Itens ---
        c.setFont(*PdfStyles.P80_FONT_DOCTYPE)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "DESCRIPCION")
        c.drawRightString(width - M, y, "SUBTOTAL")
        y -= G / 2
        draw_h_rule(c, M, y, iw, thickness=0.5)
        y -= G

        c.setFont(*PdfStyles.P80_FONT_BODY)
        for item in items[:24]:
            c.setFillColor(PdfColors.DARK)
            c.drawString(M, y, str(item.get("descripcion", "-"))[:26])
            c.setFillColor(PdfColors.GRAY)
            c.drawRightString(width - M, y, format_gs(item.get("subtotal", 0)))
            y -= G

        draw_h_rule(c, M, y, iw, thickness=0.6)
        y -= G

        # --- Total ---
        c.setFont(*PdfStyles.P80_FONT_TOTAL)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "TOTAL A PAGAR:")
        c.drawRightString(width - M, y,
                          format_gs(invoice.get("total_a_pagar") or invoice.get("valor_total", 0)))
        y -= G

        draw_h_rule(c, M, y, iw, thickness=0.8)
        y -= G

        c.setFont("Helvetica", 6)
        c.setFillColor(PdfColors.LIGHT_GRAY)
        c.drawCentredString(cx, max(y, M), "TICKET - NO VÁLIDO COMO FACTURA LEGAL O CRÉDITO FISCAL")
        return self.finalize(c)


# ---------------------------------------------------------------------------
# BulkInvoiceA4Generator — 3 faturas por página (sem título, por design)
# ---------------------------------------------------------------------------

class BulkInvoiceA4Generator(PDFGenerator):
    def __init__(self):
        super().__init__(page_size=A4)

    def _draw_card(self, c, payload: dict[str, Any],
                   box_x: float, box_y: float, box_w: float, box_h: float):
        invoice = payload.get("invoice", payload)
        client  = _client(payload)
        company = extract_company(payload)
        items   = invoice.get("items") or _default_items(invoice)

        P  = 3 * mm   # padding interno do card
        cx = box_x + P
        rx = box_x + box_w - P
        G  = GAP * 0.85

        # Borda do card (linha sólida)
        c.setStrokeColor(PdfColors.RULE)
        c.setLineWidth(0.6)
        c.rect(box_x, box_y, box_w, box_h, stroke=1, fill=0)
        c.setLineWidth(1)

        # --- Cabeçalho do card: empresa | meta da fatura ---
        y = box_y + box_h - P - G * 0.6
        c.setFont(*PdfStyles.FONT_SECTION)
        c.setFillColor(PdfColors.DARK)
        c.drawString(cx, y, str(company.get("name", "")).upper()[:40])
        c.setFont(*PdfStyles.FONT_SMALL)
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(rx, y, f"Nro {_safe_number(invoice)}  |  {_safe_period(invoice)}")
        y -= G * 0.8

        c.setFont(*PdfStyles.FONT_SMALL)
        c.setFillColor(PdfColors.GRAY)
        c.drawString(cx, y, f"RUC: {company.get('ruc', '-')}")
        c.drawRightString(rx, y, f"Vence: {format_date(invoice.get('fecha_vencimiento'))}")
        y -= G * 0.7

        draw_h_rule(c, box_x, y, box_w, thickness=0.4)
        y -= G * 0.8

        # --- Cliente + Box manzana/lote ---
        manzana  = str(client.get("manzana", client.get("manzana_lote", "-"))).strip()
        lote     = str(client.get("lote", "-")).strip()
        box_w_ml = 13 * mm
        box_h_ml = 10 * mm
        bx       = rx - box_w_ml
        name_rx  = bx - 2 * mm

        line1_h  = G * 0.9
        line2_h  = G * 0.8
        block_h  = line1_h + line2_h
        center_y = y - block_h / 2
        by       = center_y - box_h_ml / 2 + 2 * mm
        half     = box_h_ml / 2

        c.setStrokeColor(PdfColors.RULE)
        c.setLineWidth(0.5)
        c.rect(bx, by, box_w_ml, box_h_ml, stroke=1, fill=0)
        c.line(bx, by + half, bx + box_w_ml, by + half)
        c.setLineWidth(1)
        c.setFont("Helvetica", 7)
        c.setFillColor(PdfColors.GRAY)
        c.drawCentredString(bx + box_w_ml / 2, by + half + 1.5 * mm, f"M {manzana}")
        c.drawCentredString(bx + box_w_ml / 2, by + 1.5 * mm,        f"L {lote}")

        c.setFont(*PdfStyles.FONT_LABEL)
        c.setFillColor(PdfColors.DARK)
        c.drawString(cx, y, str(client.get("name", "-"))[:38])
        y -= line1_h
        c.setFont(*PdfStyles.FONT_SMALL)
        c.setFillColor(PdfColors.GRAY)
        c.drawString(cx, y, f"CI/RUC: {client.get('ci_ruc', '-')}   Medidor: {client.get('meter', '-')}")
        c.drawRightString(name_rx, y, f"Estado: {invoice.get('status', '-')}")
        y -= line2_h

        draw_h_rule(c, box_x, y, box_w, thickness=0.4)
        y -= G * 0.8

        # --- Itens ---
        col_cant     = rx - 80 * mm
        col_gs_unit  = rx - 62 * mm
        col_num_unit = rx - 38 * mm
        col_gs_sub   = rx - 26 * mm

        c.setFont(*PdfStyles.FONT_SMALL)
        c.setFillColor(PdfColors.GRAY)
        c.drawString(cx, y, "DESCRIPCION")
        c.drawRightString(col_cant,     y, "CANT.")
        c.drawRightString(col_num_unit, y, "P. UNIT.")
        c.drawRightString(rx,           y, "SUBTOTAL")
        y -= G * 0.5
        draw_h_rule(c, box_x, y, box_w, thickness=0.3)
        y -= G * 0.75

        c.setFont(*PdfStyles.FONT_BODY)
        c.setFillColor(PdfColors.DARK)
        max_items = 4
        for item in items[:max_items]:
            unit_str = format_gs(item.get("precio_unitario", 0))
            sub_str  = format_gs(item.get("subtotal", 0))
            unit_num = unit_str[4:] if unit_str.startswith("Gs. ") else unit_str
            sub_num  = sub_str[4:]  if sub_str.startswith("Gs. ")  else sub_str

            c.drawString(cx, y, str(item.get("descripcion", "-"))[:38])
            c.drawRightString(col_cant,     y, str(item.get("cantidad", 1)))
            c.drawString(col_gs_unit,       y, "Gs.")
            c.drawRightString(col_num_unit, y, unit_num)
            c.drawString(col_gs_sub,        y, "Gs.")
            c.drawRightString(rx,           y, sub_num)
            y -= G * 0.85

        if len(items) > max_items:
            c.setFont(*PdfStyles.FONT_SMALL)
            c.setFillColor(PdfColors.LIGHT_GRAY)
            c.drawString(cx, y, f"+ {len(items) - max_items} item(s) adicional(es)")
            c.setFillColor(PdfColors.DARK)
            y -= G * 0.7

        # --- Total ---
        total_y = box_y + P + G * 0.4 - 2 * mm
        rule_y  = box_y + P + G * 0.4 + 5.5 * mm
        draw_h_rule(c, box_x, rule_y, box_w, thickness=0.5)

        c.setFont(*PdfStyles.FONT_SECTION)
        c.setFillColor(PdfColors.GRAY)
        c.drawString(cx, total_y, "TOTAL A PAGAR:")
        c.setFont(*PdfStyles.FONT_TOTAL)
        c.setFillColor(PdfColors.DARK)
        c.drawRightString(rx, total_y,
                          format_gs(invoice.get("total_a_pagar") or invoice.get("valor_total", 0)))

    def generate(self, invoices_data: list[dict[str, Any]]) -> bytes:
        if not invoices_data:
            c = self.create_canvas(page_size=A4)
            c.setFont(*PdfStyles.FONT_BODY)
            c.drawString(20 * mm, A4[1] - 20 * mm, "No hay facturas para impresion en lote.")
            return self.finalize(c)

        c = self.create_canvas(page_size=A4)
        width, height = A4
        M        = 10 * mm
        per_page = 3
        pages    = [invoices_data[i: i + per_page] for i in range(0, len(invoices_data), per_page)]

        card_gap = 4 * mm
        usable_h = height - 2 * M
        card_h   = (usable_h - card_gap * (per_page - 1)) / per_page
        card_w   = width - 2 * M

        for p_idx, page_data in enumerate(pages):
            if p_idx > 0:
                c.showPage()
            for slot in range(per_page):
                box_y = height - M - (slot + 1) * card_h - slot * card_gap
                if slot < len(page_data):
                    self._draw_card(c, page_data[slot],
                                    box_x=M, box_y=box_y, box_w=card_w, box_h=card_h)
                # slots vazios ficam em branco (sem borda tracejada)

        return self.finalize(c)
