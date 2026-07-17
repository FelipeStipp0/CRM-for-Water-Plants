"""
Consulta do registro de RUC (dados DNIT) — store nacional compartilhado.

Vive na coleção `ruc_registry` do banco admin (wmapp_admin), indexada por `ruc`
(sem dígito verificador). É o mesmo dado para todas as orgs, por isso não é
replicado por tenant.

Regra de negócio (confirmada): **contribuyente = só estado `ACTIVO`**. Qualquer
outro estado (CANCELADO / SUSPENSION TEMPORAL / BLOQUEADO / CANCELADO DEFINITIVO)
→ **no contribuyente** (usa só CI sem DV).
"""

from app.database import get_admin_db

COLLECTION = "ruc_registry"


def _solo_digitos(doc: str) -> str:
    return "".join(c for c in (doc or "") if c.isdigit())


async def lookup(doc: str) -> dict:
    """
    Retorna {found, ruc, estado, es_contribuyente, nombre, dv}.

    `found=False` quando o documento não está no registro (ex.: CI de quem nunca
    teve RUC) → o chamador trata como no contribuyente.
    """
    num = _solo_digitos(doc)
    if not num:
        return {"found": False, "ruc": num, "estado": None,
                "es_contribuyente": False, "nombre": None, "dv": None}

    reg = await get_admin_db()[COLLECTION].find_one({"ruc": num})
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
