"""
Receipt PDF generators.
"""
from __future__ import annotations

from typing import Any

from reportlab.lib.units import mm

from services.pdf_generation.base import PDFGenerator
from services.pdf_generation.company import draw_company_header_p80, extract_company, normalize_company
from services.pdf_generation.styles import (
    PdfColors, PdfStyles,
    draw_h_rule,
    format_date, format_gs, short_period,
)

G = PdfStyles.GAP - 1.5 * mm   # 4.5mm — GAP compacto P80


class PaymentReceiptP80Generator(PDFGenerator):
    """Thermal receipt (80mm) for payment results."""

    def __init__(self):
        super().__init__(page_size=(80 * mm, 210 * mm))

    def generate(self, payment_result: dict[str, Any]) -> bytes:
        affected          = payment_result.get("invoices_affected") or []
        subsidio_aplicado = bool(payment_result.get("subsidio_aplicado"))
        total_subsidio    = float(payment_result.get("total_subsidio", 0) or 0)

        # altura dinâmica: header + dados + faturas + totais + sello
        # Altura generosa: garante que sello + firma + disclaimer caibam sem
        # sobreposição (papel térmico é contínuo, espaço extra ao final é ok).
        extra_subsidio = 3 if (subsidio_aplicado and total_subsidio > 0) else 0
        dynamic_h = max(175, 150 + len(affected) * 6 + extra_subsidio * 8)
        page_size = (80 * mm, dynamic_h * mm)

        c = self.create_canvas(page_size=page_size)
        width, height = page_size
        M  = PdfStyles.P80_MARGIN
        cx = width / 2
        iw = width - 2 * M
        y  = height - M

        payment    = payment_result.get("payment", {})
        company    = normalize_company(extract_company(payment_result))
        valor_pago = float(payment.get("valor_total", 0) or 0)
        valor_orig = valor_pago + total_subsidio

        # --- Header empresa ---
        y = draw_company_header_p80(c, width=width, margin=M, y=y,
                                    title="Recibo de Pago", company=company)

        # --- Número do recibo + data ---
        _nro = payment.get("numero_recibo")
        recibo_txt = f"{int(_nro):05d}" if _nro is not None else str(payment.get("grupo_pagamento", "-"))[:32]
        c.setFont(*PdfStyles.P80_FONT_BODY)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Recibo:")
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(width - M, y, recibo_txt)
        y -= G

        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Fecha:")
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(width - M, y, format_date(payment.get("fecha_pago"), include_time=True))
        y -= G

        draw_h_rule(c, M, y, iw)
        y -= G

        # --- Datos del cliente ---
        c.setFont(*PdfStyles.P80_FONT_DOCTYPE)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Datos del cliente")
        y -= G * 0.85

        c.setFont(*PdfStyles.P80_FONT_BODY)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Nombre:")
        c.setFillColor(PdfColors.GRAY)
        nombre = str(payment_result.get("client_name", "-"))
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
        c.drawRightString(width - M, y, payment_result.get("client_ci_ruc", "-"))
        y -= G

        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Método:")
        c.setFillColor(PdfColors.GRAY)
        c.drawRightString(width - M, y, payment.get("metodo", "-"))
        y -= G

        draw_h_rule(c, M, y, iw)
        y -= G

        # --- Facturas afectadas ---
        c.setFont(*PdfStyles.P80_FONT_DOCTYPE)   # bold
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "FACTURAS AFECTADAS")
        c.drawRightString(width - M, y, "APLICADO")
        y -= G * 0.5
        draw_h_rule(c, M, y, iw, thickness=0.4)
        y -= G

        c.setFont(*PdfStyles.P80_FONT_BODY)
        if not affected:
            c.setFillColor(PdfColors.LIGHT_GRAY)
            c.drawString(M, y, "Ninguna")
            y -= G
        else:
            for alloc in affected:
                label = short_period(alloc.get("mes_referencia"), alloc.get("ano_referencia"))
                c.setFillColor(PdfColors.DARK)
                c.drawString(M, y, label)
                c.setFillColor(PdfColors.GRAY)
                c.drawRightString(width - M, y, format_gs(alloc.get("valor_aplicado", 0)))
                y -= G

        draw_h_rule(c, M, y, iw)
        y -= G

        # --- Totais ---
        c.setFont(*PdfStyles.P80_FONT_BODY)
        if subsidio_aplicado and total_subsidio > 0:
            c.setFillColor(PdfColors.DARK)
            c.drawString(M, y, "Valor original:")
            c.setFillColor(PdfColors.GRAY)
            c.drawRightString(width - M, y, format_gs(valor_orig))
            y -= G

            c.setFillColor(PdfColors.DARK)
            c.drawString(M, y, "Subsidio aplicado:")
            c.setFillColor(PdfColors.GRAY)
            c.drawRightString(width - M, y, f"- {format_gs(total_subsidio)}")
            y -= G * 0.5
            draw_h_rule(c, M, y, iw, thickness=0.4)
            y -= G

        c.setFont(*PdfStyles.P80_FONT_TOTAL)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "VALOR PAGADO:")
        c.drawRightString(width - M, y, format_gs(valor_pago))
        y -= G

        draw_h_rule(c, M, y, iw, thickness=0.8)
        y -= G

        # --- Subsidio sponsor ---
        if subsidio_aplicado and total_subsidio > 0:
            sponsor = payment_result.get("sponsor_name", "-")
            c.setFont(*PdfStyles.P80_FONT_SMALL)
            c.setFillColor(PdfColors.LIGHT_GRAY)
            sponsor_str = str(sponsor)
            c.drawString(M, y, "Subsidiado por:")
            y -= G * 0.75
            c.drawString(M, y, sponsor_str[:36])
            y -= G

        # --- Área sello y firma (borda sólida) ---
        draw_h_rule(c, M, y, iw, thickness=0.4)
        y -= G

        sello_h = 18 * mm
        sello_y = y - sello_h
        c.setStrokeColor(PdfColors.RULE)
        c.setLineWidth(0.6)
        c.rect(M, sello_y, iw, sello_h, stroke=1, fill=0)
        c.setLineWidth(1)
        c.setFont(*PdfStyles.P80_FONT_SMALL)
        c.setFillColor(PdfColors.LIGHT_GRAY)
        c.drawCentredString(cx, sello_y + sello_h - 5 * mm, "Sello y firma")

        # Disclaimer SEMPRE abaixo da caixa de sello, com folga (sem sobreposição).
        y = sello_y - G * 1.4
        c.setFont("Helvetica", 6)
        c.setFillColor(PdfColors.LIGHT_GRAY)
        c.drawCentredString(cx, y, "TICKET - NO VÁLIDO COMO FACTURA LEGAL O CRÉDITO FISCAL")

        return self.finalize(c)
