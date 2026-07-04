"""
Testes do motor de cálculo da facturación electrónica (SIFEN) — puros, sem DB.

Cobrem: arredondamento HALF_UP do IVA, casamento base+IVA=total, exento,
totais do Grupo F, tipos de receptor e o payload do DTE contra um caso real.
"""

from decimal import Decimal

import pytest

from app.services.sifen import calculos, receptor, dte_builder


# ---------- IVA por item: arredondamento HALF_UP ----------

@pytest.mark.parametrize("total,iva_esperado", [
    (240000, 21818),   # 240000/11 = 21818,18 -> 21818 (caso real comprovado)
    (90000, 8182),     # 90000/11  = 8181,81  -> 8182
    (25000, 2273),     # 25000/11  = 2272,72  -> 2273
    (11000, 1000),     # exato
    (27500, 2500),     # exato
])
def test_iva_10_half_up(total, iva_esperado):
    base, iva = calculos.extraer_iva_10(Decimal(total))
    assert iva == iva_esperado
    # o detalhe crítico: base + IVA fecha exatamente com o total
    assert base + iva == Decimal(total)


@pytest.mark.parametrize("total,iva_esperado", [
    (21000, 1000),     # 21000/21 = 1000 exato
    (10000, 476),      # 10000/21 = 476,19 -> 476
    (5250, 250),       # exato
])
def test_iva_5_half_up(total, iva_esperado):
    base, iva = calculos.extraer_iva_5(Decimal(total))
    assert iva == iva_esperado
    assert base + iva == Decimal(total)


def test_item_exento_sem_iva():
    c = calculos.calcular_valores_item(Decimal(1), Decimal(50000), tasa_iva=0)
    assert c["base_gravada"] == 0
    assert c["liquidacion_iva"] == 0
    assert c["total_operacion"] == 50000


def test_item_gravado_parcial():
    # 50% gravado a 10% sobre 100000
    c = calculos.calcular_valores_item(Decimal(1), Decimal(100000), tasa_iva=10, proporcion_iva=50)
    # IVA cheio seria 100000/11=9091; metade -> 4545 (half-up de 4545,5)
    assert c["liquidacion_iva"] == 4546


# ---------- redondeo comercial (múltiplos de 50) ----------

@pytest.mark.parametrize("monto,red,dif", [
    (107437, 107400, 37),
    (47789, 47750, 39),
    (11000, 11000, 0),
])
def test_redondeo_guarani(monto, red, dif):
    r, d = calculos.redondeo_guarani(Decimal(monto))
    assert (int(r), int(d)) == (red, dif)


# ---------- totais do Grupo F ----------

def test_totales_mistos():
    itens = [
        {**calculos.calcular_valores_item(Decimal(1), Decimal(240000), tasa_iva=10),
         "tasa_iva": 10, "afectacion": 1},
        {**calculos.calcular_valores_item(Decimal(1), Decimal(50000), tasa_iva=0),
         "tasa_iva": 0, "afectacion": 3},
    ]
    t = calculos.calcular_totales(itens)
    assert t["sub_iva_10"] == 240000
    assert t["iva_10"] == 21818
    assert t["sub_exenta"] == 50000
    assert t["total_operacion"] == 290000
    assert t["total_gral"] == 290000  # redondeo desligado -> casa com o recibo
    assert t["redondeo"] == 0


# ---------- receptor ----------

def test_receptor_contribuyente_juridica():
    r = receptor.build_receptor(True, "80012345", "EMPRESA S.A.", dv=7)
    assert r["iNatRec"] == 1 and r["iTiContRec"] == 2
    assert r["dRucRec"] == "80012345" and r["dDvRec"] == 7


def test_receptor_contribuyente_fisica_sem_dv():
    r = receptor.build_receptor(True, "2438265", "MANOEL DIAZ")
    assert r["iNatRec"] == 1 and r["iTiContRec"] == 1
    assert r["dRucRec"] == "2438265" and "dDvRec" not in r


def test_receptor_ci():
    r = receptor.build_receptor(False, "1.234.567", "JUAN PEREZ")
    assert r["iNatRec"] == 2 and r["iTipIDRec"] == 1
    assert r["ddTipIDRec"] == "Cédula paraguaya"  # campo real do portal (dd minúsculo)
    assert r["dNumIDRec"] == "1234567"             # pontuação removida
    assert r["dNomRec"] == "JUAN PEREZ"
    assert "cPaisRec" not in r                      # CI não leva país (bate com a captura)


def test_receptor_pasaporte():
    r = receptor.build_receptor(False, "AB123456", "FOREIGN GUY", tipo_id=2)
    assert r["iTipIDRec"] == 2 and r["ddTipIDRec"] == "Pasaporte"
    assert r["dNumIDRec"] == "AB123456"             # alfanumérico preservado


def test_itiope_derivado():
    # jurídica (RUC 8 díg / órgão do estado) -> B2B(1)
    assert receptor.build_receptor(True, "80000856", "MUNICIPALIDAD X", dv=7)["iTiOpe"] == 1
    # física (RUC 7 díg) -> B2C(2)  (bate com a factura MANOEL já emitida)
    assert receptor.build_receptor(True, "2438265", "MANOEL")["iTiOpe"] == 2
    # no contribuyente (CI) -> B2C(2) obrigatório
    assert receptor.build_receptor(False, "7184730", "GASPAR")["iTiOpe"] == 2
    # override explícito (ex.: B2G com DNCP)
    assert receptor.build_receptor(True, "80000856", "X", dv=7, tipo_operacion=3)["iTiOpe"] == 3


def test_receptor_innominado():
    r = receptor.build_receptor(False, None, "")
    assert r["iNatRec"] == 2 and r["iTipIDRec"] == 5
    assert r["dNomRec"] == "Sin Nombre"


def test_resolver_receptor_ciudadano():
    # provider fake: não é contribuinte, mas é cidadão com nome
    class FakeProv:
        def contribuyente(self, doc): return None
        def ciudadano(self, doc):
            return {"numeroDocumento": doc, "razonSocial": "GASPAR FERNANDO AVANCO ", "dv": None}
    r = receptor.resolver_receptor(FakeProv(), "7184730")
    assert r["iNatRec"] == 2 and r["iTipIDRec"] == 1
    assert r["dNumIDRec"] == "7184730"
    assert r["dNomRec"] == "GASPAR FERNANDO AVANCO"


def test_b2g_gate():
    import pytest as _pt
    rec_oee = {"dRucRec": "80000856"}
    class ProvOEE:
        def es_oee(self, ruc): return True
    class ProvNao:
        def es_oee(self, ruc): return False
    # OEE -> B2G permitido (não levanta)
    receptor.validar_tipo_operacion(ProvOEE(), rec_oee, 3)
    # não-OEE -> B2G bloqueado
    with _pt.raises(ValueError):
        receptor.validar_tipo_operacion(ProvNao(), rec_oee, 3)
    # sem RUC (CI) -> B2G bloqueado
    with _pt.raises(ValueError):
        receptor.validar_tipo_operacion(ProvOEE(), {"dNumIDRec": "7184730"}, 3)
    # B2B/B2C nunca é gateado
    receptor.validar_tipo_operacion(ProvNao(), rec_oee, 1)
    receptor.validar_tipo_operacion(ProvNao(), rec_oee, 2)


def test_resolver_receptor_contribuyente():
    class FakeProv:
        def contribuyente(self, doc):
            return {"razonSocial": "MANOEL DIAZ NETO", "dv": "5", "correoElectronico": "x@y.com"}
        def ciudadano(self, doc): return None
    r = receptor.resolver_receptor(FakeProv(), "2438265")
    assert r["iNatRec"] == 1 and r["dRucRec"] == "2438265" and r["dDvRec"] == 5
    assert r["dEmailRec"] == "x@y.com"


# ---------- DTE completo contra caso real (240.000, IVA 10%) ----------

def test_build_dte_bate_com_caso_real():
    rec = receptor.build_receptor(True, "2438265", "MANOEL DIAZ NETO",
                                  email="HBC.CONTABLE@HOTMAIL.COM", dv=5)
    dte = dte_builder.build_dte(
        rec,
        [{"descripcion": "SUMINISTRO DE AGUA POTABLE", "cantidad": 8,
          "precio_unit": 30000, "tasa_iva": 10, "afectacion": 1, "codigo": "2"}],
        {"tipo": "contado", "forma_pago": {"codigo": 1, "desc": "Efectivo"}},
    )
    item = dte["gDtipDE"]["gCamItem"][0]
    assert item["gValorItem"]["dTotBruOpeItem"] == 240000
    assert item["gValorItem"]["gValorRestaItem"]["dTotOpeItem"] == 240000
    assert item["gCamIVA"]["dBasGravIVA"] == 218182
    assert item["gCamIVA"]["dLiqIVAItem"] == 21818

    tot = dte["gTotSub"]
    assert tot["dSub10"] == 240000
    assert tot["dIva10"] == 21818
    assert tot["dTotIVA"] == 21818
    assert tot["dBaseGrav10"] == 218182
    assert tot["dTotOpe"] == 240000
    assert tot["dTotGralOpe"] == 240000
    assert tot["dRedon"] == 0
