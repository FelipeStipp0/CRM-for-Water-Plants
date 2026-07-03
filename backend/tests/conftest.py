"""
Configuracao de fixtures para testes.
"""

from datetime import date
from decimal import Decimal
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from beanie import init_beanie
from httpx import AsyncClient, ASGITransport
from motor.motor_asyncio import AsyncIOMotorClient

from app.models.user import User
from app.models.client import Client, ClientCategory, ClientStatus
from app.models.reading import Reading
from app.models.invoice import Invoice, InvoiceStatus, InvoiceType, Counter
from app.models.payment import Payment
from app.models.settings import SystemSettings
from app.models.finance import CashTransaction, Expense, Employee, Payroll
from app.models.sponsor import SponsorDebt, SponsorInvoice
from app.models.cutoff import CutoffNotice
from app.utils.security import get_password_hash, create_access_token


@pytest_asyncio.fixture
async def test_db():
    """
    Configura banco de dados de teste.
    Usa um banco separado e limpa apos cada teste.
    """
    mongo_client = AsyncIOMotorClient("mongodb://127.0.0.1:27017")
    database = mongo_client["wmapp_test"]

    await init_beanie(
        database=database,
        document_models=[
            User,
            Client,
            Reading,
            Invoice,
            Counter,
            Payment,
            SystemSettings,
            CashTransaction,
            Expense,
            Employee,
            Payroll,
            SponsorDebt,
            SponsorInvoice,
            CutoffNotice,
        ]
    )

    yield database

    # Limpa colecoes apos o teste
    for collection_name in await database.list_collection_names():
        await database[collection_name].drop()

    mongo_client.close()


@pytest_asyncio.fixture
async def test_client(test_db) -> AsyncGenerator[AsyncClient, None]:
    """Cliente HTTP para testes de API."""
    # Importa app aqui para evitar inicializacao prematura
    from app.main import create_app

    # Cria app sem lifespan para testes (DB ja inicializado)
    from fastapi import FastAPI
    from fastapi.middleware.cors import CORSMiddleware

    test_app = FastAPI()
    test_app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from app.routers import auth, clients, readings, invoices, payments, settings as settings_router, finance, cutoff as cutoff_router
    test_app.include_router(auth.router, prefix="/auth", tags=["Autenticacao"])
    test_app.include_router(clients.router, prefix="/clients", tags=["Clientes"])
    test_app.include_router(readings.router, prefix="/readings", tags=["Leituras"])
    test_app.include_router(invoices.router, prefix="/invoices", tags=["Faturas"])
    test_app.include_router(payments.router, prefix="/payments", tags=["Pagamentos"])
    test_app.include_router(settings_router.router, prefix="/settings", tags=["Configuracoes"])
    test_app.include_router(finance.router, prefix="/finance", tags=["Financeiro"])
    test_app.include_router(cutoff_router.router, prefix="/cutoff", tags=["Corte"])
    test_app.include_router(cutoff_router.qr_router, prefix="/cutoff", tags=["Corte QR"])

    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest_asyncio.fixture
async def test_user(test_db) -> User:
    """Cria usuario de teste."""
    user = User(
        username="testuser",
        email="test@example.com",
        hashed_password=get_password_hash("testpass123"),
        full_name="Test User",
        is_superuser=True,
        must_change_password=False,  # Desativa para testes
        scopes=["*"],
    )
    await user.insert()
    return user


@pytest_asyncio.fixture
async def auth_headers(test_user: User) -> dict:
    """Headers de autenticacao para testes."""
    token = create_access_token(data={"sub": test_user.username})
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def test_settings(test_db) -> SystemSettings:
    """Configuracoes de teste."""
    settings = SystemSettings(
        nombre_junta="Junta Test",
        tarifa_base=Decimal("25000"),  # Tarifa unica global
        consumo_minimo=15,
        valor_excedente_m3=Decimal("1500"),
        subsidio_porcentagem_padrao=50,
        dias_vencimiento=15,
    )
    await settings.insert()
    return settings


@pytest_asyncio.fixture
async def sample_client(test_db) -> Client:
    """Cliente de exemplo para testes."""
    client = Client(
        nombre_completo="Juan Perez",
        ci_ruc="1234567",
        telefono="021123456",
        celular="0981123456",
        direccion="Calle Principal 123",
        manzana="A",
        lote="1",
        numero_medidor="MED-001",
        categoria=ClientCategory.RESIDENCIAL,
        status=ClientStatus.ATIVO,
    )
    await client.insert()
    return client


@pytest_asyncio.fixture
async def sample_reading(test_db, sample_client: Client) -> Reading:
    """Leitura de exemplo."""
    reading = Reading(
        client=sample_client,
        valor_leitura=100,
        mes_referencia=1,
        ano_referencia=2024,
        consumo_calculado=20,
    )
    await reading.insert()
    return reading


@pytest_asyncio.fixture
async def sample_invoice(test_db, sample_client: Client) -> Invoice:
    """Fatura de exemplo."""
    invoice = Invoice(
        client=sample_client,
        tipo=InvoiceType.CONSUMO,
        status=InvoiceStatus.PENDENTE,
        mes_referencia=1,
        ano_referencia=2024,
        fecha_vencimiento=date(2024, 1, 15),
        leitura_anterior=80,
        leitura_actual=100,
        consumo=20,
        tarifa_base=Decimal("25000"),
        excedente=Decimal("7500"),
        valor_total=Decimal("32500"),
        saldo_devedor=Decimal("32500"),
    )
    await invoice.insert()
    return invoice


@pytest_asyncio.fixture
async def multiple_invoices(test_db, sample_client: Client) -> list[Invoice]:
    """Multiplas faturas pendentes para teste de distribuicao."""
    invoices = []

    for i, (mes, valor) in enumerate([
        (1, Decimal("25000")),
        (2, Decimal("30000")),
        (3, Decimal("28000")),
    ], start=1):
        invoice = Invoice(
            client=sample_client,
            tipo=InvoiceType.CONSUMO,
            status=InvoiceStatus.PENDENTE,
            mes_referencia=mes,
            ano_referencia=2024,
            fecha_vencimiento=date(2024, mes, 15),
            consumo=15 + i,
            tarifa_base=Decimal("25000"),
            excedente=valor - Decimal("25000"),
            valor_total=valor,
            saldo_devedor=valor,
        )
        await invoice.insert()
        invoices.append(invoice)

    return invoices
