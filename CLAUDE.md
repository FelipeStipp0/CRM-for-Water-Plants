# Junta CRM (WMApp)

Sistema de administração para **juntas de saneamento** (água potável, Paraguai): cadastro de
clientes, leituras, faturamento, caixa/pagamentos, corte e reativação de serviço, finanças,
subsídios, mapa catastral e WhatsApp. SaaS **multi-tenant** (uma org por junta).

> **Idioma da UI: espanhol.** Toda mensagem/rótulo voltado ao usuário final é em espanhol
> (es). O código e comentários são majoritariamente em pt-BR. Há uma camada de i18n es/pt.

> **📌 Para IA/agentes:** comece por **[docs/AI_CONTEXT.md](docs/AI_CONTEXT.md)** (onde mexer,
> o que ler antes, pegadinhas + mapa de referência do Flet) e
> **[docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)** (arquitetura
> de ponta a ponta). Este CLAUDE.md é o resumo curto.

---

## Componentes (monorepo)

| Pasta | Stack | Papel |
|---|---|---|
| `backend/` | **FastAPI + Beanie (ODM) + MongoDB** (async) | API "cérebro": dados puros (JSON), regras de negócio, multi-tenant. Não gera PDFs. |
| `frontend/` | **Flet 0.86** (desktop Windows, Python 3.14) | App do operador. Renderiza UI, gera/imprime PDFs localmente. |
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
`/auth` · `/clients` · `/readings` · `/invoices` · `/payments` · `/products` · `/settings`
· `/finance` · `/caja` · `/agreements` · `/sponsors` · `/cutoff` (+ `/cutoff/qr/*` público)
· `/upload` · `/map` · `/sifen` · `/whatsapp`

### Models principais
- `Organization` (em `wmapp_admin`) — slug, connectionString criptografada.
- `User` — por org; `role` master/operator, `scopes`, `position` (cargo), `language` es/pt.
- `Client`, `Reading`, `Invoice` (+ `Counter` sequencial), `Payment`.
- `SystemSettings` — tarifas, faturamento, corte, **horario_atencion + banco/alias**, logo.
- Finanças: `CashTransaction`, `Expense`, `Employee`, `Payroll`.
- Subsídios: `SponsorDebt`, `SponsorInvoice`.
- `CutoffNotice` — workflow de corte (estados + tokens QR).
- `CashSession` — turno de caja (apertura → cobrança → cierre).
- `PaymentAgreement` — acordo de pagamento (parcelamento): parcelas agendadas + vínculo com
  as faturas antigas anuladas. Um ATIVO por cliente.

### Services principais
- `payment_distribution.py` — distribui o pagamento nas faturas (mais antiga→recente),
  aplica subsídio, gera `numero_recibo`, dispara auto-exit/auto-reativação.
- `cutoff_service.py` — workflow de corte/reativação (ver fluxo abaixo).
- `invoice_generation.py` — geração mensal de faturas (independentes, sem carry-over).
- `agreement_service.py` — acordo de pagamento: anula a dívida velha (saldo zerado), agenda
  as parcelas, aplica a cuota na fatura do mês e fecha o acordo na última parcela.
- `caja_service.py` — turno de caja: apertura, sangría/reposición, efectivo esperado, cierre.
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
- **Acuerdo de pago** (parcelamento, fechado no balcão): as faturas escolhidas viram
  `ANULADA` **com `saldo_devedor` zerado** e a dívida passa a viver em parcelas, somadas à
  fatura de consumo do mês correspondente (`Invoice.cuota_valor`, com IVA próprio escolhido no
  acordo). Total = soma exata dos saldos, sem juros; última parcela absorve a sobra da divisão.
  Um acordo ativo por cliente — dívida nova refaz o acordo. Parcela vencida cai no fluxo de
  corte porque quem vence é a própria fatura do mês.
- **Auto-exit**: se o cliente paga toda a dívida **antes** do corte, sai do workflow.
- **Reativação automática**: se um cliente **CORTADO** paga a dívida, `check_auto_reactivation_for_client`
  dispara a reativação (registra a taxa, gera QR, **comprobante = `numero_recibo`**), e o
  `payments_view` imprime a *Orden de Reactivación* junto com o recibo. A confirmação (QR/manual)
  devolve o cliente ao status **ATIVO**.

---

## Frontend — convenções (Flet 0.86)

- Entrypoint `ft.run(main)` (não mais `ft.app`).
- 🚨 **Não mexer no Flet sem antes verificar a documentação oficial.** A **fonte de verdade** é o
  snapshot local da doc oficial em **`flet/website/docs/`** (controls, cookbook, services, types).
  Mapa "precisa de X → doc local Y" em **[docs/AI_CONTEXT.md §3](docs/AI_CONTEXT.md)**. Em dúvida
  de assinatura, `python -c "import flet as ft, inspect; print(inspect.signature(...))"`.
- **[docs/FLET_API_GOTCHAS.md](docs/FLET_API_GOTCHAS.md)** guarda **apenas o que é específico
  deste app** e não está na doc oficial (exe branded no Windows, `AppModal` como camada de compat).
  Divergência de API pura é da doc oficial — não é gotcha.
- **i18n**: `from i18n import t` (`frontend/i18n.py`); catálogos es/pt; idioma vem de
  `user.language` (default es). Strings novas voltadas ao usuário → catálogo + `t()`.
- **Views** em `frontend/views/` (uma por módulo do sidebar). **Componentes** reutilizáveis em
  `frontend/components/` (`app_modal`, `data_table`, `map_picker`, `sidebar`, `theme`, ...).
- **Services** (`frontend/services/`) falam com a API (`api_client`), guardam o token e o slug.
- **PDFs** em `frontend/services/pdf_generation/` (reportlab). Impressão no Windows via
  pypdfium2 + GDI — ver gotchas. Pasta de referência de design: `docs/delivery pro designer/`.

---

## Índice da documentação (`docs/`)

- **[AI_CONTEXT.md](docs/AI_CONTEXT.md)** — guia de navegação p/ IA (onde mexer, mapa de referência do Flet).
- **[architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)** — arquitetura de ponta a ponta.
- **[CHANGES_2026-07.md](docs/CHANGES_2026-07.md)** — Modo Caja completo (busca, cadastro no balcão,
  otros cargos, cobro parcial, acuerdo de pago, anular/reimprimir, sangría/cierre às cegas, teclado).
  Plano de origem: [PLANO_CAJA.md](docs/PLANO_CAJA.md).
- **[CHANGES_2026-06.md](docs/CHANGES_2026-06.md)** — mudanças anteriores (Flet, recibo, reativação auto, i18n, mapa).
- **Flet: doc oficial** em `flet/website/docs/` (fonte de verdade da API). [FLET_API_GOTCHAS.md](docs/FLET_API_GOTCHAS.md) — só o específico deste app (exe branded, `AppModal`).
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

- 🚨 **`HANDOFF.md` NUNCA é commitado.** É a nota de transferência entre sessões e tem
  conteúdo interno que não pode ir para o repo. Está no `.gitignore`; se aparecer em
  `git status`, é para deixar de fora — não adicionar com `git add -A` sem conferir.
- **Reiniciar após mudar código**: backend (uvicorn) e frontend (Flet) não recarregam sozinhos
  no fluxo de dev usado aqui — reinicie o processo.
- **Logs do Flet**: rode com `-u` / `PYTHONUNBUFFERED=1`, senão o stdout fica em buffer. Erros de
  build de uma view aparecem como `[WMApp] auto_login_unexpected_error` — corrigir um costuma
  revelar o próximo.
- **Testes do backend**: a fixture de auth pode retornar `401` em ambiente sem o setup multi-tenant
  completo — não é regressão das regras de negócio.
- **datetime.utcnow()** está deprecado (hints do linter) mas é o padrão atual no código.
- **NÃO MEXER NO FLET SEM ANTES VERIFICAR A DOCUMENTAÇÃO OFICIAL!** O flet tem muita coisa diferente do que estamos acostumados — muito não é o que você acha que é. Consulte **sempre** o snapshot da doc oficial em `flet/website/docs/` (mapa em [docs/AI_CONTEXT.md §3](docs/AI_CONTEXT.md)) antes de escrever qualquer código Flet; em dúvida de assinatura, `python -c "import flet as ft, inspect; print(inspect.signature(...))"`.