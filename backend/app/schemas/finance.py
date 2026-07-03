"""
Schemas do Modulo Financeiro.
"""

from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List

from pydantic import BaseModel, Field

from app.models.finance import (
    TransactionType,
    TransactionCategory,
    ExpenseCategory,
    ExpenseStatus,
    EmployeeRole,
    EmployeeStatus,
    PayrollType,
    PayrollStatus,
)


# ============ Cash Transaction ============

class CashTransactionCreate(BaseModel):
    """Schema para criar transacao manual."""
    tipo: TransactionType
    categoria: TransactionCategory
    valor: Decimal = Field(gt=0)
    descripcion: str = Field(min_length=3, max_length=200)


class CashTransactionResponse(BaseModel):
    """Schema de resposta de transacao."""
    id: str
    tipo: TransactionType
    categoria: TransactionCategory
    valor: Decimal
    descripcion: str
    reference_id: Optional[str] = None
    reference_type: Optional[str] = None
    fecha: datetime
    registrado_por: Optional[str] = None


class CashFlowSummary(BaseModel):
    """Resumo do fluxo de caixa."""
    periodo_inicio: date
    periodo_fim: date
    total_entradas: Decimal
    total_saidas: Decimal
    saldo_periodo: Decimal
    transacoes_count: int


class CashFlowByCategory(BaseModel):
    """Fluxo agrupado por categoria."""
    categoria: TransactionCategory
    total: Decimal
    count: int


# ============ Expense ============

class ExpenseItemCreate(BaseModel):
    """Item de despesa para criacao."""
    descripcion: str
    cantidad: int = Field(ge=1, default=1)
    precio_unitario: Decimal = Field(gt=0)


class ExpenseItemResponse(BaseModel):
    """Item de despesa para resposta."""
    descripcion: str
    cantidad: int
    precio_unitario: Decimal
    subtotal: Decimal


class ExpenseCreate(BaseModel):
    """Schema para criar despesa."""
    proveedor_nombre: str = Field(min_length=2)
    proveedor_ruc: Optional[str] = None
    proveedor_telefono: Optional[str] = None
    numero_factura: Optional[str] = None
    fecha_factura: date
    fecha_vencimiento: Optional[date] = None
    categoria: ExpenseCategory
    items: List[ExpenseItemCreate] = Field(min_length=1)
    observacion: Optional[str] = None


class ExpenseResponse(BaseModel):
    """Schema de resposta de despesa."""
    id: str
    proveedor_nombre: str
    proveedor_ruc: Optional[str] = None
    numero_factura: Optional[str] = None
    fecha_factura: date
    fecha_vencimiento: Optional[date] = None
    categoria: ExpenseCategory
    status: ExpenseStatus
    items: List[ExpenseItemResponse]
    valor_total: Decimal
    fecha_pago: Optional[datetime] = None
    observacion: Optional[str] = None
    created_at: datetime


class ExpensePayRequest(BaseModel):
    """Schema para pagar despesa."""
    observacion: Optional[str] = None


# ============ Employee ============

class EmployeeCreate(BaseModel):
    """Schema para criar funcionario."""
    nombre_completo: str = Field(min_length=3)
    ci: str = Field(min_length=5)
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    cargo: EmployeeRole
    salario_base: Decimal = Field(gt=0)
    fecha_ingreso: date


class EmployeeUpdate(BaseModel):
    """Schema para atualizar funcionario."""
    nombre_completo: Optional[str] = None
    ci: Optional[str] = None
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    cargo: Optional[EmployeeRole] = None
    salario_base: Optional[Decimal] = None
    status: Optional[EmployeeStatus] = None


class EmployeeResponse(BaseModel):
    """Schema de resposta de funcionario."""
    id: str
    nombre_completo: str
    ci: str
    telefono: Optional[str] = None
    direccion: Optional[str] = None
    cargo: EmployeeRole
    salario_base: Decimal
    fecha_ingreso: date
    status: EmployeeStatus
    created_at: datetime


# ============ Payroll ============

class PayrollCreate(BaseModel):
    """Schema para criar lancamento de folha."""
    employee_id: str
    tipo: PayrollType
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int = Field(ge=2000, le=2100)
    valor_base: Decimal = Field(gt=0)
    descontos: Decimal = Field(ge=0, default=Decimal("0"))
    observacion: Optional[str] = None


class PayrollResponse(BaseModel):
    """Schema de resposta de folha."""
    id: str
    employee_id: str
    employee_name: str
    tipo: PayrollType
    status: PayrollStatus
    mes_referencia: int
    ano_referencia: int
    valor_base: Decimal
    descontos: Decimal
    valor_liquido: Decimal
    fecha_pago: Optional[datetime] = None
    observacion: Optional[str] = None
    created_at: datetime


class PayrollPayRequest(BaseModel):
    """Schema para pagar folha."""
    observacion: Optional[str] = None
