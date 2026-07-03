"""
Notification PDFs do fluxo de corte (Platypus — sem cores, QR no rodapé).

Conteúdo legal baseado nos templates de referência:
  - cutNoticeTemplate.html (Ley N° 1614/2000)
  - reactivationRequestTemplate.html
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from reportlab.lib.enums import TA_JUSTIFY, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, Spacer, Table, TableStyle

from services.pdf_generation import layout as L
from services.pdf_generation.base import PDFGenerator
from services.pdf_generation.company import extract_company
from services.pdf_generation.styles import format_date, format_gs

# ---------------------------------------------------------------------------
# Horário de atención e dados bancários VÊM das configurações da junta (Settings):
#   data["office_hours"]  <- settings.horario_atencion
#   data["bank_info"]     <- settings.banco_nombre + alias (tipo/valor)
# São OBRIGATÓRIOS: o frontend bloqueia a geração da nota se não estiverem
# configurados (sem fallback — nada de texto inventado num documento legal).
# Editáveis em Configurações > "Atención y Datos Bancarios".
# ---------------------------------------------------------------------------
_MONTHS_ES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
              "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def _long_date(value: Any) -> str:
    """Data por extenso em espanhol: '19 de enero de 2026'."""
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        dt = datetime(value.year, value.month, value.day)
    elif isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except Exception:
            dt = None
    if dt is None:
        dt = datetime.utcnow()
    return f"{dt.day} de {_MONTHS_ES[dt.month - 1]} de {dt.year}"


# Estilos de carta
_ST_RECIPIENT = ParagraphStyle("recipient", parent=L.S["field"], fontSize=10,
                               leading=13.5, alignment=TA_LEFT)
_ST_BODY = ParagraphStyle("letter_body", parent=L.S["body"], fontSize=10,
                          leading=15, alignment=TA_JUSTIFY, spaceAfter=8)
_ST_LEAD = ParagraphStyle("letter_lead", parent=L.S["field"], fontSize=10,
                          leading=14, alignment=TA_LEFT, spaceAfter=8)
_ST_BULLET = ParagraphStyle("letter_bullet", parent=L.S["field"], fontSize=10,
                            leading=14, leftIndent=14, bulletIndent=2, spaceAfter=3)


def _p(text: str) -> Paragraph:
    return Paragraph(text, _ST_BODY)


def _recipient(data: dict[str, Any]) -> Paragraph:
    """Bloco do destinatário (estilo carta), idêntico em todas as notificações."""
    rec = ["Señor/a:", str(data.get("client_name", "-"))]
    if data.get("client_ci_ruc"):
        rec.append(f"C.I. N°: {data.get('client_ci_ruc')}")
    if data.get("client_phone"):
        rec.append(str(data.get("client_phone")))
    if data.get("client_address"):
        rec.append(str(data.get("client_address")))
    rec.append("Presente")
    return Paragraph("<br/>".join(rec), _ST_RECIPIENT)


def _detalle_table(rows: list[tuple[str, str]], total_row: tuple[str, str]) -> Table:
    """Tabela 'Concepto | Importe' com linha de total em negrito."""
    tw = L.CONTENT_W
    th_r = ParagraphStyle("dthr", parent=L.S["th"], alignment=TA_RIGHT)
    data = [[Paragraph("CONCEPTO", L.S["th"]), Paragraph("IMPORTE", th_r)]]
    for label, val in rows:
        data.append([Paragraph(label, L.S["td"]), Paragraph(val, L.S["td_r"])])
    data.append([Paragraph(f"<b>{total_row[0]}</b>", L.S["td"]),
                 Paragraph(f"<b>{total_row[1]}</b>", L.S["td_r"])])
    n = len(data)
    t = Table(data, colWidths=[tw * 0.72, tw * 0.28])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2),
        ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, L.BLACK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.4, L.BLACK),
        ("LINEABOVE", (0, n - 1), (-1, n - 1), 0.8, L.BLACK),
    ]))
    return t


class CutNoticeGenerator(PDFGenerator):
    """A4 notificación / orden de corte de servicio (carta formal, Ley N° 1614/2000)."""

    def __init__(self):
        super().__init__(page_size=A4)

    def generate(self, data: dict[str, Any]) -> bytes:
        company = extract_company(data)
        name    = company.get("name", "La Junta de Saneamiento")
        title   = data.get("title", "Notificación de Corte de Servicio")
        issue_long = _long_date(data.get("issue_date") or datetime.utcnow())

        # Obrigatórios (validados no frontend antes de gerar). Sem fallback.
        office_hours = data.get("office_hours") or ""
        bank_info    = data.get("bank_info") or ""

        story = L.header(company, title)

        # --- Destinatário (estilo "bill to": empilhado, sem espaços entre linhas) ---
        story.append(_recipient(data))
        story.append(Spacer(1, 14))

        story.append(Paragraph("De nuestra mayor consideración:", _ST_LEAD))

        story.append(_p(
            f"La <b>{name}</b>, en cumplimiento de la <b>Ley N° 1614/2000</b>, que establece "
            "el marco regulatorio y tarifario de los servicios de agua potable en la "
            "República del Paraguay, se dirige a usted a fin de notificar la suspensión del "
            "servicio de agua potable por falta de pago y no respuesta a diversas "
            "notificaciones enviadas al usuario por el teléfono registrado."))
        story.append(_p(
            "Se concede un <b>plazo de quince (15) días corridos</b>, contados a partir de "
            f"la fecha de hoy, <b>{issue_long}</b>, para la regularización de la situación. "
            "Transcurrido dicho plazo sin respuesta ni pago, la Junta procederá al corte del "
            "suministro de agua potable, conforme a la normativa vigente."))
        story.append(_p(
            "Se recuerda igualmente que, según lo dispuesto en la <b>Ley N° 1614/2000</b>, "
            "la reconexión del servicio quedará sujeta al pago de la deuda total, más las "
            "multas y gastos administrativos correspondientes, que serán determinados al "
            "momento de la liquidación de los valores pendientes."))

        story.append(Paragraph(
            f"<b>Monto por pagar:</b> {format_gs(data.get('total_due', 0))} "
            f"(al {issue_long})", _ST_LEAD))

        story.append(Paragraph("<b>Medios de regularización habilitados:</b>", _ST_LEAD))
        story.append(Paragraph(
            f"Pago en la oficina administrativa de la Junta, en el horario de {office_hours}.",
            _ST_BULLET, bulletText="–"))
        story.append(Paragraph(
            f"Transferencia bancaria a la cuenta del {bank_info}.",
            _ST_BULLET, bulletText="–"))
        story.append(Spacer(1, 4))

        story.append(_p(
            "Para fines de regularización, también solicitamos que brinde con usted su "
            "cédula de identidad y un comprobante de residencia, preferentemente una factura "
            "de ANDE."))
        story.append(_p(
            "Sin otro particular, apelamos a su comprensión y solicitamos la regularización "
            "inmediata a fin de evitar la suspensión del servicio."))

        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Atentamente,<br/>La {name}", _ST_LEAD))

        return L.build_a4(story, qr_url=data.get("qr_url"))


class CutOrderGenerator(PDFGenerator):
    """A4 Orden de Corte — EXECUÇÃO do corte (Art. 54, Ley N° 1614/2000).

    Diferente da Nota/Notificación de Corte (que é o aviso prévio ao cliente):
    esta é a ordem de execução do serviço, emitida após vencido o prazo.
    """

    def __init__(self):
        super().__init__(page_size=A4)

    def generate(self, data: dict[str, Any]) -> bytes:
        company = extract_company(data)
        name    = company.get("name", "La Junta de Saneamiento")
        notif_long = _long_date(data.get("notification_date") or data.get("issue_date") or datetime.utcnow())

        deuda = data.get("total_due", 0)
        multa = data.get("multa", 0)
        total = float(deuda or 0) + float(multa or 0)

        story = L.header(company, "Orden de Corte de Servicio")
        story.append(_recipient(data))
        story.append(Spacer(1, 14))

        story.append(Paragraph("De nuestra mayor consideración:", _ST_LEAD))
        story.append(_p(
            f"La <b>{name}</b>, en cumplimiento de lo dispuesto en el <b>Artículo 54 de la "
            "Ley N° 1614/2000</b>, hace constar que, habiendo transcurrido el plazo de "
            "<b>quince (15) días corridos</b> otorgado mediante Notificación de Corte emitida "
            f"con fecha <b>{notif_long}</b>, sin que el/la usuario/a haya procedido a la "
            "regularización de la deuda registrada ni haya dado respuesta a las comunicaciones "
            "cursadas, se procede a emitir la presente <b>Orden de Corte del Servicio de Agua "
            "Potable</b>."))

        story.append(Paragraph("Detalle de la deuda al momento del corte:", _ST_LEAD))
        story.append(_detalle_table(
            [("Deuda principal", format_gs(deuda)),
             ("Multa y recargos", format_gs(multa))],
            ("Total adeudado", format_gs(total)),
        ))
        story.append(Spacer(1, 6))

        story.append(Paragraph(
            "De conformidad con el <b>Artículo 54 de la Ley N° 1614/2000</b>, se advierte "
            "al/la usuario/a que:", _ST_LEAD))
        for _b in (
            "El corte del servicio no lo/la exime del pago de los cargos fijos durante el "
            "período de interrupción, ni de los intereses y multas que correspondan.",
            "La reactivación del servicio quedará sujeta al pago total de la deuda acumulada, "
            "incluidos recargos, multas y gastos administrativos determinados al momento de la "
            "liquidación.",
            "Una vez efectuado el pago total, el servicio será restablecido en un plazo no "
            "mayor a <b>veinticuatro (24) horas</b>.",
        ):
            story.append(Paragraph(_b, _ST_BULLET, bulletText="–"))
        story.append(Spacer(1, 4))

        story.append(_p(
            "La presente Orden ha sido debidamente comunicada al <b>Ente Regulador de "
            "Servicios Sanitarios (ERSSAN)</b>, conforme lo exige la normativa vigente."))

        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Atentamente,<br/>La {name}", _ST_LEAD))

        return L.build_a4(story, qr_url=data.get("qr_url"))


class ReactivationRequestGenerator(PDFGenerator):
    """A4 orden / solicitud de reactivación (Ley N° 1614/2000)."""

    def __init__(self):
        super().__init__(page_size=A4)

    def generate(self, data: dict[str, Any]) -> bytes:
        company = extract_company(data)
        name    = company.get("name", "La Junta de Saneamiento")
        notif_long = _long_date(data.get("notification_date") or data.get("issue_date") or datetime.utcnow())
        pay_long   = _long_date(data.get("payment_date") or data.get("issue_date") or datetime.utcnow())
        comprobante = data.get("comprobante") or data.get("payment_number") or "-"

        deuda    = data.get("total_due", 0)
        recargos = data.get("reativation_fee", 0)
        total    = data.get("paid_value") or (float(deuda or 0) + float(recargos or 0))

        story = L.header(company, "Orden de Reactivación de Servicio")

        # --- Destinatário (mesmo bloco da nota de corte) ---
        story.append(_recipient(data))
        story.append(Spacer(1, 14))

        story.append(Paragraph("De nuestra mayor consideración:", _ST_LEAD))
        story.append(_p(
            f"La <b>{name}</b>, habiendo verificado la regularización total de la deuda "
            "registrada a nombre del/la usuario/a arriba identificado/a, correspondiente a "
            f"la notificación de corte emitida con fecha <b>{notif_long}</b>, procede a emitir "
            "la presente <b>Orden de Reactivación del Servicio de Agua Potable</b>."))

        story.append(Paragraph("Detalle de la regularización:", _ST_LEAD))
        story.append(_detalle_table(
            [("Deuda principal", format_gs(deuda)),
             ("Recargos y gastos administrativos", format_gs(recargos))],
            ("Total abonado", format_gs(total)),
        ))
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            f"<b>Fecha de pago:</b> {pay_long}&nbsp;&nbsp;|&nbsp;&nbsp;"
            f"<b>Comprobante N°:</b> {comprobante}", _ST_LEAD))

        story.append(_p(
            "En cumplimiento de lo dispuesto en el <b>Artículo 54 de la Ley N° 1614/2000</b>, "
            "la restitución del servicio deberá efectuarse en un plazo no mayor a "
            "<b>veinticuatro (24) horas</b> contadas a partir de la fecha y hora de emisión "
            "del presente documento."))
        story.append(_p(
            "El/la usuario/a queda notificado/a de que, en caso de no restablecerse el "
            "suministro dentro del plazo legal establecido, podrá recurrir al <b>Ente "
            "Regulador de Servicios Sanitarios (ERSSAN)</b> conforme al Artículo 35, inciso "
            "c) de la misma ley."))

        story.append(Spacer(1, 6))
        story.append(Paragraph(f"Atentamente,<br/>La {name}", _ST_LEAD))

        return L.build_a4(story, qr_url=data.get("qr_url"))
