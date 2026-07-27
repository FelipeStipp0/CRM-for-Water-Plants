"""
Teste do gerador de KuDE P80 (engine kude_v2, XML assinado → PDF).

Roda de frontend/: python -m pytest tests/test_kude_mapper.py
Precisa de reportlab (pula se ausente).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "services", "pdf_generation"))

import pytest  # noqa: E402
from kude import build_kude, KudeP80Generator, REPORTLAB_DISPONIVEL  # noqa: E402

# XML SIFEN mínimo com os elementos que o KuDE lê (namespace XSD público).
SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rDE xmlns="http://ekuatia.set.gov.py/sifen/xsd">
  <DE Id="01800000007001001000000122026020111105369197">
    <gTimb>
      <dDesTiDE>Factura electronica</dDesTiDE><dNumTim>12560192</dNumTim>
      <dEst>001</dEst><dPunExp>001</dPunExp><dNumDoc>0000001</dNumDoc>
      <dFeIniT>2025-01-01</dFeIniT>
    </gTimb>
    <gDatGralOpe>
      <dFeEmiDE>2026-02-01T11:10:53</dFeEmiDE>
      <gOpeCom><dDesMoneOpe>Guarani</dDesMoneOpe></gOpeCom>
      <gEmis>
        <dRucEm>80000000</dRucEm><dDVEmi>7</dDVEmi>
        <dNomEmi>JUNTA DE SANEAMIENTO SANTA ROSA</dNomEmi>
        <dDirEmi>Calle Principal 123</dDirEmi><dTelEmi>021555000</dTelEmi>
        <dDesDepEmi>Central</dDesDepEmi><dDesCiuEmi>Asuncion</dDesCiuEmi>
      </gEmis>
      <gDatRec>
        <dNomRec>Maria Benitez Gonzalez</dNomRec>
        <dRucRec>2005001</dRucRec><dDVRec>1</dDVRec>
        <dDirRec>Barrio San Jose</dDirRec><dTelRec>0983111222</dTelRec>
      </gDatRec>
    </gDatGralOpe>
    <gDtipDE>
      <gCamCond><dDCondOpe>Contado</dDCondOpe></gCamCond>
      <gCamItem>
        <dCodInt>1</dCodInt><dDesProSer>Servicio de agua Jul/2026</dDesProSer>
        <dCantProSer>1</dCantProSer>
        <gValorItem><dPUniProSer>30000</dPUniProSer>
          <gValorRestaItem><dTotOpeItem>30000</dTotOpeItem></gValorRestaItem></gValorItem>
        <gCamIVA><dTasaIVA>10</dTasaIVA></gCamIVA>
      </gCamItem>
    </gDtipDE>
    <gTotSub>
      <dSub10>30000</dSub10><dTotGralOpe>30000</dTotGralOpe>
      <dBaseGrav10>27273</dBaseGrav10><dIVA10>2727</dIVA10><dTotIVA>2727</dTotIVA>
    </gTotSub>
  </DE>
  <gCamFuFD><dCarQR>https://ekuatia.set.gov.py/consultas/qr?nVersion=150&amp;Id=018</dCarQR></gCamFuFD>
</rDE>"""


@pytest.mark.skipif(not REPORTLAB_DISPONIVEL, reason="reportlab no instalado")
def test_gera_pdf_valido():
    pdf = KudeP80Generator().generate(SAMPLE_XML)
    assert pdf and pdf[:4] == b"%PDF"
    assert len(pdf) > 1000


@pytest.mark.skipif(not REPORTLAB_DISPONIVEL, reason="reportlab no instalado")
def test_receptor_solo_ci_sem_dv_nao_quebra():
    xml = SAMPLE_XML.replace(
        b"<dRucRec>2005001</dRucRec><dDVRec>1</dDVRec>",
        b"<dNumIDRec>3482190</dNumIDRec>",
    )
    pdf = build_kude(xml)
    assert pdf and pdf[:4] == b"%PDF"
