# Saneo (Junta CRM)

Sistema de administração para **juntas de saneamento** — cooperativas comunitárias de água
potável (Paraguai). Cobre o ciclo completo de gestão: cadastro de clientes, leituras de
hidrômetro, faturamento, caixa e pagamentos, corte e reativação de serviço, finanças,
subsídios, mapa catastral e comunicação por WhatsApp.

É um **SaaS multi-tenant**: cada junta é uma organização isolada, com o seu próprio banco de
dados e as suas próprias credenciais.

> **Idioma da UI:** espanhol. Toda mensagem e rótulo voltado ao usuário final é em espanhol.
> O código e os comentários são majoritariamente em português (pt-BR), com uma camada de
> i18n es/pt no frontend.

---

## O que o sistema faz

- **Clientes** — cadastro com dados catastrais e localização no mapa.
- **Leituras** — registro mensal do hidrômetro por cliente.
- **Faturamento** — geração mensal de faturas. As faturas são **independentes** por mês (não há
  dívida cumulativa/carry-over). Tarifa única global + franquia + excedente por m³. Numeração
  sequencial (`numero_factura`).
- **Pagamentos e recibos** — o valor pago é distribuído entre as faturas em aberto (da mais
  antiga para a mais recente), registra-se uma entrada de caixa e emite-se um **recibo
  numerado** (`numero_recibo`).
- **Subsídios (sponsors)** — parte da fatura pode ser coberta por um patrocinador; o valor
  subsidiado vira uma dívida do sponsor.
- **Corte e reativação** — workflow de corte de fornecimento em etapas
  (`EM_LISTA → EM_AVISO → EM_CONTAGEM → PRONTO_PARA_CORTE → CORTADO`), cada uma confirmável
  por **QR** (via app mobile de campo) ou manualmente. Quem paga a dívida antes do corte sai
  do fluxo automaticamente; um cliente **cortado** que quita a dívida é reativado
  automaticamente.
- **Finanças** — caixa, despesas, funcionários e folha de pagamento.
- **Mapa catastral** — visualização geoespacial da rede e dos clientes.
- **WhatsApp** — envio de mensagens (texto e template) e recebimento via webhook.

---

## Arquitetura

Monorepo com quatro serviços principais que se comunicam por **HTTP/JSON**, mais um app
mobile de campo.

```
                 ┌──────────────────────┐        ┌──────────────────────┐
                 │   admin-panel        │  HTTP  │     admin-api        │
                 │   (Next.js, web)     │───────▶│  (Node/TS, superadmin)│
                 │   painel do superadmin│        │  cria orgs, credenciais│
                 └──────────────────────┘        └──────────┬───────────┘
                                                            │ grava org +
                                                            │ connection string
                                                            │ criptografada (AES-256)
                                                            ▼
                                                 ┌──────────────────────┐
   ┌──────────────────────┐            HTTP/JSON │      MongoDB         │
   │   frontend           │◀──────────┐         │  wmapp_admin +       │
   │   (Flet, desktop)    │           │         │  wmapp_{slug} por org│
   │   app do operador    │           │         └──────────┬───────────┘
   │   gera/imprime PDFs   │           │                    ▲
   └──────────────────────┘           │                    │
                                       ▼                    │
                            ┌──────────────────────┐        │
   ┌──────────────────────┐ │      backend         │────────┘
   │   app_android        │ │   (FastAPI + Beanie) │
   │   (Flutter, campo)   │─┼▶  API "cérebro":     │◀── webhook ── WhatsApp
   │   QR, foto, GPS      │ │   dados + regras     │    (Meta Cloud API)
   └──────────────────────┘ └──────────────────────┘
```

| Pasta | Stack | Papel |
|---|---|---|
| `backend/` | **FastAPI + Beanie (ODM) + MongoDB** (async) | API "cérebro": dados puros (JSON), regras de negócio, multi-tenant. Não gera PDFs. |
| `frontend/` | **Flet 0.84** (Python, desktop Windows) | App do operador. Renderiza a UI e gera/imprime PDFs localmente (recibos, faturas, ordens de corte). |
| `admin-api/` | **Node.js / TypeScript (Express)** | API do superadmin: cria organizações e gera as connection strings criptografadas. |
| `admin-panel/` | **Next.js** | Painel web do superadmin. |
| `app_android/` | **Flutter** | App mobile de campo (entregadores/técnicos): confirmação por QR, foto e GPS. |
| `geoespacial/` | scripts | Processamento de GeoJSON / catastro. |
| `tools/` | scripts | Utilitários. |

### Separação de responsabilidades

- O **backend** só trabalha com dados: recebe e devolve JSON, aplica as regras de negócio e
  nunca gera arquivos. É o único que fala com o MongoDB das organizações.
- O **frontend** (Flet) é onde o operador trabalha. Consome a API, mantém o token e o slug da
  org, e **gera/imprime os PDFs localmente** (reportlab + impressão no Windows via pypdfium2/GDI).
- O **admin-api** + **admin-panel** formam o plano de superadministração, isolado do dia a dia
  das juntas: cria organizações e provisiona as suas credenciais.

---

## Multi-tenant

- **Um banco por organização**: `wmapp_{slug}` (ex.: `wmapp_juntacrm`), cada um com uma
  **credencial Mongo dedicada**.
- O banco do superadmin é `wmapp_admin`, com a coleção `organizations` onde a `connectionString`
  de cada org é guardada **criptografada (AES-256)**.
- A coleção `users` mora **dentro de cada org** — não existe tabela global de usuários.
- **Login** (`POST /auth/token`, form OAuth2): `username`, `password` e o **slug da org** no
  campo `client_id`. O JWT carrega `sub` (usuário), `org` (slug) e `role`.
- A cada request, um middleware reativa o banco da org a partir do `org` presente no token
  (lazy + cacheado por processo).

---

## Comunicação entre as partes

- **Frontend ↔ backend**: HTTP/JSON autenticado por JWT (Bearer). O frontend guarda token +
  slug e chama os routers do backend.
- **app_android ↔ backend**: mesma API. As etapas do workflow de corte/reativação são
  confirmadas por endpoints de QR (parte deles públicos, protegidos por token de uso único).
- **admin-panel ↔ admin-api**: HTTP/JSON. O admin-api escreve no `wmapp_admin` e provisiona as
  credenciais Mongo de cada org.
- **admin-api → email**: notificações transacionais (credenciais, reset de senha, convites) por
  email a partir de um domínio verificado.
- **backend ↔ WhatsApp**: integração com a **Meta WhatsApp Cloud API** — webhook
  (`GET/POST /whatsapp/webhook`) para verificação e recebimento, e endpoints de envio
  (`/whatsapp/send/text`, `/whatsapp/send/template`).

### API do backend (routers principais)

`/auth` · `/clients` · `/readings` · `/invoices` · `/payments` · `/settings` · `/finance`
· `/sponsors` · `/cutoff` (+ `/cutoff/qr/*` público) · `/upload` · `/map` · `/whatsapp`

---

## Modelo de dados (backend)

- `Organization` (em `wmapp_admin`) — slug + connection string criptografada.
- `User` — por org; `role` (master/operator), `scopes`, `position` (cargo), `language` (es/pt).
- `Client`, `Reading`, `Invoice` (+ `Counter` sequencial), `Payment`.
- `SystemSettings` — tarifas, faturamento, corte, horário de atendimento, dados bancários, logo.
- Finanças: `CashTransaction`, `Expense`, `Employee`, `Payroll`.
- Subsídios: `SponsorDebt`, `SponsorInvoice`.
- `CutoffNotice` — workflow de corte (estados + tokens QR).

### Serviços de negócio principais

- `payment_distribution.py` — distribui o pagamento nas faturas (mais antiga → recente), aplica
  subsídio, numera o recibo e dispara auto-saída do corte / reativação automática.
- `cutoff_service.py` — workflow de corte e reativação.
- `invoice_generation.py` — geração mensal de faturas independentes.
- `client_matching.py`, `sponsor_service.py`.

---

## Estrutura do repositório

```
backend/       FastAPI + Beanie + MongoDB (API multi-tenant)
frontend/      App Flet do operador (desktop, gera PDFs)
admin-api/     API do superadmin (Node/TS)
admin-panel/   Painel web do superadmin (Next.js)
app_android/   App de campo (Flutter)
geoespacial/   Processamento geoespacial (GeoJSON/catastro)
tools/         Utilitários
```

---

## Stack resumida

- **Backend:** Python, FastAPI, Beanie (ODM), Motor, MongoDB, JWT (python-jose), bcrypt,
  APScheduler, boto3 (storage S3-compatível), Pillow.
- **Frontend:** Python, Flet 0.84, reportlab, pypdfium2 (impressão no Windows).
- **admin-api:** Node.js, TypeScript, Express, MongoDB driver, zod, JWT.
- **admin-panel:** Next.js, React.
- **app_android:** Flutter.
- **Integrações:** Meta WhatsApp Cloud API, email transacional, storage S3-compatível.
