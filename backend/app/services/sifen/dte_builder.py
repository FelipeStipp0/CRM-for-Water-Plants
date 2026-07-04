"""
Montagem do payload do documento eletrônico (DTE) para o `generar`.

Estrutura 100% padrão SIFEN (nomes do XSD do Manual v150) — espelha o corpo já
validado em emissão real. O timbrado/establecimiento/punto NÃO vão aqui: o portal
os injeta a partir do contribuinte logado. Cálculos vêm de calculos.py; o receptor
de receptor.py.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from app.services.sifen import calculos

# iAfecIVA / dDesAfecIVA (Manual v150, E731)
_AFEC_DESC = {
    1: "Gravado IVA",
    2: "Exonerado (Art. 83- Ley 125/91)",
    3: "Exento",
    4: "Gravado parcial (Afecta + Exento)",
}

# Obligación afectada default de uma junta (IVA + IRE SIMPLE). Ajustável por org.
_OBL_AFE_DEFAULT = [
    {"cOblAfe": "211", "dDesOblAfe": "IMPUESTO AL VALOR AGREGADO - GRAVADAS Y EXONERADAS - EXPORTADORES"},
    {"cOblAfe": "701", "dDesOblAfe": "IMPUESTO A LA RENTA EMPRESARIAL - SIMPLE"},
]


def _i(v) -> int:
    """Guaraní é inteiro."""
    return int(v)


def _fecha(dt: Optional[datetime] = None) -> str:
    return (dt or datetime.now()).strftime("%Y-%m-%dT%H:%M:%S")


def _cam_iva(tasa: int, afectacion: int, prop: int, base: Decimal, iva: Decimal) -> dict:
    return {
        "iAfecIVA": afectacion,
        "dDesAfecIVA": _AFEC_DESC.get(afectacion, "Gravado IVA"),
        "dPropIVA": prop if afectacion in (1, 4) else 0,
        "dTasaIVA": tasa if afectacion in (1, 4) else 0,
        "dBasGravIVA": _i(base),
        "dLiqIVAItem": _i(iva),
    }


def _cam_cond(condicion: dict) -> dict:
    """condicion: {tipo: 'contado'|'credito', forma_pago: {codigo, desc}}."""
    contado = (condicion.get("tipo") or "contado").lower() == "contado"
    forma = condicion.get("forma_pago") or {"codigo": 1, "desc": "Efectivo"}
    if contado:
        return {
            "iCondOpe": 1, "dDCondOpe": "Contado",
            "gPaConEIni": [{"iTiPago": forma["codigo"], "dDesTiPag": forma["desc"]}],
        }
    return {
        "iCondOpe": 2, "dDCondOpe": "Crédito",
        "gPagCred": {"iCondCred": 1, "dDCondCred": "Plazo"},
    }


def build_dte(
    receptor: dict,
    items: list[dict],
    condicion: dict,
    *,
    fecha: Optional[datetime] = None,
    obligaciones: Optional[list[dict]] = None,
    tipo_transaccion: tuple[int, str] = (1, "Venta de mercadería"),
    aplicar_redondeo: bool = False,
) -> dict:
    """
    Monta o DTE para o `generar`.

    items: [{descripcion, cantidad, precio_unit, tasa_iva, afectacion, proporcion?, codigo?}]
      - afectacion: 1=Gravado, 2=Exonerado, 3=Exento, 4=Parcial
      - tasa_iva: 10/5/0 ; proporcion: 100 (ou <100 p/ parcial)
    """
    cam_item = []
    calc_para_totais = []

    for it in items:
        cantidad = Decimal(str(it["cantidad"]))
        precio = Decimal(str(it["precio_unit"]))
        desc = Decimal(str(it.get("descuento", 0)))
        tasa = int(it.get("tasa_iva", 10))
        afect = int(it.get("afectacion", 1))
        prop = int(it.get("proporcion", 100))

        # afetação exenta/exonerada anula a taxa no cálculo
        tasa_calc = tasa if afect in (1, 4) else 0
        c = calculos.calcular_valores_item(cantidad, precio, desc, tasa_calc, prop)

        cam_item.append({
            "dCodInt": str(it.get("codigo", "1")),
            "dDesProSer": it["descripcion"],
            "cUniMed": 77, "dDesUniMed": "UNI",
            "dCantProSer": _i(cantidad) if cantidad == cantidad.to_integral() else float(cantidad),
            "gValorItem": {
                "dPUniProSer": _i(precio),
                "dTotBruOpeItem": _i(c["total_bruto"]),
                "gValorRestaItem": {
                    "dDescItem": _i(c["descuento"]),
                    "dTotOpeItem": _i(c["total_operacion"]),
                },
            },
            "gCamIVA": _cam_iva(tasa, afect, prop, c["base_gravada"], c["liquidacion_iva"]),
        })
        calc_para_totais.append({**c, "tasa_iva": tasa_calc, "afectacion": afect})

    t = calculos.calcular_totales(calc_para_totais, "PYG", aplicar_redondeo)
    base_total = _i(t["base_grav_5"] + t["base_grav_10"])

    g_tot_sub = {
        "dSubExe": _i(t["sub_exenta"]), "dSubExo": _i(t["sub_exonerada"]),
        "dSub5": _i(t["sub_iva_5"]), "dSub10": _i(t["sub_iva_10"]),
        "dIva5": _i(t["iva_5"]), "dIva10": _i(t["iva_10"]), "dTotIVA": _i(t["total_iva"]),
        "dBaseGrav5": _i(t["base_grav_5"]), "dBaseGrav10": _i(t["base_grav_10"]),
        "dTBasGraIVA": base_total,
        "dLiqTotIVA5": 0, "dLiqTotIVA10": 0,
        "dTotOpe": _i(t["total_operacion"]), "dTotDesc": _i(t["total_descuentos"]),
        "dTotDescGlotem": 0, "dTotAntItem": 0, "dTotAnt": 0,
        "dPorcDescTotal": 0, "dDescTotal": 0, "dAnticipo": 0,
        "dRedon": _i(t["redondeo"]), "dTotGralOpe": _i(t["total_gral"]),
    }

    return {
        "dSisFact": 2,
        "gTimb": {"iTiDE": 1, "dDesTiDE": "FACTURA ELECTRONICA"},
        "gDatGralOpe": {
            "dFeEmiDE": _fecha(fecha),
            "gOpeCom": {
                "iTipTra": tipo_transaccion[0], "dDesTipTra": tipo_transaccion[1],
                "iTImp": 1, "dDesTImp": "IVA",
                "cMoneOpe": "PYG", "dDesMoneOpe": "Guaraní",
                "gOblAfe": obligaciones or _OBL_AFE_DEFAULT,
            },
            "gDatRec": receptor,
        },
        "gDtipDE": {"gCamCond": _cam_cond(condicion), "gCamItem": cam_item},
        "gTotSub": g_tot_sub,
        "modalidad": 2,
    }
