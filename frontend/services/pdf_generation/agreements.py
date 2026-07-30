"""
Comprobante de acuerdo de pago (80mm) — o papel que o cliente leva do balcão.

Sai automático ao fechar o acordo, junto do recibo da entrada quando houve
entrada. É o único registro que o cliente tem do que combinou: total da dívida,
entrada, quantas parcelas, quanto cada uma e **em que mês** cada uma cai. Não é
documento fiscal (a factura legal sai no pagamento de cada parcela).

Mesma engine de duas passadas do cierre de caja: a 1ª desenha num papel folgado
só para medir onde o conteúdo termina, a 2ª desenha na altura exata. O número de
parcelas é livre, então estimar a altura por contagem erra e corta o rodapé.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from reportlab.lib.units import mm

from services.pdf_generation.base import PDFGenerator
from services.pdf_generation.company import (
    draw_company_header_p80, extract_company, normalize_company,
)
from services.pdf_generation.styles import (
    PdfColors, PdfStyles, draw_h_rule, format_gs, format_local_datetime,
)

G = PdfStyles.GAP - 1.5 * mm   # 4.5mm — mesmo passo compacto do recibo P80

_MES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
        "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


def _f(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _wrap(c, text: str, font: tuple, max_width: float) -> list[str]:
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


class AgreementP80Generator(PDFGenerator):
    """Comprobante de acuerdo de pago (80mm)."""

    def __init__(self):
        super().__init__(page_size=(80 * mm, 210 * mm))

    _PROBE_H = 400 * mm   # papel folgado da 1ª passada (só para medir)

    def generate(self, data: dict[str, Any]) -> bytes:
        """
        `data` = acordo (como vem de `/agreements`) + `client` + `company`.
        """
        M = PdfStyles.P80_MARGIN
        probe = self.create_canvas(page_size=(80 * mm, self._PROBE_H))
        y_end = self._draw(probe, 80 * mm, self._PROBE_H - M, data)
        altura = (self._PROBE_H - y_end) + M

        c = self.create_canvas(page_size=(80 * mm, altura))
        self._draw(c, 80 * mm, altura - M, data)
        return self.finalize(c)

    def _draw(self, c, width: float, y: float, data: dict[str, Any]) -> float:
        company = normalize_company(extract_company(data))
        client = data.get("client") or {}
        parcelas = data.get("parcelas") or []
        anuladas = data.get("facturas_anuladas") or []
        M = PdfStyles.P80_MARGIN
        cx = width / 2
        iw = width - 2 * M

        y = draw_company_header_p80(c, width=width, margin=M, y=y,
                                    title="Acuerdo de Pago", company=company,
                                    meta_color=PdfColors.DARK)

        def row(label: str, value: str, bold: bool = False):
            nonlocal y
            c.setFont(*(PdfStyles.P80_FONT_TOTAL if bold else PdfStyles.P80_FONT_BODY))
            c.setFillColor(PdfColors.DARK)
            c.drawString(M, y, label)
            c.drawRightString(width - M, y, value)
            y -= G

        def title(text: str):
            nonlocal y
            c.setFont(*PdfStyles.P80_FONT_DOCTYPE)
            c.setFillColor(PdfColors.DARK)
            c.drawString(M, y, text)
            y -= G * 0.85

        def rule(thickness: float = 0.4):
            nonlocal y
            draw_h_rule(c, M, y, iw, thickness=thickness)
            y -= G

        # --- Identificação do acordo ---
        c.setFont(*PdfStyles.P80_FONT_DOCTYPE)
        c.setFillColor(PdfColors.DARK)
        c.drawCentredString(cx, y, f"ACUERDO Nº {data.get('numero_fmt', '-')}")
        y -= G

        row("Fecha:", format_local_datetime(data.get("created_at") or datetime.utcnow()))
        row("Cajero:", str(data.get("creado_por", "-"))[:24])
        rule()

        title("Datos del cliente")
        for label, value in (("Nombre:", client.get("nombre_completo", "-")),
                             ("CI/RUC:", client.get("ci_ruc", "-")),
                             ("Medidor:", client.get("numero_medidor", "-"))):
            c.setFont(*PdfStyles.P80_FONT_BODY)
            c.setFillColor(PdfColors.DARK)
            c.drawString(M, y, label)
            lineas = _wrap(c, str(value or "-"), PdfStyles.P80_FONT_BODY, iw * 0.6)
            c.drawRightString(width - M, y, lineas[0] if lineas else "-")
            for extra in lineas[1:2]:
                y -= G * 0.75
                c.drawRightString(width - M, y, extra)
            y -= G
        rule()

        # --- O que entrou no acordo ---
        title("Deuda incluida")
        for f in anuladas:
            per = f"{_MES[int(f.get('mes_referencia', 1)) - 1]}/{f.get('ano_referencia', '-')}"
            nro = f.get("numero_factura")
            etiqueta = f"{per}" + (f"  Fact. {nro}" if nro else "")
            row(etiqueta, format_gs(f.get("saldo_incorporado", 0)))
        rule()

        row("Total de la deuda:", format_gs(data.get("total_deuda", 0)))
        if _f(data.get("entrada")):
            row("Entrada pagada hoy:", f"- {format_gs(data.get('entrada'))}")
        row("Total a financiar:", format_gs(data.get("total_parcelado", 0)), bold=True)
        c.setFont(*PdfStyles.P80_FONT_SMALL)
        c.setFillColor(PdfColors.DARK)
        c.drawString(M, y, "Sin intereses ni recargos.")
        y -= G
        rule()

        # --- Cronograma ---
        title(f"Cuotas ({data.get('n_parcelas', len(parcelas))})")
        for p in parcelas:
            per = f"{_MES[int(p.get('mes', 1)) - 1]}/{p.get('ano', '-')}"
            row(f"Cuota {p.get('numero', '-')}  ·  {per}", format_gs(p.get("valor", 0)))
        rule(thickness=0.8)

        # --- O que o cliente precisa saber ---
        c.setFont(*PdfStyles.P80_FONT_SMALL)
        c.setFillColor(PdfColors.DARK)
        aviso = ("Cada cuota se suma a la factura del mes correspondiente y vence "
                 "con ella. Si una cuota queda impaga, la factura de ese mes entra "
                 "en el proceso de corte como cualquier deuda.")
        for line in _wrap(c, aviso, PdfStyles.P80_FONT_SMALL, iw):
            c.drawString(M, y, line)
            y -= G * 0.7
        y -= G * 0.5

        obs = str(data.get("observacion") or "").strip()
        if obs:
            c.setFont(*PdfStyles.P80_FONT_SMALL)
            c.drawString(M, y, "Observaciones:")
            y -= G * 0.75
            for line in _wrap(c, obs, PdfStyles.P80_FONT_SMALL, iw)[:4]:
                c.drawString(M, y, line)
                y -= G * 0.7
            y -= G * 0.4

        # --- Firmas: o acordo é um compromisso das duas partes ---
        firma_h = 16 * mm
        firma_y = y - firma_h
        c.setStrokeColor(PdfColors.DARK)
        c.setLineWidth(0.6)
        c.rect(M, firma_y, iw / 2 - 1 * mm, firma_h, stroke=1, fill=0)
        c.rect(M + iw / 2 + 1 * mm, firma_y, iw / 2 - 1 * mm, firma_h, stroke=1, fill=0)
        c.setLineWidth(1)
        c.setFont(*PdfStyles.P80_FONT_SMALL)
        c.setFillColor(PdfColors.DARK)
        c.drawCentredString(M + (iw / 2 - 1 * mm) / 2, firma_y + firma_h - 4 * mm, "Cliente")
        c.drawCentredString(M + iw / 2 + 1 * mm + (iw / 2 - 1 * mm) / 2,
                            firma_y + firma_h - 4 * mm, "Cajero")

        y = firma_y - G * 1.4
        c.setFont("Helvetica", 6)
        c.setFillColor(PdfColors.DARK)
        c.drawCentredString(cx, y, "COMPROBANTE INTERNO - NO VÁLIDO COMO FACTURA LEGAL")

        return y - 2 * mm
