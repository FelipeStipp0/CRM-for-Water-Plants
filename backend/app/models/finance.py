"""
Modelos do Modulo Financeiro.

Inclui:
- CashTransaction: Movimentacoes de caixa (entradas/saidas)
- Expense: Despesas e fornecedores
- Employee: Funcionarios e folha de pagamento
"""

from datetime import datetime, date
from decimal import Decimal
from enum import Enum
from typing import Optional, List
from beanie import Document, Indexed, Link, PydanticObjectId
from pydantic import Field, BaseModel

from app.models.types import MongoDecimal


class TransactionType(str, Enum):
    """Tipo de transacao."""
    ENTRADA = "ENTRADA"
    SAIDA = "SAIDA"


class TransactionCategory(str, Enum):
    """Categoria da transacao."""
    # Entradas
    PAGAMENTO_FATURA = "PAGAMENTO_FATURA"  # Automatico
    TAXA_REATIVACAO = "TAXA_REATIVACAO"
    VENDA_MATERIAL = "VENDA_MATERIAL"
    OUTROS_ENTRADA = "OUTROS_ENTRADA"
    # Saidas
    SALARIO = "SALARIO"
    ADIANTAMENTO = "ADIANTAMENTO"
    DESPESA_MATERIAL = "DESPESA_MATERIAL"
    DESPESA_SERVICO = "DESPESA_SERVICO"
    DESPESA_MANUTENCAO = "DESPESA_MANUTENCAO"
    OUTROS_SAIDA = "OUTROS_SAIDA"


class CashTransaction(Document):
    """
    Movimentacao de caixa.

    Registra todas as entradas e saidas financeiras.
    Pagamentos de faturas geram transacoes automaticamente.
    """

    tipo: TransactionType
    categoria: TransactionCategory

    valor: MongoDecimal
    descripcion: str

    # Referencia opcional (pagamento, despesa, funcionario)
    reference_id: Optional[PydanticObjectId] = None
    reference_type: Optional[str] = None  # "payment", "expense", "payroll"

    # Data da transacao
    fecha: datetime = Field(default_factory=datetime.utcnow)

    # Quem registrou
    registrado_por: Optional[str] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "cash_transactions"
        indexes = [
            [("tipo", 1), ("fecha", -1)],
            [("categoria", 1), ("fecha", -1)],
            [("fecha", -1)],
        ]

    def __repr__(self) -> str:
        return f"CashTransaction({self.tipo.value}: {self.valor})"


class ExpenseStatus(str, Enum):
    """Status da despesa."""
    PENDENTE = "PENDENTE"
    PAGA = "PAGA"
    CANCELADA = "CANCELADA"


class ExpenseCategory(str, Enum):
    """Categoria de despesa."""
    MATERIAL = "MATERIAL"
    SERVICO = "SERVICO"
    MANUTENCAO = "MANUTENCAO"
    OUTROS = "OUTROS"


class ExpenseItem(BaseModel):
    """Item de uma despesa."""
    descripcion: str
    cantidad: int = 1
    precio_unitario: MongoDecimal

    @property
    def subtotal(self) -> Decimal:
        return Decimal(self.cantidad) * self.precio_unitario


class Expense(Document):
    """
    Despesa/Fatura de fornecedor.

    Registra compras de materiais, servicos e manutencao.
    """

    # Dados do fornecedor
    proveedor_nombre: str
    proveedor_ruc: Optional[str] = None
    proveedor_telefono: Optional[str] = None

    # Dados da fatura
    numero_factura: Optional[str] = None
    fecha_factura: date
    fecha_vencimiento: Optional[date] = None

    # Categoria e status
    categoria: ExpenseCategory
    status: ExpenseStatus = ExpenseStatus.PENDENTE

    # Itens
    items: List[ExpenseItem] = []

    # Totais
    valor_total: MongoDecimal

    # Pagamento
    fecha_pago: Optional[datetime] = None
    observacion: Optional[str] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "expenses"
        indexes = [
            [("status", 1), ("fecha_vencimiento", 1)],
            [("categoria", 1), ("fecha_factura", -1)],
            [("proveedor_nombre", 1)],
        ]

    def __repr__(self) -> str:
        return f"Expense({self.proveedor_nombre}: {self.valor_total})"


class EmployeeStatus(str, Enum):
    """Status do funcionario."""
    ATIVO = "ATIVO"
    INATIVO = "INATIVO"
    LICENCA = "LICENCA"


class EmployeeRole(str, Enum):
    """Cargo do funcionario."""
    ADMINISTRADOR = "ADMINISTRADOR"
    PRESIDENTE = "PRESIDENTE"
    TESOUREIRO = "TESOUREIRO"
    SECRETARIO = "SECRETARIO"
    LEITURISTA = "LEITURISTA"
    TECNICO = "TECNICO"
    COBRADOR = "COBRADOR"
    OUTROS = "OUTROS"


class Employee(Document):
    """
    Funcionario da Junta.
    """

    # Dados pessoais
    nombre_completo: Indexed(str)
    ci: Indexed(str, unique=True)
    telefono: Optional[str] = None
    direccion: Optional[str] = None

    # Dados profissionais
    cargo: EmployeeRole
    salario_base: MongoDecimal
    fecha_ingreso: date

    status: EmployeeStatus = EmployeeStatus.ATIVO

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None

    class Settings:
        name = "employees"
        indexes = [
            [("status", 1)],
            [("cargo", 1)],
        ]

    def __repr__(self) -> str:
        return f"Employee({self.nombre_completo}, {self.cargo.value})"


class PayrollStatus(str, Enum):
    """Status do pagamento."""
    PENDENTE = "PENDENTE"
    PAGO = "PAGO"
    CANCELADO = "CANCELADO"


class PayrollType(str, Enum):
    """Tipo de pagamento."""
    SALARIO = "SALARIO"
    ADIANTAMENTO = "ADIANTAMENTO"
    BONUS = "BONUS"
    DESCONTO = "DESCONTO"


class Payroll(Document):
    """
    Folha de pagamento / Lancamento de salario.
    """

    employee: Link[Employee]

    tipo: PayrollType
    status: PayrollStatus = PayrollStatus.PENDENTE

    # Periodo de referencia
    mes_referencia: int = Field(ge=1, le=12)
    ano_referencia: int

    # Valores
    valor_base: MongoDecimal
    descontos: MongoDecimal = Decimal("0")
    valor_liquido: MongoDecimal

    # Pagamento
    fecha_pago: Optional[datetime] = None
    observacion: Optional[str] = None

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)

    class Settings:
        name = "payroll"
        indexes = [
            [("employee", 1), ("ano_referencia", -1), ("mes_referencia", -1)],
            [("status", 1), ("fecha_pago", -1)],
        ]

    def __repr__(self) -> str:
        return f"Payroll({self.tipo.value}: {self.valor_liquido})"
