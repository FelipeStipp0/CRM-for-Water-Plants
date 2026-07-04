"""
Construção do grupo do receptor (gDatRec) da facturación electrónica.

Duas naturezas (Manual v150, grupo D + payload real do portal):
- Contribuyente (tem RUC): iNatRec=1 + iTiContRec (1=física / 2=jurídica) + dRucRec
  (+ dDvRec opcional). Leva cPaisRec/dDesPaisRe. Nome/DV vêm de /parametros/contribuyente.
- No contribuyente (CI/passaporte/etc.): iNatRec=2 + iTipIDRec + ddTipIDRec + dNumIDRec.
  NÃO leva país. O nome vem de /parametros/ciudadano (cédula) ou é digitado.

Documento SEM dígito verificador: só os 7 (física) ou 8 (jurídica) números do RUC.
"""

from typing import Optional

# iTipIDRec (D210) — tipos de identificação do receptor no contribuyente
TIPO_ID_DESC = {
    1: "Cédula paraguaya",
    2: "Pasaporte",
    3: "Cédula extranjera",
    4: "Carnet de residencia",
    5: "Innominado",
    6: "Tarjeta Diplomática de exoneración fiscal",
    9: "Otro",
}


def _solo_digitos(doc: str) -> str:
    return "".join(c for c in (doc or "") if c.isdigit())


def _limpa_doc(doc: str, tipo_id: int) -> str:
    # cédula paraguaya / carnet: numérico. Passaporte/estrangeiro/otro: alfanumérico.
    if tipo_id in (1, 4):
        return _solo_digitos(doc)
    return "".join(c for c in (doc or "") if c.isalnum())


def build_receptor(
    es_contribuyente: bool,
    doc: Optional[str],
    nombre: str,
    email: Optional[str] = None,
    dv: Optional[int] = None,
    es_juridica: Optional[bool] = None,
    tipo_id: int = 1,
    tipo_operacion: Optional[int] = None,
) -> dict:
    """
    Monta gDatRec.

    - es_contribuyente=True => RUC (iNatRec=1). doc = RUC sem DV; dv opcional.
    - es_contribuyente=False => no contribuyente (iNatRec=2). tipo_id em TIPO_ID_DESC.
    - tipo_operacion (iTiOpe): 1=B2B, 2=B2C, 3=B2G, 4=B2F. Se None, deriva (regra D202):
        no contribuyente        -> B2C (2) [obrigatório pela norma]
        contribuyente física    -> B2C (2)
        contribuyente jurídica  -> B2B (1)  [empresas e órgãos do estado/OEE]
      B2G (3) exige códigos DNCP por item (contrato de licitação) → passar explícito.
    """
    nombre = (nombre or "").strip()

    if es_contribuyente:
        num = _solo_digitos(doc)
        juridica = es_juridica if es_juridica is not None else len(num) >= 8
        ito = tipo_operacion if tipo_operacion is not None else (1 if juridica else 2)
        rec = {
            "cPaisRec": "PRY", "dDesPaisRe": "Paraguay",
            "iTiOpe": ito, "iNatRec": 1,
            "iTiContRec": 2 if juridica else 1, "dRucRec": num, "dNomRec": nombre,
        }
        if dv is not None:
            rec["dDvRec"] = int(dv)
        if email:
            rec["dEmailRec"] = email.strip()
        return rec

    # no contribuyente -> B2C obrigatório (D202)
    ito = tipo_operacion if tipo_operacion is not None else 2
    num = _limpa_doc(doc, tipo_id)
    if tipo_id == 5 or not num:  # innominado (consumidor final sem identificação)
        return {
            "iNatRec": 2, "iTiOpe": ito, "iTipIDRec": 5,
            "ddTipIDRec": "Innominado", "dNumIDRec": "0", "dNomRec": "Sin Nombre",
        }
    rec = {
        "iNatRec": 2, "iTiOpe": ito, "iTipIDRec": tipo_id,
        "ddTipIDRec": TIPO_ID_DESC.get(tipo_id, "Cédula paraguaya"),
        "dNumIDRec": num, "dNomRec": nombre or "SIN NOMBRE",
    }
    if email:
        rec["dEmailRec"] = email.strip()
    return rec


def _dv_int(v) -> Optional[int]:
    return int(v) if v is not None and str(v).isdigit() else None


def resolver_receptor(provider, doc: str, *, email: Optional[str] = None, tipo_id: int = 1) -> dict:
    """
    Classifica e monta o receptor consultando o portal:
      1) /contribuyente  -> tem RUC/DV  => contribuinte (RUC)
      2) /ciudadano      -> cédula      => no contribuyente (CI) + nome
      3) nada            -> innominado

    `provider` cumpre SifenProvider (login já feito). `email` sobrescreve o do cadastro.
    """
    num = _solo_digitos(doc)

    gd = provider.contribuyente(num)
    if gd and (gd.get("razonSocial") or gd.get("dv") is not None):
        return build_receptor(
            True, num, gd.get("razonSocial") or "",
            email=(gd.get("correoElectronico") or email),
            dv=_dv_int(gd.get("dv")),
        )

    gd = provider.ciudadano(num)
    if gd and gd.get("razonSocial"):
        return build_receptor(False, num, gd["razonSocial"].strip(), email=email, tipo_id=tipo_id)

    return build_receptor(False, None, "", tipo_id=5)  # innominado


def validar_tipo_operacion(provider, receptor: dict, tipo_operacion: int) -> None:
    """
    Valida a escolha manual de iTiOpe. **B2G (3) só é permitido para OEE**
    (Organismo/Entidad del Estado) — bloqueia o operador de emitir B2G para
    cliente comum. Levanta ValueError se inválido. DNCP é opcional (não exigido).
    """
    if tipo_operacion == 3:  # B2G
        ruc = receptor.get("dRucRec")
        if not ruc:
            raise ValueError("B2G exige un receptor contribuyente con RUC.")
        if not provider.es_oee(ruc):
            raise ValueError("B2G permitido solo para entidades del Estado (OEE).")
