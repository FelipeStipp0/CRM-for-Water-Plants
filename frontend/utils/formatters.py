"""
WMApp Frontend - Formatters
Funções utilitárias de formatação
"""
from datetime import datetime, date, timezone
from typing import Optional, Union


def to_local(value: Union[str, datetime, None]) -> Optional[datetime]:
    """
    Converte um instante gravado pelo backend para a hora local da máquina.

    O backend grava tudo com `datetime.utcnow()` (naive, em UTC), então um
    datetime sem tzinfo é assumido como UTC. Datas puras ("2026-07-26", sem
    hora) voltam como estão — converter meia-noite mudaria o dia.
    """
    dt: Optional[datetime] = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        if "T" not in raw and " " not in raw:  # data pura: não tem instante
            try:
                return datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                return None
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone()


def local_day_range_utc(dia: date) -> tuple[str, str]:
    """
    Um dia do calendário local como intervalo UTC em ISO — (desde, hasta).

    O backend guarda instantes em UTC e não sabe o fuso do balcão; filtrar "hoy"
    comparando data crua trocaria de dia toda noite (Paraguai é UTC−3/−4). Quem
    sabe o fuso é esta máquina, então a conversão acontece aqui.
    """
    inicio_local = datetime(dia.year, dia.month, dia.day).astimezone()
    fin_local = datetime(dia.year, dia.month, dia.day, 23, 59, 59).astimezone()
    return (
        inicio_local.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
        fin_local.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
    )


def format_local(value: Union[str, datetime, None], fmt: str = "%d/%m/%Y %H:%M") -> str:
    """Formata na hora local um instante vindo do backend (UTC)."""
    dt = to_local(value)
    return dt.strftime(fmt) if dt else "-"


def format_currency(value: Union[str, float, int], symbol: str = "₲") -> str:
    """Formata valor monetário."""
    try:
        if isinstance(value, str):
            value = float(value.replace(",", "."))
        return f"{symbol} {value:,.0f}".replace(",", ".")
    except (ValueError, TypeError):
        return f"{symbol} 0"


def format_date(value: Union[str, datetime, date], format: str = "%d/%m/%Y") -> str:
    """Formata data."""
    try:
        if isinstance(value, str):
            # ISO format
            if "T" in value:
                value = datetime.fromisoformat(value.replace("Z", "+00:00"))
            else:
                value = datetime.strptime(value, "%Y-%m-%d")
        return value.strftime(format)
    except (ValueError, TypeError):
        return "-"


def format_datetime(value: Union[str, datetime], format: str = "%d/%m/%Y %H:%M") -> str:
    """Formata data e hora."""
    return format_date(value, format)


def format_month_year(mes: int, ano: int) -> str:
    """Formata mês/ano."""
    meses = [
        "", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
        "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
    ]
    return f"{meses[mes]} {ano}"


def format_phone(phone: str) -> str:
    """Formata telefone."""
    if not phone:
        return "-"
    # Remove caracteres não numéricos
    digits = "".join(filter(str.isdigit, phone))
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return phone


def truncate(text: str, max_length: int = 50) -> str:
    """Trunca texto."""
    if not text:
        return ""
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."
