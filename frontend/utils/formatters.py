"""
WMApp Frontend - Formatters
Funções utilitárias de formatação
"""
from datetime import datetime, date
from typing import Union


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
