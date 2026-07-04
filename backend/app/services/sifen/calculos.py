"""
Motor de cálculos monetários e tributários da facturación electrónica (SIFEN).

Regras (Manual Técnico v150, confirmadas em emissão real):
- Preços no Paraguai incluem IVA ("imposto por dentro").
- IVA 10%: liquidação = round_half_up(total / 11) ; base = total - liquidação
- IVA 5%:  liquidação = round_half_up(total / 21) ; base = total - liquidação
- Guaraní (PYG) não tem centavo → tudo inteiro, arredondamento HALF_UP.
- Cálculos são feitos POR ITEM primeiro, depois acumulados.
- Redondeo comercial (múltiplos de 50, Res. 347/2014 SEDECO) é OPCIONAL — desligado
  por padrão para a factura casar 1:1 com o recibo interno.

Portado da implementação de referência já validada na SET.
"""

from decimal import Decimal, ROUND_HALF_UP


def extraer_iva_10(precio_con_iva: Decimal) -> tuple[Decimal, Decimal]:
    """Base gravada e IVA de um preço com IVA 10% incluído. Retorna (base, iva)."""
    liquidacion_iva = (precio_con_iva / Decimal("11")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    base_gravada = precio_con_iva - liquidacion_iva
    return base_gravada, liquidacion_iva


def extraer_iva_5(precio_con_iva: Decimal) -> tuple[Decimal, Decimal]:
    """Base gravada e IVA de um preço com IVA 5% incluído. Retorna (base, iva)."""
    liquidacion_iva = (precio_con_iva / Decimal("21")).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    base_gravada = precio_con_iva - liquidacion_iva
    return base_gravada, liquidacion_iva


def redondeo_guarani(monto: Decimal) -> tuple[Decimal, Decimal]:
    """
    Redondeo comercial PYG (SEDECO Res. 347/2014): arredonda para BAIXO ao
    múltiplo de 50 mais próximo. Retorna (monto_redondeado, diferencia).
    A diferença vai em F013 (dRedon). Só usar se a junta cobra em múltiplos de 50.

    Ex.: 107437 -> (107400, 37) ; 47789 -> (47750, 39) ; 11000 -> (11000, 0)
    """
    monto_int = int(monto)
    redondeado = (monto_int // 50) * 50
    diferencia = monto_int - redondeado
    return Decimal(redondeado), Decimal(diferencia)


def calcular_valores_item(
    cantidad: Decimal,
    precio_unitario: Decimal,
    descuento: Decimal = Decimal("0"),
    tasa_iva: int = 10,
    proporcion_iva: int = 100,
) -> dict:
    """
    Calcula os valores monetários/tributários de um item.

    Retorna dict com:
      total_bruto (E727), descuento (EA002), total_operacion (EA008),
      base_gravada (E735), liquidacion_iva (E736).

    afetação é derivada pelo chamador: tasa_iva=0 => Exento/Exonerado.
    """
    total_bruto = (cantidad * precio_unitario).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    total_operacion = total_bruto - descuento

    base_gravada = Decimal("0")
    liquidacion_iva = Decimal("0")

    if tasa_iva == 10:
        base_gravada, liquidacion_iva = extraer_iva_10(total_operacion)
    elif tasa_iva == 5:
        base_gravada, liquidacion_iva = extraer_iva_5(total_operacion)
    # tasa_iva == 0: Exenta/Exonerada -> base e liquidação ficam 0

    # Gravado parcial (proporção < 100): reaplica e re-arredonda
    if proporcion_iva < 100 and tasa_iva > 0:
        factor = Decimal(proporcion_iva) / Decimal("100")
        base_gravada = (base_gravada * factor).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
        liquidacion_iva = (liquidacion_iva * factor).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )

    return {
        "total_bruto": total_bruto,          # E727 dTotBruOpeItem
        "descuento": descuento,              # EA002 dDescItem
        "total_operacion": total_operacion,  # EA008 dTotOpeItem
        "base_gravada": base_gravada,        # E735 dBasGravIVA
        "liquidacion_iva": liquidacion_iva,  # E736 dLiqIVAItem
    }


def calcular_totales(
    items_calculados: list[dict], moneda: str = "PYG", aplicar_redondeo: bool = False
) -> dict:
    """
    Totais do Grupo F a partir dos itens já calculados. Cada item deve trazer
    "tasa_iva" e "afectacion" (1=Gravado, 2=Exonerado, 3=Exento).

    aplicar_redondeo=False (default): total geral = total da operação (casa com o recibo).
    aplicar_redondeo=True: aplica múltiplos de 50 (SEDECO) e preenche dRedon.
    """
    sub_exenta = Decimal("0")
    sub_exonerada = Decimal("0")
    sub_iva_5 = Decimal("0")
    sub_iva_10 = Decimal("0")
    total_descuentos = Decimal("0")
    total_iva_5 = Decimal("0")
    total_iva_10 = Decimal("0")
    base_grav_5 = Decimal("0")
    base_grav_10 = Decimal("0")

    for item in items_calculados:
        tasa = item.get("tasa_iva", 0)
        afectacion = item.get("afectacion", 1)
        total_op = item["total_operacion"]
        total_descuentos += item["descuento"]

        if afectacion == 3:      # Exento
            sub_exenta += total_op
        elif afectacion == 2:    # Exonerado
            sub_exonerada += total_op
        elif tasa == 5:
            sub_iva_5 += total_op
            total_iva_5 += item["liquidacion_iva"]
            base_grav_5 += item["base_gravada"]
        elif tasa == 10:
            sub_iva_10 += total_op
            total_iva_10 += item["liquidacion_iva"]
            base_grav_10 += item["base_gravada"]

    total_operacion = sub_exenta + sub_exonerada + sub_iva_5 + sub_iva_10
    total_iva = total_iva_5 + total_iva_10

    redondeo = Decimal("0")
    total_gral = total_operacion
    if aplicar_redondeo and moneda == "PYG":
        total_gral, redondeo = redondeo_guarani(total_operacion)

    return {
        "sub_exenta": sub_exenta,               # F001 dSubExe
        "sub_exonerada": sub_exonerada,         # F002 dSubExo
        "sub_iva_5": sub_iva_5,                 # F004 dSub5
        "sub_iva_10": sub_iva_10,               # F005 dSub10
        "total_operacion": total_operacion,     # F008 dTotOpe
        "total_descuentos": total_descuentos,   # F009 dTotDesc
        "redondeo": redondeo,                   # F013 dRedon
        "total_gral": total_gral,               # F014 dTotGralOpe
        "iva_5": total_iva_5,                   # F015 dIva5
        "iva_10": total_iva_10,                 # F016 dIva10
        "total_iva": total_iva,                 # F017 dTotIVA
        "base_grav_5": base_grav_5,             # F019 dBaseGrav5
        "base_grav_10": base_grav_10,           # F020 dBaseGrav10
    }
