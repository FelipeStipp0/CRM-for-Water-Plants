"""
Endpoints do Modulo Financeiro.

Inclui:
- Transacoes de caixa
- Despesas
- Funcionarios
- Folha de pagamento
"""

from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Annotated, List, Optional

from beanie import PydanticObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.models.user import User
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
    Payroll,
    PayrollStatus,
    PayrollType,
)
from app.routers.auth import get_current_active_user, require_scopes
from app.schemas.finance import (
    CashTransactionCreate,
    CashTransactionResponse,
    CashFlowSummary,
    CashFlowByCategory,
    ExpenseCreate,
    ExpenseResponse,
    ExpenseItemResponse,
    ExpensePayRequest,
    EmployeeCreate,
    EmployeeUpdate,
    EmployeeResponse,
    PayrollCreate,
    PayrollResponse,
    PayrollPayRequest,
)

router = APIRouter(dependencies=[Depends(require_scopes("finance"))])


# ============ Cash Transactions ============

def transaction_to_response(t: CashTransaction) -> CashTransactionResponse:
    """Converte modelo para schema."""
    return CashTransactionResponse(
        id=str(t.id),
        tipo=t.tipo,
        categoria=t.categoria,
        valor=t.valor,
        descripcion=t.descripcion,
        reference_id=str(t.reference_id) if t.reference_id else None,
        reference_type=t.reference_type,
        fecha=t.fecha,
        registrado_por=t.registrado_por,
    )


@router.post("/transactions", response_model=CashTransactionResponse, status_code=status.HTTP_201_CREATED)
async def create_transaction(
    data: CashTransactionCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cria uma transacao manual de caixa."""
    transaction = CashTransaction(
        tipo=data.tipo,
        categoria=data.categoria,
        valor=data.valor,
        descripcion=data.descripcion,
        registrado_por=current_user.full_name,
    )
    await transaction.insert()
    return transaction_to_response(transaction)


@router.get("/transactions", response_model=List[CashTransactionResponse])
async def list_transactions(
    current_user: Annotated[User, Depends(get_current_active_user)],
    tipo: Optional[TransactionType] = None,
    categoria: Optional[TransactionCategory] = None,
    fecha_inicio: Optional[date] = None,
    fecha_fin: Optional[date] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Lista transacoes com filtros."""
    filters = {}

    if tipo:
        filters["tipo"] = tipo.value
    if categoria:
        filters["categoria"] = categoria.value
    if fecha_inicio or fecha_fin:
        fecha_filter = {}
        if fecha_inicio:
            fecha_filter["$gte"] = datetime.combine(fecha_inicio, datetime.min.time())
        if fecha_fin:
            fecha_filter["$lte"] = datetime.combine(fecha_fin, datetime.max.time())
        if fecha_filter:
            filters["fecha"] = fecha_filter

    query = CashTransaction.find(filters) if filters else CashTransaction.find()
    transactions = await query.skip(skip).limit(limit).sort("-fecha").to_list()

    return [transaction_to_response(t) for t in transactions]


@router.get("/summary", response_model=CashFlowSummary)
async def get_cash_flow_summary(
    current_user: Annotated[User, Depends(get_current_active_user)],
    fecha_inicio: Optional[date] = None,
    fecha_fin: Optional[date] = None,
):
    """Retorna resumo do fluxo de caixa do periodo."""
    if not fecha_inicio:
        fecha_inicio = date.today().replace(day=1)
    if not fecha_fin:
        fecha_fin = date.today()

    fecha_filter = {
        "$gte": datetime.combine(fecha_inicio, datetime.min.time()),
        "$lte": datetime.combine(fecha_fin, datetime.max.time()),
    }

    # Entradas
    entradas = await CashTransaction.find(
        {"tipo": TransactionType.ENTRADA.value, "fecha": fecha_filter}
    ).to_list()
    total_entradas = sum(t.valor for t in entradas)

    # Saidas
    saidas = await CashTransaction.find(
        {"tipo": TransactionType.SAIDA.value, "fecha": fecha_filter}
    ).to_list()
    total_saidas = sum(t.valor for t in saidas)

    return CashFlowSummary(
        periodo_inicio=fecha_inicio,
        periodo_fim=fecha_fin,
        total_entradas=total_entradas,
        total_saidas=total_saidas,
        saldo_periodo=total_entradas - total_saidas,
        transacoes_count=len(entradas) + len(saidas),
    )


@router.get("/by-category", response_model=List[CashFlowByCategory])
async def get_cash_flow_by_category(
    current_user: Annotated[User, Depends(get_current_active_user)],
    fecha_inicio: Optional[date] = None,
    fecha_fin: Optional[date] = None,
):
    """Retorna fluxo agrupado por categoria."""
    if not fecha_inicio:
        fecha_inicio = date.today().replace(day=1)
    if not fecha_fin:
        fecha_fin = date.today()

    pipeline = [
        {
            "$match": {
                "fecha": {
                    "$gte": datetime.combine(fecha_inicio, datetime.min.time()),
                    "$lte": datetime.combine(fecha_fin, datetime.max.time()),
                }
            }
        },
        {
            "$group": {
                "_id": "$categoria",
                "total": {"$sum": "$valor"},
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"total": -1}},
    ]

    cursor = CashTransaction.get_pymongo_collection().aggregate(pipeline)
    results = await cursor.to_list(length=50)

    return [
        CashFlowByCategory(
            categoria=TransactionCategory(r["_id"]),
            total=Decimal(str(r["total"])),
            count=r["count"],
        )
        for r in results
    ]


# ============ Expenses ============

def expense_to_response(e: Expense) -> ExpenseResponse:
    """Converte modelo para schema."""
    items = [
        ExpenseItemResponse(
            descripcion=item.descripcion,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
            subtotal=item.subtotal,
        )
        for item in e.items
    ]

    return ExpenseResponse(
        id=str(e.id),
        proveedor_nombre=e.proveedor_nombre,
        proveedor_ruc=e.proveedor_ruc,
        numero_factura=e.numero_factura,
        fecha_factura=e.fecha_factura,
        fecha_vencimiento=e.fecha_vencimiento,
        categoria=e.categoria,
        status=e.status,
        items=items,
        valor_total=e.valor_total,
        fecha_pago=e.fecha_pago,
        observacion=e.observacion,
        created_at=e.created_at,
    )


@router.post("/expenses", response_model=ExpenseResponse, status_code=status.HTTP_201_CREATED)
async def create_expense(
    data: ExpenseCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cria uma despesa."""
    items = [
        ExpenseItem(
            descripcion=item.descripcion,
            cantidad=item.cantidad,
            precio_unitario=item.precio_unitario,
        )
        for item in data.items
    ]

    valor_total = sum(item.subtotal for item in items)

    expense = Expense(
        proveedor_nombre=data.proveedor_nombre,
        proveedor_ruc=data.proveedor_ruc,
        proveedor_telefono=data.proveedor_telefono,
        numero_factura=data.numero_factura,
        fecha_factura=data.fecha_factura,
        fecha_vencimiento=data.fecha_vencimiento,
        categoria=data.categoria,
        items=items,
        valor_total=valor_total,
        observacion=data.observacion,
    )
    await expense.insert()

    return expense_to_response(expense)


@router.get("/expenses", response_model=List[ExpenseResponse])
async def list_expenses(
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Optional[ExpenseStatus] = Query(None, alias="status"),
    categoria: Optional[ExpenseCategory] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Lista despesas com filtros."""
    filters = {}

    if status_filter:
        filters["status"] = status_filter.value
    if categoria:
        filters["categoria"] = categoria.value

    query = Expense.find(filters) if filters else Expense.find()
    expenses = await query.skip(skip).limit(limit).sort("-fecha_factura").to_list()

    return [expense_to_response(e) for e in expenses]


@router.get("/expenses/pending", response_model=List[ExpenseResponse])
async def list_pending_expenses(
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Lista despesas pendentes ordenadas por vencimento."""
    expenses = await Expense.find(
        Expense.status == ExpenseStatus.PENDENTE
    ).sort("fecha_vencimiento").limit(200).to_list()

    return [expense_to_response(e) for e in expenses]


@router.get("/expenses/{expense_id}", response_model=ExpenseResponse)
async def get_expense(
    expense_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna uma despesa pelo ID."""
    try:
        expense = await Expense.get(PydanticObjectId(expense_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Despesa nao encontrada")

    if not expense:
        raise HTTPException(status_code=404, detail="Despesa nao encontrada")

    return expense_to_response(expense)


@router.post("/expenses/{expense_id}/pay", response_model=ExpenseResponse)
async def pay_expense(
    expense_id: str,
    data: ExpensePayRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Registra pagamento de uma despesa."""
    try:
        expense = await Expense.get(PydanticObjectId(expense_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Despesa nao encontrada")

    if not expense:
        raise HTTPException(status_code=404, detail="Despesa nao encontrada")

    if expense.status != ExpenseStatus.PENDENTE:
        raise HTTPException(status_code=400, detail="Despesa nao esta pendente")

    # Atualiza despesa
    now = datetime.utcnow()
    await expense.update({
        "$set": {
            "status": ExpenseStatus.PAGA,
            "fecha_pago": now,
            "observacion": data.observacion or expense.observacion,
            "updated_at": now,
        }
    })
    await expense.sync()

    # Mapeia categoria de despesa para categoria de transacao
    category_map = {
        ExpenseCategory.MATERIAL: TransactionCategory.DESPESA_MATERIAL,
        ExpenseCategory.SERVICO: TransactionCategory.DESPESA_SERVICO,
        ExpenseCategory.MANUTENCAO: TransactionCategory.DESPESA_MANUTENCAO,
        ExpenseCategory.OUTROS: TransactionCategory.OUTROS_SAIDA,
    }

    # Cria transacao de saida
    transaction = CashTransaction(
        tipo=TransactionType.SAIDA,
        categoria=category_map.get(expense.categoria, TransactionCategory.OUTROS_SAIDA),
        valor=expense.valor_total,
        descripcion=f"Pagamento: {expense.proveedor_nombre} - {expense.numero_factura or 'S/N'}",
        reference_id=expense.id,
        reference_type="expense",
        registrado_por=current_user.full_name,
    )
    await transaction.insert()

    return expense_to_response(expense)


# ============ Employees ============

def employee_to_response(e: Employee) -> EmployeeResponse:
    """Converte modelo para schema."""
    return EmployeeResponse(
        id=str(e.id),
        nombre_completo=e.nombre_completo,
        ci=e.ci,
        telefono=e.telefono,
        direccion=e.direccion,
        cargo=e.cargo,
        salario_base=e.salario_base,
        fecha_ingreso=e.fecha_ingreso,
        status=e.status,
        created_at=e.created_at,
    )


@router.post("/employees", response_model=EmployeeResponse, status_code=status.HTTP_201_CREATED)
async def create_employee(
    data: EmployeeCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cria um funcionario."""
    # Verifica CI duplicado
    existing = await Employee.find_one(Employee.ci == data.ci)
    if existing:
        raise HTTPException(status_code=400, detail="CI ja cadastrado")

    employee = Employee(**data.model_dump())
    await employee.insert()

    return employee_to_response(employee)


@router.get("/employees", response_model=List[EmployeeResponse])
async def list_employees(
    current_user: Annotated[User, Depends(get_current_active_user)],
    status_filter: Optional[EmployeeStatus] = Query(None, alias="status"),
):
    """Lista funcionarios."""
    if status_filter:
        employees = await Employee.find(Employee.status == status_filter).limit(200).to_list()
    else:
        employees = await Employee.find().limit(200).to_list()

    return [employee_to_response(e) for e in employees]


@router.get("/employees/{employee_id}", response_model=EmployeeResponse)
async def get_employee(
    employee_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Retorna um funcionario pelo ID."""
    try:
        employee = await Employee.get(PydanticObjectId(employee_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")

    if not employee:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")

    return employee_to_response(employee)


@router.patch("/employees/{employee_id}", response_model=EmployeeResponse)
async def update_employee(
    employee_id: str,
    data: EmployeeUpdate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Atualiza um funcionario."""
    try:
        employee = await Employee.get(PydanticObjectId(employee_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")

    if not employee:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")

    update_data = data.model_dump(exclude_unset=True)
    if update_data:
        update_data["updated_at"] = datetime.utcnow()
        await employee.update({"$set": update_data})
        await employee.sync()

    return employee_to_response(employee)


# ============ Payroll ============

async def payroll_to_response(p: Payroll) -> PayrollResponse:
    """Converte modelo para schema."""
    if hasattr(p.employee, 'fetch'):
        employee = await p.employee.fetch()
    else:
        employee = p.employee

    return PayrollResponse(
        id=str(p.id),
        employee_id=str(employee.id),
        employee_name=employee.nombre_completo,
        tipo=p.tipo,
        status=p.status,
        mes_referencia=p.mes_referencia,
        ano_referencia=p.ano_referencia,
        valor_base=p.valor_base,
        descontos=p.descontos,
        valor_liquido=p.valor_liquido,
        fecha_pago=p.fecha_pago,
        observacion=p.observacion,
        created_at=p.created_at,
    )


@router.post("/payroll", response_model=PayrollResponse, status_code=status.HTTP_201_CREATED)
async def create_payroll(
    data: PayrollCreate,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cria um lancamento de folha."""
    try:
        employee = await Employee.get(PydanticObjectId(data.employee_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")

    if not employee:
        raise HTTPException(status_code=404, detail="Funcionario nao encontrado")

    if employee.status != EmployeeStatus.ATIVO:
        raise HTTPException(status_code=400, detail="Funcionario nao esta ativo")

    # Verifica duplicata (mesmo tipo, mesmo periodo)
    existing = await Payroll.find_one(
        {"employee.$id": employee.id},
        Payroll.tipo == data.tipo,
        Payroll.mes_referencia == data.mes_referencia,
        Payroll.ano_referencia == data.ano_referencia,
        Payroll.status != PayrollStatus.CANCELADO,
    )
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"Ja existe lancamento de {data.tipo.value} para {data.mes_referencia}/{data.ano_referencia}"
        )

    valor_liquido = data.valor_base - data.descontos

    payroll = Payroll(
        employee=employee,
        tipo=data.tipo,
        mes_referencia=data.mes_referencia,
        ano_referencia=data.ano_referencia,
        valor_base=data.valor_base,
        descontos=data.descontos,
        valor_liquido=valor_liquido,
        observacion=data.observacion,
    )
    await payroll.insert()

    return await payroll_to_response(payroll)


@router.get("/payroll", response_model=List[PayrollResponse])
async def list_payroll(
    current_user: Annotated[User, Depends(get_current_active_user)],
    employee_id: Optional[str] = None,
    status_filter: Optional[PayrollStatus] = Query(None, alias="status"),
    mes: Optional[int] = Query(None, ge=1, le=12),
    ano: Optional[int] = Query(None, ge=2000, le=2100),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    """Lista lancamentos de folha."""
    filters = {}

    if employee_id:
        try:
            filters["employee.$id"] = PydanticObjectId(employee_id)
        except Exception:
            raise HTTPException(status_code=400, detail="employee_id invalido")
    if status_filter:
        filters["status"] = status_filter.value
    if mes:
        filters["mes_referencia"] = mes
    if ano:
        filters["ano_referencia"] = ano

    query = Payroll.find(filters) if filters else Payroll.find()
    payrolls = await query.skip(skip).limit(limit).sort("-created_at").to_list()

    if not payrolls:
        return []

    # Batch fetch: busca todos os funcionarios de uma vez
    emp_ids = set()
    for p in payrolls:
        eid = p.employee.ref.id if hasattr(p.employee, 'ref') else p.employee.id
        emp_ids.add(eid)

    employees_list = await Employee.find({"_id": {"$in": list(emp_ids)}}).to_list()
    employees_map = {e.id: e for e in employees_list}

    results = []
    for p in payrolls:
        eid = p.employee.ref.id if hasattr(p.employee, 'ref') else p.employee.id
        employee = employees_map.get(eid)
        if employee:
            results.append(PayrollResponse(
                id=str(p.id),
                employee_id=str(employee.id),
                employee_name=employee.nombre_completo,
                tipo=p.tipo,
                status=p.status,
                mes_referencia=p.mes_referencia,
                ano_referencia=p.ano_referencia,
                valor_base=p.valor_base,
                descontos=p.descontos,
                valor_liquido=p.valor_liquido,
                fecha_pago=p.fecha_pago,
                observacion=p.observacion,
                created_at=p.created_at,
            ))

    return results


@router.post("/payroll/{payroll_id}/pay", response_model=PayrollResponse)
async def pay_payroll(
    payroll_id: str,
    data: PayrollPayRequest,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Registra pagamento de folha."""
    try:
        payroll = await Payroll.get(PydanticObjectId(payroll_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Lancamento nao encontrado")

    if not payroll:
        raise HTTPException(status_code=404, detail="Lancamento nao encontrado")

    if payroll.status != PayrollStatus.PENDENTE:
        raise HTTPException(status_code=400, detail="Lancamento nao esta pendente")

    # Busca funcionario
    if hasattr(payroll.employee, 'fetch'):
        employee = await payroll.employee.fetch()
    else:
        employee = payroll.employee

    # Atualiza folha
    now = datetime.utcnow()
    await payroll.update({
        "$set": {
            "status": PayrollStatus.PAGO,
            "fecha_pago": now,
            "observacion": data.observacion or payroll.observacion,
        }
    })
    await payroll.sync()

    # Mapeia tipo para categoria
    category_map = {
        PayrollType.SALARIO: TransactionCategory.SALARIO,
        PayrollType.ADIANTAMENTO: TransactionCategory.ADIANTAMENTO,
        PayrollType.BONUS: TransactionCategory.SALARIO,
        PayrollType.DESCONTO: TransactionCategory.SALARIO,
    }

    # Cria transacao de saida
    transaction = CashTransaction(
        tipo=TransactionType.SAIDA,
        categoria=category_map.get(payroll.tipo, TransactionCategory.SALARIO),
        valor=payroll.valor_liquido,
        descripcion=f"{payroll.tipo.value}: {employee.nombre_completo} ({payroll.mes_referencia}/{payroll.ano_referencia})",
        reference_id=payroll.id,
        reference_type="payroll",
        registrado_por=current_user.full_name,
    )
    await transaction.insert()

    return await payroll_to_response(payroll)


@router.post("/payroll/{payroll_id}/cancel", response_model=PayrollResponse)
async def cancel_payroll(
    payroll_id: str,
    current_user: Annotated[User, Depends(get_current_active_user)],
):
    """Cancela um lancamento de folha pendente."""
    try:
        payroll = await Payroll.get(PydanticObjectId(payroll_id))
    except Exception:
        raise HTTPException(status_code=404, detail="Lancamento nao encontrado")

    if not payroll:
        raise HTTPException(status_code=404, detail="Lancamento nao encontrado")

    if payroll.status != PayrollStatus.PENDENTE:
        raise HTTPException(status_code=400, detail="Apenas lancamentos pendentes podem ser cancelados")

    await payroll.update({"$set": {"status": PayrollStatus.CANCELADO}})
    await payroll.sync()

    return await payroll_to_response(payroll)
