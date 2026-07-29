"""
Consulta do registro de RUC (dados DNIT) — store nacional compartilhado.

Vive na coleção `ruc_registry` do banco `wmapp_ruc` (separado do admin
de propósito: um reset do ambiente não leva o padrón junto), indexada por `ruc`
(sem dígito verificador). É o mesmo dado para todas as orgs, por isso não é
replicado por tenant.

Regra de negócio (confirmada): **contribuyente = só estado `ACTIVO`**. Qualquer
outro estado (CANCELADO / SUSPENSION TEMPORAL / BLOQUEADO / CANCELADO DEFINITIVO)
→ **no contribuyente** (usa só CI sem DV).
"""

from app.database import get_ruc_db

COLLECTION = "ruc_registry"


async def lookup(doc: str) -> dict:
    """
    Retorna {found, ruc, estado, es_contribuyente, nombre, dv}.

    `found=False` quando o documento não está no registro (ex.: CI de quem nunca
    teve RUC) → o chamador trata como no contribuyente.

    O documento chega como o operador digitou (`80012345-6`); o registro é indexado
    sem DV. `separar_dv` é a mesma regra usada na montagem do receptor — com um
    `só dígitos` aqui, quem tem RUC nunca era encontrado.
    """
    from app.services.sifen.receptor import candidatos_consulta, separar_dv

    num, _dv = separar_dv(doc)
    # Mesmas tentativas da emissão: o que a tela de confirmação mostra tem de ser
    # exatamente o que vai sair na factura.
    reg = None
    for cand in candidatos_consulta(num):
        reg = await get_ruc_db()[COLLECTION].find_one({"ruc": cand})
        if reg:
            num = cand
            break
    if not reg:
        return {"found": False, "ruc": num, "estado": None,
                "es_contribuyente": False, "nombre": None, "dv": None}

    estado = (reg.get("estado") or "").strip().upper()
    return {
        "found": True,
        "ruc": num,
        "estado": estado,
        "es_contribuyente": estado == "ACTIVO",
        "nombre": reg.get("nombre"),
        "dv": reg.get("dv"),
    }
