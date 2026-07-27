"""
Seed de ambiente de teste: cria orgs, usuários de todos os perfis e (opcional)
popula uma delas com dados reais exportados do Zoho.

Cria duas orgs:
  - `demo`  — Junta Demo Santa Fe: clientes, faturas e pagamentos dos CSVs.
  - `nueva` — Junta Nueva: só os usuários (para testar uma junta recém-criada).

Os usuários são os mesmos nas duas, um por perfil de escopo (ver PERFILES).
Todos entram com `must_change_password=False` — exceto `nuevo`, que existe
justamente para testar o fluxo de primeiro acesso.

Uso:
    cd backend
    python -m scripts.seed_demo                      # cria/atualiza tudo
    python -m scripts.seed_demo --reset              # apaga os dados das orgs antes
    python -m scripts.seed_demo --sin-datos          # só orgs + usuários
    python -m scripts.seed_demo --csv-dir "C:/ruta"  # outra pasta de CSVs

Os CSVs esperados na pasta (export do Zoho):
    Contactos.csv · Factura.csv · Pagos hasta julio.csv
"""

import argparse
import asyncio
import csv
import os
import re
import sys
from datetime import datetime
from decimal import Decimal, InvalidOperation

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from motor.motor_asyncio import AsyncIOMotorClient  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.utils.crypto import encrypt  # noqa: E402
from app.utils.security import get_password_hash  # noqa: E402


CSV_DIR_PADRAO = r"C:\Users\stipp\Downloads\faturas junta\julho"

ORGS = [
    {"slug": "demo",  "name": "Junta Demo Santa Fe", "email": "demo@saneo.test",  "datos": True},
    {"slug": "nueva", "name": "Junta Nueva",         "email": "nueva@saneo.test", "datos": False},
]

# Um usuário por perfil de acesso. A senha vai em claro aqui de propósito:
# é ambiente de teste e o dono precisa delas para entrar.
PERFILES = [
    {"username": "master",     "password": "Master#2026",   "role": "master",
     "full_name": "María Elena Ortiz",   "position": "Presidenta",
     "scopes": ["*"]},
    {"username": "cajero",     "password": "Cajero#2026",   "role": "operator",
     "full_name": "Rosa Giménez",        "position": "Cajera",
     "scopes": ["caja", "clients", "payments", "sifen"]},
    {"username": "tesorero",   "password": "Tesorero#2026", "role": "operator",
     "full_name": "Jorge Cáceres",       "position": "Tesorero",
     "scopes": ["finance", "sponsors", "payments", "invoices", "clients"]},
    {"username": "secretaria", "password": "Secre#2026",    "role": "operator",
     "full_name": "Ana Riveros",         "position": "Secretaria",
     "scopes": ["clients", "invoices", "readings", "payments"]},
    {"username": "lecturista", "password": "Lector#2026",   "role": "operator",
     "full_name": "Carlos Benítez",      "position": "Lecturista",
     "scopes": ["readings", "clients"]},
    {"username": "tecnico",    "password": "Tecnico#2026",  "role": "operator",
     "full_name": "Pedro Villalba",      "position": "Técnico de campo",
     "scopes": ["cutoff", "clients"]},
    {"username": "operador",   "password": "Operador#2026", "role": "operator",
     "full_name": "Lucía Franco",        "position": "Operadora",
     "scopes": ["clients", "readings", "invoices", "payments", "cutoff",
                "finance", "sponsors"]},
    # Primeiro acesso: entra e o sistema deve exigir troca de senha.
    {"username": "nuevo",      "password": "Nuevo#2026",    "role": "operator",
     "full_name": "Usuario Nuevo",       "position": "En capacitación",
     "scopes": ["clients", "payments"], "must_change_password": True},
]


# --------------------------------------------------------------------- infra

async def criar_org(admin_db, org: dict, mongodb_url: str, encryption_key: str) -> None:
    """Registra a org no wmapp_admin (connection string cifrada, como o admin-api)."""
    doc = {
        "name": org["name"],
        "slug": org["slug"],
        "masterEmail": org["email"],
        "isActive": True,
        "connectionString": encrypt(mongodb_url, encryption_key) if encryption_key else None,
        "updatedAt": datetime.utcnow(),
    }
    existente = await admin_db["organizations"].find_one({"slug": org["slug"]})
    if existente:
        await admin_db["organizations"].update_one({"slug": org["slug"]}, {"$set": doc})
        print(f"  org '{org['slug']}' atualizada")
    else:
        doc["createdAt"] = datetime.utcnow()
        await admin_db["organizations"].insert_one(doc)
        print(f"  org '{org['slug']}' criada")


async def criar_usuarios(db) -> None:
    """Cria/atualiza os usuários de teste (senha sempre redefinida)."""
    for p in PERFILES:
        doc = {
            "username": p["username"],
            "email": f"{p['username']}@saneo.test",
            "hashed_password": get_password_hash(p["password"]),
            "full_name": p["full_name"],
            "is_active": True,
            "role": p["role"],
            "scopes": p["scopes"],
            "must_change_password": p.get("must_change_password", False),
            "position": p["position"],
            "language": "es",
            "updated_at": datetime.utcnow(),
        }
        existente = await db["users"].find_one({"username": p["username"]})
        if existente:
            await db["users"].update_one({"username": p["username"]}, {"$set": doc})
        else:
            doc["created_at"] = datetime.utcnow()
            await db["users"].insert_one(doc)
    print(f"  {len(PERFILES)} usuários prontos")


COLECOES_DE_DADOS = [
    "clients", "readings", "invoices", "payments", "counters", "cash_transactions",
    "cash_sessions", "expenses", "employees", "payrolls", "sponsor_debts",
    "sponsor_invoices", "cutoff_notices", "audit_logs", "sifen_emissions",
]


async def limpar_dados(db) -> None:
    """Apaga os dados de negócio (mantém users e settings)."""
    for col in COLECOES_DE_DADOS:
        await db[col].delete_many({})
    print("  dados anteriores apagados")


# ----------------------------------------------------------------- CSV → dados

def _mz_lote(street2: str, notes: str = "") -> tuple[str, str]:
    """Extrai manzana/lote do endereço (mesma heurística do import_clientes)."""
    for texto in (street2 or "", notes or ""):
        texto = texto.strip()
        if not texto:
            continue
        m = re.search(r"M0*(\d+)\s*L0*(\d+)", texto, re.IGNORECASE)
        if m:
            return m.group(1), m.group(2)
        m = re.search(r"M0*(\d+)\s*[-/]\s*0*(\d+)", texto)
        if m:
            return m.group(1), m.group(2)
    return "", ""


def _tel(valor: str) -> str:
    """Normaliza o telefone do Zoho ('+595983287183 → 0983287183)."""
    t = re.sub(r"[^\d]", "", valor or "")
    if t.startswith("595"):
        t = "0" + t[3:]
    return t


def _dec(valor) -> Decimal:
    try:
        return Decimal(str(valor or "0").replace(",", "").strip() or "0")
    except (InvalidOperation, ValueError):
        return Decimal("0")


def ler_csv(path: str) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


async def seed_clientes(csv_dir: str) -> dict:
    """Cria os clientes a partir de Contactos.csv. Devolve {nome: client}."""
    from app.models.client import Client, ClientCategory, ClientStatus

    linhas = ler_csv(os.path.join(csv_dir, "Contactos.csv"))
    por_nome: dict = {}
    vistos_ci: set = set()
    criados = 0

    for ln in linhas:
        nome = (ln.get("Display Name") or "").strip()
        ci = (ln.get("CF.CI o RUC") or "").strip()
        if not nome or not ci or ci in vistos_ci:
            continue
        vistos_ci.add(ci)

        mz, lote = _mz_lote(ln.get("Billing Street2", ""), ln.get("Notes", ""))
        sub = (ln.get("Customer Sub Type") or "").strip().lower()
        cliente = Client(
            nombre_completo=nome,
            ci_ruc=ci,
            direccion=(ln.get("Billing Address") or "Sin dirección").strip() or "Sin dirección",
            manzana=mz,
            lote=lote,
            telefono=_tel(ln.get("MobilePhone") or ln.get("Billing Phone") or ""),
            categoria=(ClientCategory.COMERCIAL if sub == "business" else ClientCategory.RESIDENCIAL),
            status=(ClientStatus.ATIVO if (ln.get("Status") or "").lower() == "active"
                    else ClientStatus.INATIVO),
        )
        await cliente.insert()
        por_nome[nome] = cliente
        criados += 1

    print(f"  {criados} clientes")
    return por_nome


async def seed_faturas(csv_dir: str, clientes_por_nome: dict) -> int:
    """
    Cria as faturas a partir de Factura.csv (uma linha por item → agrupa por
    número). Entram PENDENTES com saldo cheio: os pagamentos reais são aplicados
    depois pelo serviço de distribuição, que é quem decide o que fica quitado.
    """
    from app.models.invoice import Invoice, InvoiceStatus, InvoiceType, Counter

    linhas = ler_csv(os.path.join(csv_dir, "Factura.csv"))
    agrupadas: dict = {}
    for ln in linhas:
        num = (ln.get("Invoice Number") or "").strip()
        if not num or (ln.get("Invoice Status") or "").strip() in ("Void", "Draft"):
            continue
        agrupadas.setdefault(num, []).append(ln)

    criadas = 0
    sem_cliente = 0
    for num, itens in sorted(agrupadas.items(), key=lambda kv: kv[1][0].get("Invoice Date", "")):
        cab = itens[0]
        cliente = clientes_por_nome.get((cab.get("Customer Name") or "").strip())
        if cliente is None:
            sem_cliente += 1
            continue

        try:
            emissao = datetime.strptime(cab["Invoice Date"], "%Y-%m-%d")
        except (ValueError, KeyError):
            continue
        try:
            venc = datetime.strptime(cab.get("Due Date") or "", "%Y-%m-%d").date()
        except ValueError:
            venc = emissao.date()

        total = _dec(cab.get("Total"))
        if total <= 0:
            continue
        consumo = int(sum(float(i.get("Quantity") or 0) for i in itens))

        invoice = Invoice(
            client=cliente,
            tipo=InvoiceType.CONSUMO,
            status=InvoiceStatus.PENDENTE,
            mes_referencia=emissao.month,
            ano_referencia=emissao.year,
            fecha_vencimiento=venc,
            consumo=consumo,
            tarifa_base=total,
            excedente=Decimal("0"),
            valor_total=total,
            saldo_devedor=total,
            numero_factura=await Counter.get_next("invoice_number"),
        )
        await invoice.insert()
        criadas += 1

    print(f"  {criadas} faturas" + (f" ({sem_cliente} sem cliente correspondente)" if sem_cliente else ""))
    return criadas


async def seed_pagamentos(csv_dir: str) -> int:
    """
    Aplica os pagamentos reais (mais antigos primeiro) pelo serviço de
    distribuição — o mesmo caminho do sistema, então o estado final (saldos,
    faturas quitadas, números de recibo) é consistente de verdade.
    """
    from app.models.client import Client
    from app.services.payment_distribution import PaymentDistributionService

    linhas = ler_csv(os.path.join(csv_dir, "Pagos hasta julio.csv"))
    linhas.sort(key=lambda p: p.get("date") or "")

    por_ci: dict = {}
    for c in await Client.find_all().to_list():
        por_ci[c.ci_ruc] = c.id

    aplicados = 0
    sem_cliente = 0
    sem_deuda = 0
    for ln in linhas:
        ci = (ln.get("contact.CF.CI o RUC") or "").strip()
        valor = _dec(ln.get("bcy_amount") or ln.get("amount"))
        client_id = por_ci.get(ci)
        if client_id is None:
            sem_cliente += 1
            continue
        if valor <= 0:
            continue

        res = await PaymentDistributionService.process_payment(
            client_id=client_id,
            valor_total=valor,
            recibido_por="cajero",
            observacion=f"Importado del histórico ({ln.get('date', '')})",
        )
        if res.success:
            aplicados += 1
        else:
            sem_deuda += 1

    detalhes = []
    if sem_cliente:
        detalhes.append(f"{sem_cliente} sem cliente")
    if sem_deuda:
        detalhes.append(f"{sem_deuda} sem dívida aberta")
    print(f"  {aplicados} pagamentos" + (f" ({', '.join(detalhes)})" if detalhes else ""))
    return aplicados


# --------------------------------------------------------------------- main

async def main() -> None:
    ap = argparse.ArgumentParser(description="Seed de orgs/usuários/dados de teste")
    ap.add_argument("--csv-dir", default=os.getenv("SEED_CSV_DIR", CSV_DIR_PADRAO))
    ap.add_argument("--reset", action="store_true", help="apaga os dados das orgs antes")
    ap.add_argument("--sin-datos", action="store_true", help="só orgs e usuários")
    args = ap.parse_args()

    settings = get_settings()
    if not settings.encryption_key:
        print("AVISO: ENCRYPTION_KEY vazia — as orgs ficam sem connection string cifrada\n"
              "       (o backend cai no fallback da URL global; serve para dev local).")

    client = AsyncIOMotorClient(settings.mongodb_url)
    admin_db = client["wmapp_admin"]

    from beanie import init_beanie
    from app.database import _get_org_document_models

    print(f"MongoDB: {settings.mongodb_url}")
    for org in ORGS:
        print(f"\n[{org['slug']}] {org['name']}")
        await criar_org(admin_db, org, settings.mongodb_url, settings.encryption_key)

        db = client[f"wmapp_{org['slug']}"]
        await init_beanie(database=db, document_models=_get_org_document_models())

        if args.reset:
            await limpar_dados(db)
        await criar_usuarios(db)

        from app.models.settings import SystemSettings
        await SystemSettings.get_instance()   # garante o doc de configuração

        if org["datos"] and not args.sin_datos:
            if not os.path.isdir(args.csv_dir):
                print(f"  CSVs não encontrados em {args.csv_dir} — pulando os dados")
                continue
            clientes = await seed_clientes(args.csv_dir)
            await seed_faturas(args.csv_dir, clientes)
            await seed_pagamentos(args.csv_dir)

    print("\n" + "=" * 68)
    print("ORGS:      " + " · ".join(o["slug"] for o in ORGS))
    print("USUARIOS (mesmos nas duas orgs):")
    for p in PERFILES:
        marca = "  [1º acesso: troca senha]" if p.get("must_change_password") else ""
        escopos = "todo" if p["scopes"] == ["*"] else ", ".join(p["scopes"])
        print(f"  {p['username']:<11} {p['password']:<14} {p['position']:<18} {escopos}{marca}")
    print("=" * 68)
    client.close()


if __name__ == "__main__":
    asyncio.run(main())
