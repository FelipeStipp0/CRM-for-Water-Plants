"""
Prazos e textos fiscais da facturación electrónica.

O prazo válido para pedir a cancelación de um DTE é o que a **própria SET imprime
no KuDE**:

    «Si su documento electrónico presenta algun error, podrá solicitar dentro de
    las 72 horas siguientes de la emisión del presente documento, la cancelación
    del mismo y la generación de un nuevo comprobante.»

Isso **substitui** o que consta no Manual Técnico v141 (2018), que fala em 48 h
da aprovação — manual desatualizado, e por isso não usado aqui.

O prazo vive nesta constante única porque é usado em dois lugares que não podem
divergir: a legenda impressa no KuDE (P80 e A4) e o aviso da caja quando o cajero
tenta anular um cobro com factura legal. Mudar aqui vale nos dois.
"""

from datetime import datetime, timedelta, timezone

# Horas a partir da EMISSÃO para solicitar a cancelación do documento no SET.
PLAZO_CANCELACION_HORAS = 72


def horas_desde_emision(fecha_emision) -> float | None:
    """
    Horas passadas desde a emissão. `None` quando a data é desconhecida.

    As datas do backend vêm em UTC (com ou sem tzinfo, dependendo do caminho):
    normaliza as duas pontas para UTC antes de subtrair, senão a conta erra em
    horas inteiras justamente perto do limite, que é onde ela importa.
    """
    if not fecha_emision:
        return None
    dt = fecha_emision
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def dentro_del_plazo(fecha_emision) -> bool:
    """
    A factura ainda pode ser cancelada no SET?

    Sem data conhecida devolve True: não é papel desta função barrar a tentativa
    por falta de informação — quem recusa de verdade é o SET, e o aviso da caja
    só serve para não deixar o cajero tentar às cegas.
    """
    horas = horas_desde_emision(fecha_emision)
    return True if horas is None else horas <= PLAZO_CANCELACION_HORAS


def horas_restantes(fecha_emision) -> float | None:
    """Quanto ainda resta do prazo (negativo quando já passou)."""
    horas = horas_desde_emision(fecha_emision)
    return None if horas is None else PLAZO_CANCELACION_HORAS - horas


def vence_en(fecha_emision) -> datetime | None:
    """Momento (UTC) em que o prazo de cancelación expira."""
    if not fecha_emision:
        return None
    dt = fecha_emision
    if isinstance(dt, str):
        try:
            dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(dt, datetime):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt + timedelta(hours=PLAZO_CANCELACION_HORAS)


# --- Legenda impressa (o texto fica como a SET escreve; só o número é variável) ---
LEYENDA_KUDE_L1 = "Si su documento electrónico presenta algún error,"
LEYENDA_KUDE_L2 = f"solicite la modificación dentro de las {PLAZO_CANCELACION_HORAS} horas"
LEYENDA_KUDE_L3 = "siguientes de la emisión de este comprobante."
LEYENDA_KUDE_UNA_LINEA = (
    "Si su documento electrónico presenta algún error, solicite la modificación "
    f"dentro de las {PLAZO_CANCELACION_HORAS} horas."
)
