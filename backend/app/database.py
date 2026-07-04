"""
Configuracao e inicializacao do banco de dados MongoDB.

Arquitetura multi-tenant: um database por org, cada um com sua propria
connection string criptografada armazenada no wmapp_admin.

  wmapp_admin       — database do superadmin (Organizations, auditoria)
  wmapp_{slug}      — database de cada org (conectado com credencial exclusiva)

Clientes Motor sao cacheados por org — um cliente por slug por processo.
init_beanie e chamado UMA VEZ por org (lazy, cacheado em _initialized_orgs).
"""

from beanie import init_beanie
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from app.config import get_settings

# Cliente para o wmapp_admin (URL global — só o admin-api e o backend admin usam)
_admin_client: AsyncIOMotorClient | None = None
_admin_initialized: bool = False

# Cache de clientes Motor por org — chave: slug
_org_clients: dict[str, AsyncIOMotorClient] = {}

# Cache de orgs já inicializadas com Beanie
_initialized_orgs: set[str] = set()


def _get_org_document_models() -> list:
    from app.models.user import User
    from app.models.client import Client
    from app.models.reading import Reading
    from app.models.invoice import Invoice, Counter
    from app.models.payment import Payment
    from app.models.settings import SystemSettings
    from app.models.finance import CashTransaction, Expense, Employee, Payroll
    from app.models.sponsor import SponsorDebt, SponsorInvoice
    from app.models.cutoff import CutoffNotice
    from app.models.sifen import (
        SifenEmission, SifenSessionLock, SifenCredential, SifenCoordinator,
    )
    return [
        User, Client, Reading, Invoice, Counter, Payment,
        SystemSettings, CashTransaction, Expense, Employee,
        Payroll, SponsorDebt, SponsorInvoice, CutoffNotice,
        SifenEmission, SifenSessionLock, SifenCredential, SifenCoordinator,
    ]


def _get_admin_document_models() -> list:
    from app.models.organization import Organization
    return [Organization]


async def init_db():
    """
    Inicializa o cliente MongoDB admin no startup da aplicacao.
    Conecta ao wmapp_admin usando a URL global (que so o backend conhece).
    """
    global _admin_client, _admin_initialized
    settings = get_settings()
    _admin_client = AsyncIOMotorClient(settings.mongodb_url)

    await init_beanie(
        database=_admin_client["wmapp_admin"],
        document_models=_get_admin_document_models(),
    )
    _admin_initialized = True


async def _get_org_connection_string(slug: str) -> str:
    """
    Busca e decripta a connection string da org no wmapp_admin.
    Lanca RuntimeError se a org nao existir ou nao tiver connection_string.
    """
    from app.models.organization import Organization
    from app.utils.crypto import decrypt_connection_string

    settings = get_settings()

    if not settings.encryption_key:
        # Fallback para desenvolvimento local sem ENCRYPTION_KEY configurada:
        # usa a URL global apontando para o database da org
        return f"{settings.mongodb_url}"

    org = await Organization.find_one(Organization.slug == slug)
    if org is None:
        raise RuntimeError(f"Organizacao '{slug}' nao encontrada no wmapp_admin.")
    if not org.connection_string:
        raise RuntimeError(f"Organizacao '{slug}' nao tem connection_string configurada.")
    if not org.is_active:
        raise RuntimeError(f"Organizacao '{slug}' esta inativa.")

    return decrypt_connection_string(org.connection_string, settings.encryption_key)


async def ensure_org_db(slug: str) -> AsyncIOMotorDatabase:
    """
    Garante que o Beanie esta inicializado para a org.
    Idempotente — so inicializa uma vez por slug por processo.
    Usa a connection string exclusiva da org (credencial isolada).
    """
    if _admin_client is None:
        raise RuntimeError("Database admin nao inicializado. Chame init_db() primeiro.")

    if slug not in _initialized_orgs:
        conn_str = await _get_org_connection_string(slug)

        # Cria (ou reutiliza) cliente Motor para esta org
        if slug not in _org_clients:
            _org_clients[slug] = AsyncIOMotorClient(conn_str)

        db = _org_clients[slug][f"wmapp_{slug}"]
        await init_beanie(
            database=db,
            document_models=_get_org_document_models(),
        )
        _initialized_orgs.add(slug)

    return _org_clients[slug][f"wmapp_{slug}"]


async def close_db():
    """Fecha todas as conexoes com o MongoDB."""
    global _admin_client, _admin_initialized

    for client in _org_clients.values():
        client.close()
    _org_clients.clear()
    _initialized_orgs.clear()

    if _admin_client:
        _admin_client.close()
        _admin_client = None
    _admin_initialized = False


def get_admin_db() -> AsyncIOMotorDatabase:
    """Retorna o database do admin (wmapp_admin)."""
    if _admin_client is None:
        raise RuntimeError("Database nao inicializado. Chame init_db() primeiro.")
    return _admin_client["wmapp_admin"]


def get_org_db(slug: str) -> AsyncIOMotorDatabase:
    """
    Retorna o database Motor de uma org pelo slug.
    Requer que ensure_org_db(slug) ja tenha sido chamado antes.
    """
    if slug not in _org_clients:
        raise RuntimeError(f"Org '{slug}' nao inicializada. Chame ensure_org_db() primeiro.")
    return _org_clients[slug][f"wmapp_{slug}"]


def get_admin_client() -> AsyncIOMotorClient:
    if _admin_client is None:
        raise RuntimeError("Database nao inicializado.")
    return _admin_client
