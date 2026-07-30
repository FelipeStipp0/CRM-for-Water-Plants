"""
Gerador de KuDE P80 (representação gráfica da factura electrónica SIFEN).

Engine escolhida: a do `kude_v2` (reportlab platypus, papel em rolo 80mm, altura
dinâmica), adaptada para bytes-in/bytes-out e com os ajustes pedidos:
- itens tabelados (cabeçalho Cant./P.Unitario/Total uma vez, não por item);
- receptor na ordem Nombre → RUC/CI → Dirección → Teléfono;
- CDC em grupos de 4, maior, em duas linhas (número é fixo: 44 díg. = 11 grupos);
- um único total;
- "solicite" (não "solicitar").

Só renderiza o XSD público do SIFEN — nada da engenharia reversa do portal.
Entrada: bytes do XML assinado (dsig + dCarQR). Saída: bytes do PDF (ou None sem reportlab).
"""

import io
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from xml.etree import ElementTree as ET

from config.fiscal import (
    LEYENDA_KUDE_L1,
    LEYENDA_KUDE_L2,
    LEYENDA_KUDE_L3,
    LEYENDA_KUDE_UNA_LINEA,
)

try:
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    REPORTLAB_DISPONIVEL = True
except ImportError:
    REPORTLAB_DISPONIVEL = False

try:
    import qrcode
    QRCODE_DISPONIVEL = True
except ImportError:
    QRCODE_DISPONIVEL = False

NS = {"s": "http://ekuatia.set.gov.py/sifen/xsd"}

if REPORTLAB_DISPONIVEL:
    PW = 72 * mm            # área imprimível real de papel 80mm
    MH = 2 * mm
    UW = PW - 2 * MH

    def S(name, fn="Helvetica", fs=7.5, ld=10, al=TA_LEFT, **kw):
        return ParagraphStyle(name, fontName=fn, fontSize=fs, leading=ld,
                              alignment=al, spaceAfter=0, spaceBefore=0, **kw)

    sN = S("n")
    sB = S("b", fn="Helvetica-Bold")
    sC = S("c", al=TA_CENTER)
    sCB = S("cb", fn="Helvetica-Bold", al=TA_CENTER)
    sTi = S("ti", fn="Helvetica-Bold", fs=10, ld=13, al=TA_CENTER)
    sInf = S("inf", fs=7, ld=9, al=TA_CENTER)
    sTim = S("tim", fn="Helvetica-Bold", fs=8.5, ld=11, al=TA_CENTER)
    sDoc = S("doc", fn="Helvetica-Bold", fs=11, ld=14, al=TA_CENTER)
    sSm = S("sm", fs=6.5, ld=8.5, al=TA_CENTER)
    sLbl = S("lbl", fs=7.5, ld=10)
    sVal = S("val", fs=7.5, ld=10)
    sNom = S("nom", fn="Helvetica-Bold", fs=8.5, ld=11)
    sIH = S("ih", fn="Helvetica-Bold", fs=7, ld=9, al=TA_CENTER)
    sIHR = S("ihr", fn="Helvetica-Bold", fs=7, ld=9, al=TA_RIGHT)  # cabeçalho alinhado à direita
    sIC = S("ic", fs=7, ld=9, al=TA_CENTER)
    sIR = S("ir", fs=7, ld=9, al=TA_RIGHT)
    sTL = S("tl", fs=7.5, ld=10)
    sTR = S("tr", fs=7.5, ld=10, al=TA_RIGHT)
    sTLB = S("tLB", fn="Helvetica-Bold", fs=8.5, ld=11)
    sTRB = S("tRB", fn="Helvetica-Bold", fs=8.5, ld=11, al=TA_RIGHT)
    sCDC = S("cdc", fn="Courier-Bold", fs=7.5, ld=10, al=TA_CENTER)  # maior, 2 linhas
    sFt = S("ft", fs=6.5, ld=8.5, al=TA_CENTER)


# --------------------------------------------------------------- helpers
def _p(t, st):
    return Paragraph(str(t), st)


def _sp(h=1):
    return Spacer(1, h * mm)


def _hr(th=0.5, b=0.8, a=0.8):
    return HRFlowable(width="100%", thickness=th, color=colors.black,
                      spaceBefore=b * mm, spaceAfter=a * mm)


def _g(node, path):
    if node is None:
        return ""
    el = node.find(path, NS)
    return (el.text or "").strip() if el is not None else ""


def _fmt_num(val):
    """Monto em guaraníes: milhar com '.', sem centavo.

    Emissores mandam decimais no XML mesmo em PYG (visto em DE real aprovado);
    arredonda HALF_UP em vez de truncar, senão 650374.8 vira 650.374.
    """
    try:
        d = Decimal(str(val or 0)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"{int(d):,}".replace(",", ".")
    except (ValueError, TypeError, InvalidOperation):
        return str(val)


def _fmt_cant(val):
    """Cantidad no formato es-PY: milhar '.', decimal ','. Sem casas se for inteira.

    Quantidade pode ser fracionária (litros, m³). Formatar como monto faria
    '79.314' litros parecer setenta e nove mil.
    """
    try:
        d = Decimal(str(val or 0))
    except (ValueError, TypeError, InvalidOperation):
        return str(val)
    if d == d.to_integral_value():
        return f"{int(d):,}".replace(",", ".")
    s = f"{d:,.4f}".rstrip("0").rstrip(".")
    inteiro, _, dec = s.partition(".")
    return inteiro.replace(",", ".") + ("," + dec if dec else "")


def _fmt_dt(val):
    try:
        return datetime.fromisoformat(val).strftime("%d/%m/%Y %H:%M:%S")
    except Exception:
        return val


def _fmt_d(val):
    try:
        return datetime.fromisoformat(val).strftime("%d/%m/%Y")
    except Exception:
        return val


def _formatar_fecha(val):
    """Formata data flexível (ISO/datetime) → dd/mm/aaaa [hh:mm]. '' se vazio."""
    if not val:
        return ""
    s = str(val).replace("T", " ").strip()
    for fin, fout in (("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M"), ("%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M"),
                      ("%Y-%m-%d", "%d/%m/%Y"), ("%Y%m%d", "%d/%m/%Y")):
        try:
            return datetime.strptime(s[:19], fin).strftime(fout)
        except ValueError:
            continue
    return s


def _make_qr(url, sz=40):
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=1)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return Image(buf, width=sz * mm, height=sz * mm)


# --------------------------------------------------------------- story
def _build_story(xml_bytes: bytes) -> list:
    root = ET.fromstring(xml_bytes)
    de = root.find("s:DE", NS)
    if de is None:
        raise ValueError("XML SIFEN inválido: falta <DE>")

    CW2 = [UW * 0.35, UW * 0.65]

    def sep():
        return _hr(th=0.8, b=2.5, a=2.5)

    T = de.find("s:gTimb", NS)
    tipo_de = _g(T, "s:dDesTiDE")
    num_tim = _g(T, "s:dNumTim")
    est, pun, num_doc = _g(T, "s:dEst"), _g(T, "s:dPunExp"), _g(T, "s:dNumDoc")
    fei_nit = _fmt_d(_g(T, "s:dFeIniT"))

    GD = de.find("s:gDatGralOpe", NS)
    fe_emi = _fmt_dt(_g(GD, "s:dFeEmiDE"))
    GC = GD.find("s:gOpeCom", NS) if GD is not None else None
    moneda = _g(GC, "s:dDesMoneOpe")
    if moneda and moneda.strip().lower() in ("guarani", "guaraní", "guaranies", "guaraníes"):
        moneda = "Guaraníes"

    E = GD.find("s:gEmis", NS) if GD is not None else None
    ruc_em, dv_em = _g(E, "s:dRucEm"), _g(E, "s:dDVEmi")
    nom_em = _g(E, "s:dNomEmi")
    dir_em, dep_em, ciu_em = _g(E, "s:dDirEmi"), _g(E, "s:dDesDepEmi"), _g(E, "s:dDesCiuEmi")
    tel_em = _g(E, "s:dTelEmi")
    acts = [_g(a, "s:dDesActEco") for a in (E.findall("s:gActEco", NS) if E is not None else [])
            if _g(a, "s:dDesActEco")]

    R = GD.find("s:gDatRec", NS) if GD is not None else None
    ruc_rec, dv_rec = _g(R, "s:dRucRec"), _g(R, "s:dDVRec")
    nom_rec = _g(R, "s:dNomRec")
    num_id_rec, tip_id_rec = _g(R, "s:dNumIDRec"), _g(R, "s:dDTipIDRec")
    dir_rec, tel_rec = _g(R, "s:dDirRec"), _g(R, "s:dTelRec")
    ciu_rec, dep_rec = _g(R, "s:dDesCiuRec"), _g(R, "s:dDesDepRec")

    GCond = de.find(".//s:gCamCond", NS)
    cond_ope = _g(GCond, "s:dDCondOpe") if GCond is not None else ""

    items = []
    for it in de.findall(".//s:gCamItem", NS):
        items.append({
            "cod": _g(it, "s:dCodInt"),
            "des": _g(it, "s:dDesProSer"),
            "cant": _g(it, "s:dCantProSer"),
            "precio": _g(it, "s:gValorItem/s:dPUniProSer"),
            "total": _g(it, "s:gValorItem/s:gValorRestaItem/s:dTotOpeItem"),
        })

    TS = de.find("s:gTotSub", NS)
    sub_exo, sub_exe = _g(TS, "s:dSubExo"), _g(TS, "s:dSubExe")
    sub5, sub10 = _g(TS, "s:dSub5"), _g(TS, "s:dSub10")
    tot_gral = _g(TS, "s:dTotGralOpe")
    iva5, iva10, tot_iva = _g(TS, "s:dIVA5"), _g(TS, "s:dIVA10"), _g(TS, "s:dTotIVA")
    base5, base10 = _g(TS, "s:dBaseGrav5"), _g(TS, "s:dBaseGrav10")

    cdc = de.get("Id", "")
    qr_url = ""
    fu = root.find("s:gCamFuFD", NS)
    if fu is not None:
        qe = fu.find("s:dCarQR", NS)
        if qe is not None and qe.text:
            qr_url = qe.text.strip()
    prot_aut = _g(root, "s:dProtAut") or _g(de, "s:dProtAut")

    St = []

    # ---- EMISSOR ----
    St.append(_p(nom_em, sTi))
    St.append(_sp(1.5))
    for act in acts:
        St.append(_p(act, sInf))
    St.append(_sp(1))
    if dir_em:
        St.append(_p(dir_em, sInf))
    St.append(_p(f"{ciu_em} - {dep_em} - PARAGUAY", sInf))
    if tel_em:
        St.append(_p(f"Tel: {tel_em}", sInf))
    St.append(_sp(1))
    St.append(_p(f"RUC: {ruc_em}-{dv_em}", sCB))
    St.append(sep())

    # ---- TIMBRADO + DOCUMENTO ----
    St.append(_p(f"Timbrado N°: {num_tim}", sC))
    St.append(_p(f"Inicio de Vigencia: {fei_nit}", sC))
    St.append(_sp(2))
    St.append(_p(tipo_de, sTim))
    St.append(_sp(1))
    St.append(_p(f"{est}-{pun}-{num_doc}", sDoc))
    St.append(_sp(2))
    St.append(_p(f"Fecha de Emisión: {fe_emi}", sC))
    St.append(_sp(0.5))
    St.append(_p(f"Moneda: {moneda}", sC))
    if cond_ope:
        St.append(_sp(0.5))
        St.append(_p(f"Condición de Venta: {cond_ope}", sC))
    St.append(sep())

    # ---- RECEPTOR: Nombre → RUC/CI → Dirección → Teléfono ----
    St.append(_p("Nombre:", sLbl))
    St.append(_p(nom_rec, sNom))
    St.append(_sp(1.5))
    if ruc_rec:
        ruc_disp = f"{ruc_rec}-{dv_rec}" if dv_rec else ruc_rec
        St.append(_p("RUC/CI:", sLbl))
        St.append(_p(ruc_disp, sB))
    elif num_id_rec:
        St.append(_p("RUC/CI:", sLbl))
        St.append(_p(num_id_rec, sB))
    if dir_rec:
        dr = dir_rec
        if ciu_rec:
            dr += f" - {ciu_rec}"
        if dep_rec:
            dr += f" - {dep_rec}"
        St.append(_sp(1.5))
        St.append(_p("Dirección:", sLbl))
        St.append(_p(dr, sVal))
    if tel_rec:
        St.append(_sp(1.5))
        St.append(_p("Teléfono:", sLbl))
        St.append(_p(tel_rec, sVal))
    St.append(sep())

    # ---- ÍTEMS (tabelado, com Cód.; sem linhas separadoras) ----
    cw_val = [UW * 0.14, UW * 0.14, UW * 0.36, UW * 0.36]  # Cód | Cant | P.Unit | Total
    _icell = TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 2), ("RIGHTPADDING", (0, 0), (-1, -1), 2),
        ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ])
    St.append(Table(
        [[_p("Cód.", sIH), _p("Cant.", sIH), _p("P.Unit.", sIHR), _p("Total", sIHR)]],
        colWidths=cw_val, style=_icell,
    ))
    for idx, it in enumerate(items):
        cant_str = _fmt_cant(it["cant"])
        St.append(_p(it["des"], sN))
        St.append(Table(
            [[_p(it["cod"], sIC), _p(cant_str, sIC),
              _p(_fmt_num(it["precio"]), sIR), _p(_fmt_num(it["total"]), sIR)]],
            colWidths=cw_val, style=_icell,
        ))
        if idx < len(items) - 1:
            St.append(_sp(1))
    St.append(sep())

    # ---- SUBTOTAIS + TOTAL (único) ----
    v_exe_tot = int(float(sub_exe or 0)) + int(float(sub_exo or 0))
    sub_rows = []
    if v_exe_tot > 0:
        sub_rows.append([_p("Subtotal Exentas:", sTL), _p(_fmt_num(v_exe_tot), sTR)])
    if float(sub5 or 0) > 0:
        sub_rows.append([_p("Subtotal Gravadas 5%:", sTL), _p(_fmt_num(sub5), sTR)])
    if float(sub10 or 0) > 0:
        sub_rows.append([_p("Subtotal Gravadas 10%:", sTL), _p(_fmt_num(sub10), sTR)])
    if sub_rows:
        St.append(Table(sub_rows, colWidths=CW2, style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ])))
        St.append(_sp(1))
    St.append(Table(
        [[_p("TOTAL:", sTLB), _p(_fmt_num(tot_gral), sTRB)]],
        colWidths=CW2,
        style=TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.black),
            ("LINEBELOW", (0, 0), (-1, -1), 1.2, colors.black),
            ("BOX", (0, 0), (-1, -1), 0.8, colors.black),
        ]),
    ))
    St.append(sep())

    # ---- LIQUIDACIÓN DEL IVA ----
    St.append(_p("LIQUIDACIÓN DEL IVA", sCB))
    St.append(_sp(1))
    iva_rows = []
    if float(base5 or 0) > 0:
        iva_rows.append([_p("Base Gravada 5%:", sTL), _p(_fmt_num(base5), sTR)])
        iva_rows.append([_p("Liquidación IVA 5%:", sTL), _p(_fmt_num(iva5), sTR)])
    if float(base10 or 0) > 0:
        iva_rows.append([_p("Base Gravada 10%:", sTL), _p(_fmt_num(base10), sTR)])
        iva_rows.append([_p("Liquidación IVA 10%:", sTL), _p(_fmt_num(iva10), sTR)])
    iva_rows.append([_p("Total IVA:", sTLB), _p(_fmt_num(tot_iva), sTRB)])
    St.append(Table(iva_rows, colWidths=CW2, style=TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.black),
    ])))
    St.append(sep())

    # ---- QR + CDC + RODAPÉ ----
    if qr_url and QRCODE_DISPONIVEL:
        St.append(_sp(1))
        St.append(Table([[_make_qr(qr_url, sz=40)]], colWidths=[UW], style=TableStyle([
            ("ALIGN", (0, 0), (0, 0), "CENTER"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ])))
        St.append(_sp(1.5))

    # CDC: grupos de 4, em DUAS linhas (44 díg. = 11 grupos → 6 + 5)
    grps = [cdc[i:i + 4] for i in range(0, len(cdc), 4)]
    mid = (len(grps) + 1) // 2
    St.append(_p(" ".join(grps[:mid]), sCDC))
    St.append(_p(" ".join(grps[mid:]), sCDC))

    if prot_aut:
        St.append(_sp(1))
        St.append(_p(f"Protocolo de autorización: {prot_aut}", sSm))

    St.append(_sp(2))
    St.append(_hr(th=0.3, b=0.5, a=0.5))
    St.append(_p("ESTE DOCUMENTO ES UNA REPRESENTACIÓN GRÁFICA", sFt))
    St.append(_p("DE UN DOCUMENTO ELECTRÓNICO (XML)", sFt))
    St.append(_sp(1))
    # O prazo vem de config.fiscal: a legenda impressa e o aviso da caja têm de
    # dizer o mesmo número, e ele muda num ponto só.
    St.append(_p(LEYENDA_KUDE_L1, sFt))
    St.append(_p(LEYENDA_KUDE_L2, sFt))
    St.append(_p(LEYENDA_KUDE_L3, sFt))
    St.append(_sp(5))
    return St


def build_kude(xml_bytes: bytes):
    """XML assinado (bytes) → PDF P80 (bytes). None se reportlab ausente."""
    if not REPORTLAB_DISPONIVEL:
        return None

    story = _build_story(xml_bytes)
    MARGIN_TOP, MARGIN_BOT = 4 * mm, 2 * mm

    # mede a altura do conteúdo numa página muito alta (papel em rolo)
    heights = []

    class HeightCapture(SimpleDocTemplate):
        def afterPage(self):
            heights.append(self.frame._y)

    doc_m = HeightCapture(io.BytesIO(), pagesize=(PW, 5000 * mm),
                          rightMargin=MH, leftMargin=MH,
                          topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOT)
    doc_m.build(list(story))

    if heights:
        frame_h = 5000 * mm - MARGIN_TOP - MARGIN_BOT
        content_h = frame_h - heights[0]
        real_h = content_h + MARGIN_TOP + MARGIN_BOT + 5 * mm
    else:
        real_h = 280 * mm

    buf = io.BytesIO()
    doc_f = SimpleDocTemplate(buf, pagesize=(PW, real_h),
                              rightMargin=MH, leftMargin=MH,
                              topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOT)
    doc_f.build(story)
    return buf.getvalue()


class KudeP80Generator:
    """Padrão dos geradores do CRM: generate(xml_bytes) -> bytes."""

    def generate(self, xml_bytes: bytes) -> bytes:
        return build_kude(xml_bytes)


# =================================================================== A4
# XML assinado -> doc_data (dict) para o gerador A4 (canvas).
def xml_to_doc_data(xml_bytes: bytes) -> dict:
    root = ET.fromstring(xml_bytes)
    de = root.find("s:DE", NS)
    if de is None:
        raise ValueError("XML SIFEN inválido: falta <DE>")
    T = de.find("s:gTimb", NS)
    GD = de.find("s:gDatGralOpe", NS)
    E = GD.find("s:gEmis", NS) if GD is not None else None
    R = GD.find("s:gDatRec", NS) if GD is not None else None
    GCond = de.find(".//s:gCamCond", NS)
    TS = de.find("s:gTotSub", NS)

    ruc_em, dv_em = _g(E, "s:dRucEm"), _g(E, "s:dDVEmi")
    ruc_rec, dv_rec = _g(R, "s:dRucRec"), _g(R, "s:dDVRec")
    num_id_rec = _g(R, "s:dNumIDRec")
    cliente_doc = (f"{ruc_rec}-{dv_rec}" if ruc_rec and dv_rec else ruc_rec) or num_id_rec
    est, pun, num_doc = _g(T, "s:dEst"), _g(T, "s:dPunExp"), _g(T, "s:dNumDoc")
    act = ""
    if E is not None:
        a = E.find("s:gActEco", NS)
        act = _g(a, "s:dDesActEco") if a is not None else ""

    items = []
    for it in de.findall(".//s:gCamItem", NS):
        items.append({
            "codigo": _g(it, "s:dCodInt"),
            "descricao": _g(it, "s:dDesProSer"),
            "quantidade": _g(it, "s:dCantProSer"),
            "preco_unitario": _g(it, "s:gValorItem/s:dPUniProSer"),
            "total_operacion": _g(it, "s:gValorItem/s:gValorRestaItem/s:dTotOpeItem"),
            "tasa_iva": _g(it, "s:gCamIVA/s:dTasaIVA"),
            "unidade_medida": _g(it, "s:dDesUniMed"),
        })
    qr_url = ""
    fu = root.find("s:gCamFuFD", NS)
    if fu is not None:
        qe = fu.find("s:dCarQR", NS)
        if qe is not None and qe.text:
            qr_url = qe.text.strip()
    return {
        "emisor_razon_social": _g(E, "s:dNomEmi"),
        "emisor_ruc": f"{ruc_em}-{dv_em}" if dv_em else ruc_em,
        "emisor_actividad": act,
        "emisor_direccion": _g(E, "s:dDirEmi"),
        "emisor_telefono": _g(E, "s:dTelEmi"),
        "emisor_email": _g(E, "s:dEmailE"),
        "timbrado": _g(T, "s:dNumTim"),
        "inicio_vigencia": _g(T, "s:dFeIniT"),
        "fin_vigencia": _g(T, "s:dFeFinT"),  # eletrônico não tem → vazio
        "tipo_documento_desc": _g(T, "s:dDesTiDE"),
        "numero_formatado": f"{est}-{pun}-{num_doc}",
        "fecha_emision": _g(GD, "s:dFeEmiDE"),
        "condicion": _g(GCond, "s:dDCondOpe"),
        "cliente_nome": _g(R, "s:dNomRec"),
        "cliente_doc": cliente_doc,
        "cliente_direccion": _g(R, "s:dDirRec"),
        "cliente_telefono": _g(R, "s:dTelRec"),
        "items_detalle": items,
        "subtotal_exento": _g(TS, "s:dSubExe") or _g(TS, "s:dSubExo"),
        "subtotal_5": _g(TS, "s:dSub5"),
        "subtotal_10": _g(TS, "s:dSub10"),
        "total_gral": _g(TS, "s:dTotGralOpe"),
        "iva_5": _g(TS, "s:dIVA5"),
        "iva_10": _g(TS, "s:dIVA10"),
        "total_iva": _g(TS, "s:dTotIVA"),
        "cdc": de.get("Id", ""),
        "qr_url": qr_url,
        # logo_bytes: opcional — o CRM injeta o logo da junta (o XML não tem)
    }


def gerar_kude_a4(doc_data: dict):
    """doc_data -> PDF A4 (canvas). Layout original (boxes/grade), com ajustes:
    logo 1x1 + header de altura variável; itens SEM linhas horizontais (mantém as
    verticais das colunas); números formatados; IVA sem 'Base'; vigencia 'al' só
    quando há data de fim do timbrado (o eletrônico não tem)."""
    if not REPORTLAB_DISPONIVEL:
        return None
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as _canvas
    from reportlab.lib.utils import ImageReader

    def n(v):
        return _fmt_num(v)

    buffer = io.BytesIO()
    c = _canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    margem_x = 10 * mm
    margem_y = 10 * mm
    largura_util = width - (2 * margem_x)
    h_footer = 45 * mm
    h_totais = 20 * mm
    y_table_bottom = margem_y + h_footer + 2 * mm
    y_totais_start = y_table_bottom + h_totais
    y_limit_items = y_totais_start
    y = height - margem_y

    def desenhar_box(x, yy, w, h):
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.5)
        c.rect(x, yy - h, w, h)

    def fit_text(text, max_width, font_name="Helvetica", font_size=7.5):
        """Trunca com reticências para não invadir a coluna vizinha."""
        s = (text or "").replace("\n", " ").strip()
        if c.stringWidth(s, font_name, font_size) <= max_width:
            return s
        while s and c.stringWidth(s + "...", font_name, font_size) > max_width:
            s = s[:-1]
        return s.rstrip() + "..."

    def draw_wrapped_text(text, x, yy, max_width, font_name="Helvetica", font_size=8, line_spacing=3 * mm):
        c.setFont(font_name, font_size)
        words = (text or "").replace("\n", " ").split(" ")
        lines, cur = [], []
        for word in words:
            if c.stringWidth(" ".join(cur + [word]), font_name, font_size) < max_width:
                cur.append(word)
            else:
                lines.append(" ".join(cur))
                cur = [word]
        if cur:
            lines.append(" ".join(cur))
        cy = yy
        for ln in lines:
            c.drawString(x, cy, ln)
            cy -= line_spacing
        return cy

    def _cdc_disp(cdc):
        return " ".join(cdc[i:i + 4] for i in range(0, len(cdc), 4))

    def desenhar_rodape_fixo():
        y_footer = margem_y + h_footer
        c.setLineWidth(0.5)
        c.line(margem_x, y_footer, width - margem_x, y_footer)
        qr_url = doc_data.get("qr_url", "")

        # QR ocupa a faixa inteira do rodapé (menos uma folga em cima e embaixo):
        # é o que o fiscal lê no celular, então quanto maior, melhor.
        pad = 3 * mm
        qr_size = h_footer - 2 * pad
        qr_bottom = margem_y + pad
        if qr_url and QRCODE_DISPONIVEL:
            q = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=1)
            q.add_data(qr_url)
            q.make(fit=True)
            im = q.make_image(fill_color="black", back_color="white")
            b = io.BytesIO()
            im.save(b, "PNG")
            b.seek(0)
            c.drawImage(ImageReader(b), margem_x, qr_bottom, qr_size, qr_size)

        x_cdc = margem_x + qr_size + 6 * mm
        larg_texto = width - margem_x - x_cdc

        # CDC tem 44 dígitos: com o QR maior, sobra menos largura. Encolhe a fonte
        # só o necessário para não vazar na margem.
        cdc_txt = f"CDC: {_cdc_disp(doc_data.get('cdc', ''))}"
        cdc_fs = 11
        while cdc_fs > 7 and c.stringWidth(cdc_txt, "Courier-Bold", cdc_fs) > larg_texto:
            cdc_fs -= 0.5

        # (fonte, tamanho, espaço ANTES da linha, cor, texto)
        linhas = [
            ("Helvetica-Bold", 8, 0, colors.black,
             "Consulte la validez de este Documento Electrónico con el CDC impreso abajo en:"),
            ("Helvetica", 8, 4.5 * mm, colors.black,
             "https://ekuatia.set.gov.py/consultas"),
            ("Courier-Bold", cdc_fs, 8 * mm, colors.black, cdc_txt),
            ("Helvetica", 6.5, 7.5 * mm, colors.black,
             "ESTE DOCUMENTO ES UNA REPRESENTACIÓN GRÁFICA DE UN DOCUMENTO ELECTRÓNICO (XML)"),
            ("Helvetica", 6.5, 3.5 * mm, colors.black, LEYENDA_KUDE_UNA_LINEA),
        ]
        # centra o bloco de texto na altura do QR, em vez de empilhar tudo no topo
        altura_bloco = sum(esp for _, _, esp, _, _ in linhas)
        y_txt = qr_bottom + qr_size - (qr_size - altura_bloco) / 2
        for fonte, tam, espaco, cor, texto in linhas:
            y_txt -= espaco
            c.setFont(fonte, tam)
            c.setFillColor(cor)
            c.drawString(x_cdc, y_txt, texto)
        c.setFillColor(colors.black)

    # ── CABEÇALHO (altura variável, com logo à esquerda) ──
    w_emissor = largura_util * 0.55
    w_info = largura_util - w_emissor
    x_info = margem_x + w_emissor
    y_top = y

    logo_sz = 20 * mm
    lx = margem_x + 3 * mm
    ly_top = y_top - 4 * mm
    logo = doc_data.get("logo_bytes")
    drew = False
    if logo:
        try:
            c.drawImage(ImageReader(io.BytesIO(logo)), lx, ly_top - logo_sz, logo_sz, logo_sz,
                        preserveAspectRatio=True, mask="auto")
            drew = True
        except Exception:
            drew = False
    if not drew:
        c.setStrokeColor(colors.Color(0, 0, 0, 0.35))
        c.setLineWidth(0.5)
        c.rect(lx, ly_top - logo_sz, logo_sz, logo_sz)
        c.setFillColor(colors.grey)
        c.setFont("Helvetica", 6)
        c.drawCentredString(lx + logo_sz / 2, ly_top - logo_sz / 2 - 2, "LOGO")
        c.setFillColor(colors.black)

    x_txt = lx + logo_sz + 3 * mm
    w_txt = w_emissor - (logo_sz + 9 * mm)
    ey = y_top - 6 * mm
    ey = draw_wrapped_text(doc_data.get("emisor_razon_social", ""), x_txt, ey, w_txt, "Helvetica-Bold", 10.5, 4.4 * mm)
    ey -= 2 * mm
    if doc_data.get("emisor_actividad"):
        ey = draw_wrapped_text(doc_data["emisor_actividad"], x_txt, ey, w_txt, "Helvetica", 7, 3 * mm)
        ey -= 1 * mm
    if doc_data.get("emisor_direccion"):
        ey = draw_wrapped_text(f"Dirección: {doc_data['emisor_direccion']}", x_txt, ey, w_txt, "Helvetica", 7, 3 * mm)
        ey -= 1 * mm
    contato = " | ".join(t for t in [
        f"Tel: {doc_data['emisor_telefono']}" if doc_data.get("emisor_telefono") else "",
        doc_data.get("emisor_email", "")] if t)
    if contato:
        ey = draw_wrapped_text(contato, x_txt, ey, w_txt, "Helvetica", 7, 3 * mm)
    left_bottom = min(ey, ly_top - logo_sz)

    # bloco fiscal (direita)
    x_info_txt = x_info + 4 * mm
    y_info = y_top - 7 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_info_txt, y_info, "RUC:")
    c.setFont("Helvetica", 9)
    c.drawString(x_info_txt + 10 * mm, y_info, doc_data.get("emisor_ruc", ""))
    y_info -= 6 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_info_txt, y_info, "TIMBRADO N°:")
    c.setFont("Helvetica", 9)
    c.drawString(x_info_txt + 26 * mm, y_info, str(doc_data.get("timbrado", "")))
    y_info -= 6 * mm
    ini = _formatar_fecha(doc_data.get("inicio_vigencia", ""))
    fin = _formatar_fecha(doc_data.get("fin_vigencia", ""))
    c.setFont("Helvetica-Bold", 9)
    c.drawString(x_info_txt, y_info, "Vigencia:")
    c.setFont("Helvetica", 9)
    c.drawString(x_info_txt + 18 * mm, y_info, f"{ini} al {fin}" if fin else ini)
    y_info -= 9 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(x_info_txt, y_info, f"{doc_data.get('tipo_documento_desc', '').upper()}   {doc_data.get('numero_formatado', '')}")
    y_info -= 4 * mm
    right_bottom = y_info

    header_bottom = min(left_bottom, right_bottom) - 3 * mm
    h_header = y_top - header_bottom
    desenhar_box(margem_x, y_top, w_emissor, h_header)
    desenhar_box(x_info, y_top, w_info, h_header)
    y = header_bottom - 2 * mm

    # ── DADOS DO CLIENTE (box) ──
    h_cliente = 22 * mm
    desenhar_box(margem_x, y, largura_util, h_cliente)
    y_cli = y - 4.5 * mm
    x_label = margem_x + 3 * mm
    x_val = margem_x + 30 * mm
    x_col2_label = margem_x + largura_util * 0.55
    x_col2_val = x_col2_label + 22 * mm
    w_col1_val = x_col2_label - x_val - 3 * mm  # limite da coluna 1: não invadir a coluna 2
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x_label, y_cli, "Fecha Emisión:")
    c.setFont("Helvetica", 7.5)
    c.drawString(x_val, y_cli, _formatar_fecha(doc_data.get("fecha_emision", "")))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x_col2_label, y_cli, "Condición:")
    c.setFont("Helvetica", 7.5)
    c.drawString(x_col2_val, y_cli, (doc_data.get("condicion", "CONTADO") or "").upper())
    y_cli -= 4.5 * mm
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x_label, y_cli, "Nombre/Razón:")
    c.setFont("Helvetica", 7.5)
    c.drawString(x_val, y_cli, fit_text(doc_data.get("cliente_nome", ""), w_col1_val))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x_col2_label, y_cli, "RUC/CI:")
    c.setFont("Helvetica", 7.5)
    c.drawString(x_col2_val, y_cli, doc_data.get("cliente_doc", ""))
    y_cli -= 4.5 * mm
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x_label, y_cli, "Dirección:")
    c.setFont("Helvetica", 7.5)
    c.drawString(x_val, y_cli, fit_text(doc_data.get("cliente_direccion", "-"), w_col1_val))
    c.setFont("Helvetica-Bold", 7.5)
    c.drawString(x_col2_label, y_cli, "Tel:")
    c.setFont("Helvetica", 7.5)
    c.drawString(x_col2_val, y_cli, doc_data.get("cliente_telefono", ""))
    y -= h_cliente + 2 * mm

    # ── TABELA DE ITENS (mantém verticais; SEM horizontais entre itens) ──
    header_h = 6 * mm
    cols = [
        {"name": "Código", "w": 22 * mm, "align": "L"},
        {"name": "Descripción", "w": 55 * mm, "align": "L"},
        {"name": "U.M.", "w": 13 * mm, "align": "L"},
        {"name": "Cant.", "w": 15 * mm, "align": "R"},
        {"name": "Precio Unit.", "w": 23 * mm, "align": "R"},
        {"name": "Exenta", "w": 20 * mm, "align": "R"},
        {"name": "5%", "w": 20 * mm, "align": "R"},
        {"name": "10%", "w": 22 * mm, "align": "R"},
    ]
    col_positions = []
    curr_x = margem_x
    for col in cols:
        col_positions.append(curr_x)
        curr_x += col["w"]

    def desenhar_header_tabela(y_pos):
        c.setFillColor(colors.lightgrey)
        c.rect(margem_x, y_pos - header_h, largura_util, header_h, fill=1)
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 7)
        y_t = y_pos - 4.5 * mm
        for i, col in enumerate(cols):
            cx = col_positions[i]
            if col["align"] == "R":
                c.drawRightString(cx + col["w"] - 2 * mm, y_t, col["name"])
            else:
                c.drawString(cx + 2 * mm, y_t, col["name"])
        return y_pos - header_h

    # Quebra de linha da descrição: cada item ocupa quantas linhas precisar e a
    # altura da linha acompanha, para o item seguinte nunca sobrepor.
    item_fs = 7
    item_line_h = 3.2 * mm
    row_h_min = 5 * mm
    desc_w = cols[1]["w"] - 4 * mm

    def _wrap_desc(text):
        """Quebra por palavra dentro da largura da coluna; palavra longa quebra por caractere."""
        lines, cur = [], ""
        for word in (text or "").replace("\n", " ").split():
            cand = f"{cur} {word}".strip()
            if c.stringWidth(cand, "Helvetica", item_fs) <= desc_w:
                cur = cand
                continue
            if cur:
                lines.append(cur)
            while c.stringWidth(word, "Helvetica", item_fs) > desc_w:
                cut = len(word)
                while cut > 1 and c.stringWidth(word[:cut], "Helvetica", item_fs) > desc_w:
                    cut -= 1
                lines.append(word[:cut])
                word = word[cut:]
            cur = word
        if cur:
            lines.append(cur)
        return lines or [""]

    y_table_top = y
    y = desenhar_header_tabela(y)
    c.setFont("Helvetica", 7)
    for item in doc_data.get("items_detalle", []):
        desc_lines = _wrap_desc(str(item.get("descricao", "")))
        row_h = max(row_h_min, 1.8 * mm + len(desc_lines) * item_line_h)
        if y - row_h < y_limit_items:
            for i, _ in enumerate(cols):
                cx = col_positions[i]
                c.line(cx, y_table_top, cx, y)
                if i == len(cols) - 1:
                    c.line(cx + cols[-1]["w"], y_table_top, cx + cols[-1]["w"], y)
            c.line(margem_x, y, width - margem_x, y)
            desenhar_rodape_fixo()
            c.showPage()
            y = height - margem_y
            y = desenhar_header_tabela(y)
            y_table_top = height - margem_y
            c.setFont("Helvetica", 7)

        try:
            tasa_i = int(float(item.get("tasa_iva", 10)))
        except Exception:
            tasa_i = 0
        total_line = item.get("total_operacion", "0")
        val_ex, val_5, val_10 = "0", "0", "0"
        if tasa_i == 10:
            val_10 = n(total_line)
        elif tasa_i == 5:
            val_5 = n(total_line)
        else:
            val_ex = n(total_line)
        cant = _fmt_cant(item.get("quantidade", ""))
        row_vals = [
            str(item.get("codigo", ""))[:12],
            None,  # descrição sai à parte (multilinha)
            str(item.get("unidade_medida", "") or "UNI"),
            str(cant),
            n(item.get("preco_unitario", "0")),
            val_ex, val_5, val_10,
        ]
        for i, val in enumerate(row_vals):
            if val is None:
                continue
            col_x = col_positions[i]
            col_w = cols[i]["w"]
            if cols[i]["align"] == "R":
                c.drawRightString(col_x + col_w - 2 * mm, y - 4 * mm, val)
            else:
                c.drawString(col_x + 2 * mm, y - 4 * mm, val)
        y_desc = y - 4 * mm
        for ln in desc_lines:
            c.drawString(col_positions[1] + 2 * mm, y_desc, ln)
            y_desc -= item_line_h
        y -= row_h
        # (removida a divisória horizontal leve entre itens)

    # ── FECHAMENTO DA GRADE (verticais) + TOTAIS (mantém as linhas) ──
    y_final_grid = y_totais_start
    c.setLineWidth(0.5)
    c.setStrokeColor(colors.black)
    for i, col in enumerate(cols):
        c.line(col_positions[i], y_table_top, col_positions[i], y_final_grid)
    cx_last = col_positions[-1] + cols[-1]["w"]
    c.line(cx_last, y_table_top, cx_last, y_final_grid)

    y = y_final_grid
    c.line(margem_x, y, width - margem_x, y)
    row_h_sub = 6 * mm
    c.setFont("Helvetica-Bold", 8)
    c.drawString(margem_x + 2 * mm, y - 4 * mm, "SUBTOTALES:")
    vals_sub = [n(doc_data.get("subtotal_exento", "0")), n(doc_data.get("subtotal_5", "0")), n(doc_data.get("subtotal_10", "0"))]
    for i in range(3):
        idx = 5 + i
        cx = col_positions[idx]
        cw = cols[idx]["w"]
        c.drawRightString(cx + cw - 2 * mm, y - 4 * mm, vals_sub[i])
        c.line(cx, y, cx, y - row_h_sub)
        c.line(cx + cw, y, cx + cw, y - row_h_sub)
    y -= row_h_sub
    c.line(margem_x, y, width - margem_x, y)

    row_h_total = 8 * mm
    c.setFont("Helvetica-Bold", 10)
    c.drawString(margem_x + 2 * mm, y - 5.5 * mm, "TOTAL GENERAL (Gs.)")
    c.setFont("Helvetica-Bold", 11)
    c.drawRightString(width - margem_x - 2 * mm, y - 5.5 * mm, n(doc_data.get("total_gral", "0")))
    c.line(margem_x, y, margem_x, y - row_h_total)
    c.line(width - margem_x, y, width - margem_x, y - row_h_total)
    y -= row_h_total
    c.line(margem_x, y, width - margem_x, y)

    # LIQUIDACIÓN DEL IVA — simplificado (SEM 'Base')
    row_h_iva = 6 * mm
    w_cell = largura_util / 3
    x1, x2, x3 = margem_x, margem_x + w_cell, margem_x + 2 * w_cell
    c.setFont("Helvetica", 8)
    c.drawString(x1 + 2 * mm, y - 4 * mm, f"IVA 5%: {n(doc_data.get('iva_5', '0'))}")
    c.line(x1, y, x1, y - row_h_iva)
    c.drawString(x2 + 2 * mm, y - 4 * mm, f"IVA 10%: {n(doc_data.get('iva_10', '0'))}")
    c.line(x2, y, x2, y - row_h_iva)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(x3 + 2 * mm, y - 4 * mm, f"Total IVA: {n(doc_data.get('total_iva', '0'))}")
    c.line(x3, y, x3, y - row_h_iva)
    c.line(width - margem_x, y, width - margem_x, y - row_h_iva)
    y -= row_h_iva
    c.setLineWidth(0.5)
    c.line(margem_x, y, width - margem_x, y)

    desenhar_rodape_fixo()
    c.save()
    return buffer.getvalue()


class KudeA4Generator:
    """A4: generate(xml_bytes, logo_bytes=None) -> bytes (mapeador + gerar_kude_a4).

    logo_bytes: PNG/JPG da logo quadrada 1×1 da junta (de SystemSettings.logo_cuadrado_*).
    """

    def generate(self, xml_bytes: bytes, logo_bytes: bytes | None = None) -> bytes:
        doc_data = xml_to_doc_data(xml_bytes)
        if logo_bytes:
            doc_data["logo_bytes"] = logo_bytes
        return gerar_kude_a4(doc_data)
