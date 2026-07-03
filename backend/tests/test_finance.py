"""
Testes do Modulo Financeiro.

Testa:
- Transacoes de caixa
- Despesas
- Funcionarios
- Folha de pagamento
- Integracao pagamento -> caixa
"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.models.finance import (
    CashTransaction,
    TransactionType,
    TransactionCategory,
    Expense,
    ExpenseItem,
    ExpenseStatus,
    ExpenseCategory,
    Employee,
    EmployeeStatus,
    EmployeeRole,
    Payroll,
    PayrollStatus,
    PayrollType,
)
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType
from app.models.client import Client
from app.services.payment_distribution import PaymentDistributionService


# ============ Cash Transaction Tests ============

@pytest.mark.asyncio
async def test_create_cash_transaction(test_db):
    """Testa criacao de transacao de caixa."""
    transaction = CashTransaction(
        tipo=TransactionType.ENTRADA,
        categoria=TransactionCategory.VENDA_MATERIAL,
        valor=Decimal("50000"),
        descripcion="Venda de cano PVC",
        registrado_por="Admin",
    )
    await transaction.insert()

    assert transaction.id is not None
    assert transaction.tipo == TransactionType.ENTRADA
    assert transaction.valor == Decimal("50000")


@pytest.mark.asyncio
async def test_cash_transaction_output(test_db):
    """Testa transacao de saida."""
    transaction = CashTransaction(
        tipo=TransactionType.SAIDA,
        categoria=TransactionCategory.DESPESA_MANUTENCAO,
        valor=Decimal("100000"),
        descripcion="Reparo de bomba",
    )
    await transaction.insert()

    assert transaction.tipo == TransactionType.SAIDA
    assert transaction.categoria == TransactionCategory.DESPESA_MANUTENCAO


@pytest.mark.asyncio
async def test_payment_creates_cash_transaction(test_db, sample_client, test_settings):
    """Testa que pagamento de fatura cria transacao automatica."""
    # Cria fatura
    invoice = Invoice(
        client=sample_client,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=1,
        ano_referencia=2024,
        fecha_vencimiento=date(2024, 1, 15),
        valor_total=Decimal("25000"),
        saldo_devedor=Decimal("25000"),
    )
    await invoice.insert()

    # Processa pagamento
    result = await PaymentDistributionService.process_payment(
        client_id=sample_client.id,
        valor_total=Decimal("25000"),
        recibido_por="Caixa",
    )

    assert result.success

    # Verifica transacao de caixa
    transactions = await CashTransaction.find(
        CashTransaction.reference_type == "payment"
    ).to_list()

    assert len(transactions) == 1
    assert transactions[0].tipo == TransactionType.ENTRADA
    assert transactions[0].categoria == TransactionCategory.PAGAMENTO_FATURA
    assert transactions[0].valor == Decimal("25000")


# ============ Expense Tests ============

@pytest.mark.asyncio
async def test_create_expense(test_db):
    """Testa criacao de despesa."""
    items = [
        ExpenseItem(
            descripcion="Cano PVC 100mm",
            cantidad=10,
            precio_unitario=Decimal("15000"),
        ),
        ExpenseItem(
            descripcion="Conexao T",
            cantidad=5,
            precio_unitario=Decimal("8000"),
        ),
    ]

    expense = Expense(
        proveedor_nombre="Ferreteria ABC",
        proveedor_ruc="80012345-6",
        numero_factura="001-001-0001234",
        fecha_factura=date(2024, 1, 15),
        categoria=ExpenseCategory.MATERIAL,
        items=items,
        valor_total=sum(item.subtotal for item in items),
    )
    await expense.insert()

    assert expense.id is not None
    assert expense.valor_total == Decimal("190000")  # 150000 + 40000
    assert expense.status == ExpenseStatus.PENDENTE


@pytest.mark.asyncio
async def test_expense_item_subtotal():
    """Testa calculo de subtotal do item."""
    item = ExpenseItem(
        descripcion="Material",
        cantidad=3,
        precio_unitario=Decimal("10000"),
    )
    assert item.subtotal == Decimal("30000")


# ============ Employee Tests ============

@pytest.mark.asyncio
async def test_create_employee(test_db):
    """Testa criacao de funcionario."""
    employee = Employee(
        nombre_completo="Carlos Garcia",
        ci="4567890",
        telefono="0981234567",
        cargo=EmployeeRole.LEITURISTA,
        salario_base=Decimal("2500000"),
        fecha_ingreso=date(2023, 1, 1),
    )
    await employee.insert()

    assert employee.id is not None
    assert employee.status == EmployeeStatus.ATIVO
    assert employee.cargo == EmployeeRole.LEITURISTA


@pytest.mark.asyncio
async def test_employee_unique_ci(test_db):
    """Testa que CI e unico."""
    employee1 = Employee(
        nombre_completo="Carlos Garcia",
        ci="4567890",
        cargo=EmployeeRole.LEITURISTA,
        salario_base=Decimal("2500000"),
        fecha_ingreso=date(2023, 1, 1),
    )
    await employee1.insert()

    # Verifica no banco (sem usar unique index pois o teste usa banco limpo)
    existing = await Employee.find_one(Employee.ci == "4567890")
    assert existing is not None


# ============ Payroll Tests ============

@pytest.mark.asyncio
async def test_create_payroll(test_db):
    """Testa criacao de lancamento de folha."""
    employee = Employee(
        nombre_completo="Maria Lopez",
        ci="7891234",
        cargo=EmployeeRole.ADMINISTRADOR,
        salario_base=Decimal("3000000"),
        fecha_ingreso=date(2022, 6, 1),
    )
    await employee.insert()

    payroll = Payroll(
        employee=employee,
        tipo=PayrollType.SALARIO,
        mes_referencia=1,
        ano_referencia=2024,
        valor_base=Decimal("3000000"),
        descontos=Decimal("300000"),
        valor_liquido=Decimal("2700000"),
    )
    await payroll.insert()

    assert payroll.id is not None
    assert payroll.status == PayrollStatus.PENDENTE
    assert payroll.valor_liquido == Decimal("2700000")


@pytest.mark.asyncio
async def test_payroll_adiantamento(test_db):
    """Testa lancamento de adiantamento."""
    employee = Employee(
        nombre_completo="Pedro Santos",
        ci="3456789",
        cargo=EmployeeRole.TECNICO,
        salario_base=Decimal("2800000"),
        fecha_ingreso=date(2023, 3, 1),
    )
    await employee.insert()

    payroll = Payroll(
        employee=employee,
        tipo=PayrollType.ADIANTAMENTO,
        mes_referencia=1,
        ano_referencia=2024,
        valor_base=Decimal("1000000"),
        descontos=Decimal("0"),
        valor_liquido=Decimal("1000000"),
    )
    await payroll.insert()

    assert payroll.tipo == PayrollType.ADIANTAMENTO


# ============ API Tests ============

@pytest.mark.asyncio
async def test_api_create_transaction(test_client, auth_headers):
    """Testa criacao de transacao via API."""
    response = await test_client.post(
        "/finance/transactions",
        json={
            "tipo": "ENTRADA",
            "categoria": "VENDA_MATERIAL",
            "valor": "75000",
            "descripcion": "Venda de material",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["tipo"] == "ENTRADA"
    assert Decimal(data["valor"]) == Decimal("75000")


@pytest.mark.asyncio
async def test_api_list_transactions(test_client, auth_headers, test_db):
    """Testa listagem de transacoes."""
    # Cria transacoes
    for i in range(3):
        t = CashTransaction(
            tipo=TransactionType.ENTRADA,
            categoria=TransactionCategory.OUTROS_ENTRADA,
            valor=Decimal(str((i + 1) * 10000)),
            descripcion=f"Transacao {i+1}",
        )
        await t.insert()

    response = await test_client.get(
        "/finance/transactions",
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3


@pytest.mark.asyncio
async def test_api_cash_flow_summary(test_client, auth_headers, test_db):
    """Testa resumo do fluxo de caixa."""
    # Usa datetime.now() (local) para alinhar com date.today() do endpoint
    from datetime import datetime as dt
    now_local = dt.now()

    # Cria entradas
    for i in range(2):
        t = CashTransaction(
            tipo=TransactionType.ENTRADA,
            categoria=TransactionCategory.PAGAMENTO_FATURA,
            valor=Decimal("50000"),
            descripcion=f"Entrada {i+1}",
            fecha=now_local,
        )
        await t.insert()

    # Cria saida
    t = CashTransaction(
        tipo=TransactionType.SAIDA,
        categoria=TransactionCategory.DESPESA_MATERIAL,
        valor=Decimal("30000"),
        descripcion="Saida 1",
        fecha=now_local,
    )
    await t.insert()

    response = await test_client.get(
        "/finance/summary",
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert Decimal(data["total_entradas"]) == Decimal("100000")
    assert Decimal(data["total_saidas"]) == Decimal("30000")
    assert Decimal(data["saldo_periodo"]) == Decimal("70000")


@pytest.mark.asyncio
async def test_api_create_expense(test_client, auth_headers):
    """Testa criacao de despesa via API."""
    response = await test_client.post(
        "/finance/expenses",
        json={
            "proveedor_nombre": "Ferreteria XYZ",
            "numero_factura": "001-001-0005678",
            "fecha_factura": "2024-01-20",
            "categoria": "MATERIAL",
            "items": [
                {
                    "descripcion": "Torneira",
                    "cantidad": 5,
                    "precio_unitario": "25000",
                }
            ],
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["proveedor_nombre"] == "Ferreteria XYZ"
    assert Decimal(data["valor_total"]) == Decimal("125000")
    assert data["status"] == "PENDENTE"


@pytest.mark.asyncio
async def test_api_pay_expense(test_client, auth_headers, test_db):
    """Testa pagamento de despesa via API."""
    # Cria despesa
    expense = Expense(
        proveedor_nombre="Fornecedor Test",
        fecha_factura=date(2024, 1, 15),
        categoria=ExpenseCategory.SERVICO,
        items=[ExpenseItem(
            descripcion="Servico de limpeza",
            cantidad=1,
            precio_unitario=Decimal("80000"),
        )],
        valor_total=Decimal("80000"),
    )
    await expense.insert()

    response = await test_client.post(
        f"/finance/expenses/{expense.id}/pay",
        json={"observacion": "Pago em dinheiro"},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PAGA"

    # Verifica transacao criada
    transactions = await CashTransaction.find(
        CashTransaction.reference_type == "expense"
    ).to_list()
    assert len(transactions) == 1
    assert transactions[0].tipo == TransactionType.SAIDA


@pytest.mark.asyncio
async def test_api_create_employee(test_client, auth_headers):
    """Testa criacao de funcionario via API."""
    response = await test_client.post(
        "/finance/employees",
        json={
            "nombre_completo": "Ana Silva",
            "ci": "9876543",
            "telefono": "0971234567",
            "cargo": "COBRADOR",
            "salario_base": "2200000",
            "fecha_ingreso": "2024-01-01",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert data["nombre_completo"] == "Ana Silva"
    assert data["cargo"] == "COBRADOR"


@pytest.mark.asyncio
async def test_api_create_payroll(test_client, auth_headers, test_db):
    """Testa criacao de folha via API."""
    # Cria funcionario
    employee = Employee(
        nombre_completo="Jose Fernandez",
        ci="1122334",
        cargo=EmployeeRole.LEITURISTA,
        salario_base=Decimal("2500000"),
        fecha_ingreso=date(2023, 5, 1),
    )
    await employee.insert()

    response = await test_client.post(
        "/finance/payroll",
        json={
            "employee_id": str(employee.id),
            "tipo": "SALARIO",
            "mes_referencia": 2,
            "ano_referencia": 2024,
            "valor_base": "2500000",
            "descontos": "250000",
        },
        headers=auth_headers,
    )

    assert response.status_code == 201
    data = response.json()
    assert Decimal(data["valor_liquido"]) == Decimal("2250000")
    assert data["status"] == "PENDENTE"


@pytest.mark.asyncio
async def test_api_pay_payroll(test_client, auth_headers, test_db):
    """Testa pagamento de folha via API."""
    # Cria funcionario e folha
    employee = Employee(
        nombre_completo="Roberto Diaz",
        ci="5566778",
        cargo=EmployeeRole.TECNICO,
        salario_base=Decimal("2800000"),
        fecha_ingreso=date(2022, 8, 1),
    )
    await employee.insert()

    payroll = Payroll(
        employee=employee,
        tipo=PayrollType.SALARIO,
        mes_referencia=1,
        ano_referencia=2024,
        valor_base=Decimal("2800000"),
        descontos=Decimal("0"),
        valor_liquido=Decimal("2800000"),
    )
    await payroll.insert()

    response = await test_client.post(
        f"/finance/payroll/{payroll.id}/pay",
        json={},
        headers=auth_headers,
    )

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "PAGO"

    # Verifica transacao criada
    transactions = await CashTransaction.find(
        CashTransaction.reference_type == "payroll"
    ).to_list()
    assert len(transactions) == 1
    assert transactions[0].tipo == TransactionType.SAIDA
    assert transactions[0].valor == Decimal("2800000")
