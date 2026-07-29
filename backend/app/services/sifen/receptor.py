"""
Construção do grupo do receptor (gDatRec) da facturación electrónica.

Duas naturezas (Manual v150, grupo D + payload real do portal):
- Contribuyente (tem RUC): iNatRec=1 + iTiContRec (1=física / 2=jurídica) + dRucRec
  (+ dDvRec opcional). Leva cPaisRec/dDesPaisRe. Nome/DV vêm de /parametros/contribuyente.
- No contribuyente (CI/passaporte/etc.): iNatRec=2 + iTipIDRec + ddTipIDRec + dNumIDRec.
  NÃO leva país. O nome vem de /parametros/ciudadano (cédula) ou é digitado.

Documento SEM dígito verificador: só os 7 (física) ou 8 (jurídica) números do RUC.
"""

from typing import Callable, Optional

# iTipIDRec (D210) — tipos de identificação do receptor no contribuyente
# RUC genérico de consumidor final (com e sem DV/pontuação, como aparece nos
# cadastros importados). Marca "cliente ocasional", não um contribuyente real.
RUC_OCASIONAL = {"44444401", "444444017"}

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
    # `44444401-7` é o RUC genérico de consumidor final: no cadastro ele marca
    # "cliente ocasional" (quem não tem documento válido — estrangeiro, ou dado
    # quebrado). Ele NÃO existe no padrón, então cairia aqui como se fosse uma
    # cédula de verdade e a factura sairia com esse número como CI. No DTE o
    # certo é innominado (iTipIDRec=5), que é o que a linha abaixo já faz.
    if num in RUC_OCASIONAL:
        num = ""
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


def dv_calculado(base: str) -> Optional[int]:
    """
    Dígito verificador do RUC (módulo 11, regra SET). None se `base` não for numérica.

    Serve para decidir com segurança se o último dígito de um número digitado sem
    hífen é DV ou parte do documento.
    """
    num = _solo_digitos(base)
    if not num:
        return None
    total, k = 0, 2
    for ch in reversed(num):
        total += int(ch) * k
        k = 2 if k >= 11 else k + 1
    resto = total % 11
    return 11 - resto if resto > 1 else 0


def separar_dv(doc: str) -> tuple[str, Optional[int]]:
    """
    Separa `documento` de `dígito verificador`.

    O padrón do DNIT é indexado pelo RUC **sem DV**, mas o cadastro guarda o que o
    operador digitou — quase sempre `80012345-6`. Colar o DV no número (o que um
    `só dígitos` faz) nunca encontra o contribuyente: a factura saía como CI, sem
    DV, para quem tem RUC ativo.

    - Com hífen: intenção explícita, separa direto.
    - Sem hífen: só separa se o último dígito **for** o DV do restante (módulo 11)
      e o número for longo o bastante para ser RUC+DV. Para CI (7-8 dígitos) não
      se mexe: em pessoa física o RUC É a cédula, então a busca direta é a certa —
      e chutar aqui acharia o RUC de OUTRA pessoa.
    """
    bruto = (doc or "").strip()
    if "-" in bruto:
        base, _, resto = bruto.partition("-")
        return _solo_digitos(base), _dv_int(_solo_digitos(resto))
    return _solo_digitos(bruto), None


def candidatos_consulta(num: str) -> list[str]:
    """
    Números a consultar no padrón, na ordem: o inteiro primeiro.

    Sem hífen o DV é ambíguo — `10000003` tanto pode ser uma cédula de 8 dígitos
    quanto o RUC `1000000` com DV `3`. Consultar o número inteiro antes evita
    quebrar quem é achado direto; a variante sem o último dígito só entra depois,
    e só se esse dígito **for** o DV do restante (módulo 11), o que corta 10 de
    cada 11 coincidências. Quem confere o resultado é o operador, na tela de
    confirmação, onde aparece o nome vindo do padrón.
    """
    num = _solo_digitos(num)
    saida = [num] if num else []
    if len(num) >= 8 and dv_calculado(num[:-1]) == int(num[-1]):
        saida.append(num[:-1])
    return saida


def resolver_receptor(
    provider,
    doc: str,
    *,
    email: Optional[str] = None,
    tipo_id: int = 1,
    nombre: Optional[str] = None,
    ruc_lookup: Optional[Callable[[str], dict]] = None,
) -> dict:
    """
    Classifica e monta o receptor.

    Contribuyente (RUC) vem do **registro DNIT** via `ruc_lookup(doc)` — regra
    Solo ACTIVO: só `es_contribuyente` (estado ACTIVO) vira RUC (com DV). Se
    `ruc_lookup` não for passado, cai no legado (portal `/contribuyente`), preservando
    os testes/uso antigo.

    No contribuyente (CI sem DV): o nome vem do cadastro do cliente (`nombre`), senão
    do portal `/ciudadano`, senão innominado. RUC cancelado/suspenso → no contribuyente.

    `provider` cumpre SifenProvider (login já feito). `email` sobrescreve o do cadastro.
    """
    # O que o operador digitou pode trazer o DV (`80012345-6`); o padrón é indexado
    # sem ele. `num` é o documento para consulta; `dv_informado` é o do cadastro.
    num, dv_informado = separar_dv(doc)

    # 1) contribuyente (RUC ACTIVO) — preferir o registro DNIT local
    if ruc_lookup is not None:
        for cand in candidatos_consulta(num):
            r = ruc_lookup(cand) or {}
            if r.get("es_contribuyente"):
                return build_receptor(
                    True, cand, (r.get("nombre") or nombre or "").strip(),
                    email=email,
                    dv=_dv_int(r.get("dv")) if r.get("dv") is not None else dv_informado,
                )
        # achou porém cancelado/suspenso, ou não achou → no contribuyente (abaixo)
    else:
        gd = provider.contribuyente(num)
        if gd and (gd.get("razonSocial") or gd.get("dv") is not None):
            return build_receptor(
                True, num, gd.get("razonSocial") or "",
                email=(gd.get("correoElectronico") or email),
                dv=_dv_int(gd.get("dv")) if gd.get("dv") is not None else dv_informado,
            )

    # 2) no contribuyente — nome do cadastro, senão portal, senão innominado
    if nombre and nombre.strip():
        return build_receptor(False, num, nombre.strip(), email=email, tipo_id=tipo_id)

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
