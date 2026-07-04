# Junta CRM (WMApp)

Sistema de administração para **juntas de saneamento** (água potável, Paraguai): cadastro de
clientes, leituras, faturamento, caixa/pagamentos, corte e reativação de serviço, finanças,
subsídios, mapa catastral e WhatsApp. SaaS **multi-tenant** (uma org por junta).

> **Idioma da UI: espanhol.** Toda mensagem/rótulo voltado ao usuário final é em espanhol
> (es). O código e comentários são majoritariamente em pt-BR. Há uma camada de i18n es/pt.

---

## Componentes (monorepo)

| Pasta | Stack | Papel |
|---|---|---|
| `backend/` | **FastAPI + Beanie (ODM) + MongoDB** (async) | API "cérebro": dados puros (JSON), regras de negócio, multi-tenant. Não gera PDFs. |
| `frontend/` | **Flet 0.84** (desktop Windows, Python) | App do operador. Renderiza UI, gera/imprime PDFs localmente. |
| `admin-api/` | Node.js / TypeScript | API do superadmin: cria orgs, gera connection strings criptografadas (AES-256) em `wmapp_admin`. |
| `admin-panel/` | Next.js | Painel web do superadmin. |
| `app_android/` | Flutter | App mobile (entregadores/técnicos — confirmação por QR, foto, GPS). |
| `geoespacial/` | scripts | Processamento de GeoJSON/catastro. |
| `tools/` | scripts | Utilitários. |

---

## Arquitetura multi-tenant (importante)

- **Banco por org**: `wmapp_{slug}` (ex.: `wmapp_juntacrm`), cada um com **credencial Mongo dedicada**.
  O banco do superadmin é `wmapp_admin` (coleção `organizations` com a `connectionString` **criptografada**).
- A coleção `users` mora **dentro de cada org** — não há tabela global de usuários.
- **Login** (`POST /auth/token`, OAuth2 form): `username`, `password` e o **org slug** no campo
  `client_id`. O JWT carrega `sub` (username), `org` (slug) e `role`.
- Cada request reativa o banco da org a partir do `org` no token (`middleware/org_context.py`,
  `database.ensure_org_db(slug)`). Lazy + cacheado por processo.
- Detalhes/roadmap: [docs/architecture/PLANO_WHATSAPP_MULTIORG.md](docs/architecture/PLANO_WHATSAPP_MULTIORG.md).

---

## Como rodar (dev, Windows)

Pré-requisitos: **MongoDB** em `127.0.0.1:27017` e `backend/.env` (com `MONGODB_URL`,
`ENCRYPTION_KEY`, `SECRET_KEY`, `MAPBOX_TOKEN`, etc.).

```bash
# Backend (porta 8000) — precisa do MongoDB no ar
cd backend && python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Frontend (janela Flet desktop)
cd frontend && python main.py
# logs em tempo real (stdout fica em buffer sem -u):
#   WMAPP_DEBUG_LOGS=1 PYTHONUNBUFFERED=1 python -u main.py

# Testes do backend
cd backend && python -m pytest
```

**Credenciais de dev** (org semeada localmente): slug `juntacrm` / usuário `admin` / senha `admin123`.

---

## Backend — estrutura

```
backend/app/
  main.py            # cria o FastAPI, registra routers, lifespan (init_db, jobs)
  config.py          # Settings (env): mongodb_url, encryption_key, mapbox_*, ...
  database.py        # multi-tenant: wmapp_admin + wmapp_{slug}, init_beanie por org
  middleware/        # org_context (ContextVar com o slug do request)
  models/            # Documentos Beanie (ver abaixo)
  schemas/           # Pydantic request/response
  routers/           # endpoints (ver tabela)
  services/          # regras de negócio (ver abaixo)
  utils/             # crypto (AES-256), security (bcrypt), r2 (storage)
  whatsapp/          # webhook + envio (Meta Cloud API)
```

### Routers (`app.include_router` em `main.py`)
`/auth` · `/clients` · `/readings` · `/invoices` · `/payments` · `/settings` · `/finance`
· `/sponsors` · `/cutoff` (+ `/cutoff/qr/*` público) · `/upload` · `/map` · `/whatsapp`

### Models principais
- `Organization` (em `wmapp_admin`) — slug, connectionString criptografada.
- `User` — por org; `role` master/operator, `scopes`, `position` (cargo), `language` es/pt.
- `Client`, `Reading`, `Invoice` (+ `Counter` sequencial), `Payment`.
- `SystemSettings` — tarifas, faturamento, corte, **horario_atencion + banco/alias**, logo.
- Finanças: `CashTransaction`, `Expense`, `Employee`, `Payroll`.
- Subsídios: `SponsorDebt`, `SponsorInvoice`.
- `CutoffNotice` — workflow de corte (estados + tokens QR).

### Services principais
- `payment_distribution.py` — distribui o pagamento nas faturas (mais antiga→recente),
  aplica subsídio, gera `numero_recibo`, dispara auto-exit/auto-reativação.
- `cutoff_service.py` — workflow de corte/reativação (ver fluxo abaixo).
- `invoice_generation.py` — geração mensal de faturas (independentes, sem carry-over).
- `client_matching.py`, `sponsor_service.py`.

---

## Domínio — fluxos críticos

> Fonte detalhada: [docs/workflow_documentation.md](docs/workflow_documentation.md) e
> [docs/functional_documentation.md](docs/functional_documentation.md).

- **Faturamento**: faturas **independentes** por mês (sem dívida cumulativa). `numero_factura`
  sequencial via `Counter("invoice_number")`. Tarifa única global + franquia + excedente/m³;
  subsídio aplicado no pagamento (vira `SponsorDebt`).
- **Pagamento + Recibo**: `process_payment` distribui o valor, registra `CashTransaction`
  (ENTRADA), e numera o recibo com **`numero_recibo`** sequencial — exibido `00001` (5 díg.).
- **Corte** (`CutoffNotice.status`): `EM_LISTA → EM_AVISO → EM_CONTAGEM → PRONTO_PARA_CORTE → CORTADO`.
  Cada etapa pode ser confirmada por **QR** (entregador/técnico via app mobile) ou manualmente.
  A **nota de corte** imprime horário de atención + dados bancários (obrigatórios, sem fallback).
- **Auto-exit**: se o cliente paga toda a dívida **antes** do corte, sai do workflow.
- **Reativação automática**: se um cliente **CORTADO** paga a dívida, `check_auto_reactivation_for_client`
  dispara a reativação (registra a taxa, gera QR, **comprobante = `numero_recibo`**), e o
  `payments_view` imprime a *Orden de Reactivación* junto com o recibo. A confirmação (QR/manual)
  devolve o cliente ao status **ATIVO**.

---

## Frontend — convenções (Flet 0.84)

- Entrypoint `ft.run(main)`. **Atenção**: o 0.84 tem muitas mudanças de API —
  ver **[docs/FLET_API_GOTCHAS.md](docs/FLET_API_GOTCHAS.md)** (FilePicker em `page.services` +
  `pick_files` async, `ft.Alignment.CENTER`, sem `max_height`, teclado em `AppModal`).
- **i18n**: `from i18n import t` (`frontend/i18n.py`); catálogos es/pt; idioma vem de
  `user.language` (default es). Strings novas voltadas ao usuário → catálogo + `t()`.
- **Views** em `frontend/views/` (uma por módulo do sidebar). **Componentes** reutilizáveis em
  `frontend/components/` (`app_modal`, `data_table`, `map_picker`, `sidebar`, `theme`, ...).
- **Services** (`frontend/services/`) falam com a API (`api_client`), guardam o token e o slug.
- **PDFs** em `frontend/services/pdf_generation/` (reportlab). Impressão no Windows via
  pypdfium2 + GDI — ver gotchas. Pasta de referência de design: `docs/delivery pro designer/`.

---

## Índice da documentação (`docs/`)

- **[CHANGES_2026-06.md](docs/CHANGES_2026-06.md)** — mudanças recentes (Flet 0.84, recibo, reativação auto, i18n, mapa).
- [FLET_API_GOTCHAS.md](docs/FLET_API_GOTCHAS.md) — incompatibilidades do Flet 0.84.
- [functional_documentation.md](docs/functional_documentation.md) — funcionalidades por módulo.
- [workflow_documentation.md](docs/workflow_documentation.md) — lógica de faturamento/corte/recursividade.
- [FRONTEND_INTEGRATION.md](docs/FRONTEND_INTEGRATION.md) — endpoints e integração do frontend.
- [implementation_plan.md](docs/implementation_plan.md) — arquitetura (API remota + cliente local).
- [architecture/PLANO_WHATSAPP_MULTIORG.md](docs/architecture/PLANO_WHATSAPP_MULTIORG.md) — multi-org + WhatsApp.
- **Facturación electrónica (SIFEN/DNIT)**: docs locais (gitignored) em `docs/SIFEN_*.md` — referência
  da API, arquitetura de integração (sessão única, lock, coordenador, subsídio, KuDE) e plano por fases.
  A implementação sensível mora num módulo/repo **fechado** à parte; no repo público a integração é
  genérica e o endpoint vem de env var (`SIFEN_BASE`).
- PDFs/impressão: [PDF_IMPLEMENTATION_VALIDATION.md](docs/PDF_IMPLEMENTATION_VALIDATION.md),
  [PDF_TEMPLATE_MIGRATION_PLAN.md](docs/PDF_TEMPLATE_MIGRATION_PLAN.md),
  [PRINTING_TROUBLESHOOTING.md](docs/PRINTING_TROUBLESHOOTING.md).
- Templates HTML legados de referência: `docs/templates/`.

---

## Notas práticas / pegadinhas

- **Reiniciar após mudar código**: backend (uvicorn) e frontend (Flet) não recarregam sozinhos
  no fluxo de dev usado aqui — reinicie o processo.
- **Logs do Flet**: rode com `-u` / `PYTHONUNBUFFERED=1`, senão o stdout fica em buffer. Erros de
  build de uma view aparecem como `[WMApp] auto_login_unexpected_error` — corrigir um costuma
  revelar o próximo.
- **Testes do backend**: a fixture de auth pode retornar `401` em ambiente sem o setup multi-tenant
  completo — não é regressão das regras de negócio.
- **datetime.utcnow()** está deprecado (hints do linter) mas é o padrão atual no código.
- **SEMPRE TESTAR SE UM NOME DE FUNÇÃO EXISTE NO FLET!** O flet tem muitas coisas diferentes do que estamos acostumados, então muita coisa não é o que voce acha que é, sempre rode e veja se existe antes de aplicar.