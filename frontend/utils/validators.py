"""
WMApp Frontend - Validators
Funções de validação de dados
"""
import re
from typing import Optional, Tuple


def validate_required(value: str, field_name: str) -> Optional[str]:
    """Valida campo obrigatório."""
    if not value or not value.strip():
        return f"{field_name} é obrigatório"
    return None


def validate_length(value: str, field_name: str, min_len: int = None, max_len: int = None) -> Optional[str]:
    """Valida tamanho de string."""
    if min_len and len(value) < min_len:
        return f"{field_name} deve ter no mínimo {min_len} caracteres"
    if max_len and len(value) > max_len:
        return f"{field_name} deve ter no máximo {max_len} caracteres"
    return None


def validate_numeric(value: str, field_name: str, allow_decimal: bool = True) -> Optional[str]:
    """Valida valor numérico."""
    if not value:
        return None
    
    pattern = r"^\d+([.,]\d+)?$" if allow_decimal else r"^\d+$"
    if not re.match(pattern, value):
        return f"{field_name} deve ser um número válido"
    return None


def validate_positive(value: str, field_name: str) -> Optional[str]:
    """Valida valor positivo."""
    try:
        num = float(value.replace(",", "."))
        if num < 0:
            return f"{field_name} deve ser positivo"
    except (ValueError, TypeError):
        pass
    return None


def validate_ruc(ruc: str) -> Optional[str]:
    """Valida RUC paraguaio."""
    if not ruc:
        return None
    
    # RUC: 8 dígitos + guion + dígito verificador (ex: 12345678-9)
    # ou CI: 1-8 dígitos
    clean = ruc.replace("-", "").replace(".", "")
    if not clean.isdigit():
        return "CI/RUC deve conter apenas números"
    if len(clean) < 1 or len(clean) > 9:
        return "CI/RUC inválido"
    return None


def validate_phone(phone: str) -> Optional[str]:
    """Valida telefone."""
    if not phone:
        return None
    
    clean = "".join(filter(str.isdigit, phone))
    if len(clean) < 6 or len(clean) > 15:
        return "Telefone inválido"
    return None


def validate_email(email: str) -> Optional[str]:
    """Valida email."""
    if not email:
        return None
    
    pattern = r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$"
    if not re.match(pattern, email):
        return "Email inválido"
    return None


def validate_client_form(data: dict) -> Tuple[bool, dict]:
    """
    Valida formulário de cliente.
    
    Returns:
        Tuple[is_valid, errors_dict]
    """
    errors = {}
    
    # Obrigatórios
    for field in ["nombre_completo", "ci_ruc", "direccion", "manzana", "lote", "numero_medidor"]:
        err = validate_required(data.get(field, ""), field)
        if err:
            errors[field] = err
    
    # Tamanho nome
    if not errors.get("nombre_completo"):
        err = validate_length(data.get("nombre_completo", ""), "Nome", min_len=2, max_len=200)
        if err:
            errors["nombre_completo"] = err
    
    # CI/RUC
    if not errors.get("ci_ruc"):
        err = validate_ruc(data.get("ci_ruc", ""))
        if err:
            errors["ci_ruc"] = err
    
    # Telefones
    if data.get("telefono"):
        err = validate_phone(data.get("telefono"))
        if err:
            errors["telefono"] = err
    
    if data.get("celular"):
        err = validate_phone(data.get("celular"))
        if err:
            errors["celular"] = err
    
    return len(errors) == 0, errors
