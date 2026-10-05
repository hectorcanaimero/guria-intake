# guria-intake

Conversational intake agent for [guria.lat](https://guria.lat), an AI engineering practice serving businesses in Brazil and Latin America.

A visitor describes their project in a chat widget. The assistant asks follow-up questions until the problem is clear (what it costs today for running businesses, what is already validated for new products), confirms a summary, and tells the visitor the Guria team will reach out with a proposal and an online meeting. A LangGraph workflow then drafts an internal brief (scope, risks, effort range, open questions, related past work) for review before anyone replies. It also writes the client-facing proposal: a slide deck in guria.lat's visual identity, exported to PDF and sent to the team on WhatsApp for review. Conversations are persisted, classified nightly, and summarized in a weekly report, so the agent improves through reviewed changes rather than learning from raw chat input.

The chat works in Spanish and Portuguese.

## How it works

```
browser widget ──POST /api/chat──▶ FastAPI ──▶ chat agent (LangChain create_agent + SQLite checkpointer)
                                                   │
                                                   ├─ cerrar_charla   ends off-topic or abusive sessions
                                                   └─ enviar_intake   validates and stores the intake
                                                                          │
                                                       background task ◀──┘
                                                          │
                                                          ▼
                     drafting workflow (LangGraph StateGraph)
                     evaluar → triage ─(vague)─▶ pedir_datos
                                      └(clear)─▶ buscar ─┬▶ redactar ⇄ revisar ─(fit)─▶ componer ⇄ revisar_propuesta
                                                         └▶ marketing   (runs in parallel with redactar)
                                                          │
                     interno.py: internal brief → A4 PDF (headless Chromium)
                     deck.py: proposal → HTML slides → PDF
                     avisos.py: summary + internal PDF, then proposal PDF → n8n webhook → WhatsApp
```

**Two parts with different jobs.** Conversation is open-ended, so it is an agent. Drafting is a known process, so it is a fixed graph where the model only works inside nodes (`triage`, `redactar`, `marketing`, `componer`) and everything verifiable runs as plain code.

**Two internal views, one call each.** `redactar` acts as a product owner with technical judgment: a viability verdict, what to reuse before building, what depends on the client, and the hypothesis and metric the first stage tests. It deliberately does not write a spec. `marketing` reads the intake as a buyer: real pain, motivations, likely objections, and the angle that `componer` uses to order the proposal. It needs only the intake, so it fans out from `buscar` and runs alongside `redactar`.

**Rules live in code, not prompts.** `revisar` rejects inverted ranges, references to projects that don't exist, and a "not viable" verdict marked as a fit, and sends the draft back to `redactar` at most twice. If the brief says the project is not a fit, no proposal is composed: the team gets the brief and decides. The client deck never cites past projects. LLM nodes retry when the model omits a required field. The assistant never asks about budget: a declared budget anchors the estimate, so money is discussed only in the meeting. Session state, turn limits, and rate limits are enforced by the API, so a closed session never reaches the model.

**No prices to clients.** The internal brief (`Borrador`) carries effort as hours per deliverable; code turns them into cost and weeks with the team's rate (`TARIFA_USD_HORA`, `HORAS_SEMANA`), so the model never sets a price; the client proposal (`Propuesta`) is a separate schema with no price or date fields at all, and `revisar_propuesta` rejects any currency, duration, em dash, or pressure tactic (fake scarcity, limited-time offers) before it is rendered. The deck's only call to action is booking a 30-minute online meeting.

**Content from the model, design from code.** The model fills a fixed schema; `deck.py` owns layout, typography, and color, and pulls reference-project details from the real project list. Every proposal looks the same and the model cannot break the layout.

## Learning loop

Every conversation is stored, but none of them changes the agent directly. Letting public chat input shape the agent would make it trivial to poison.

| Step | Who | How |
|---|---|---|
| Store | automatic | LangGraph `SqliteSaver` + a `sesiones` table (state, turns, category) |
| Classify | nightly cron | [Jev](https://typesafe.ai) (TypeSafe System One): category as a `Choice`, objections as `Noul`s, and the unanswered question *selected* from the client's real messages, never generated |
| Report | weekly cron | Conversion, objections, leads that dropped off, and low-confidence classifications sent to a webhook |
| Change | human | Prompt and rule changes, reviewed and versioned in git |

## Stack

- **LangChain 1.x / LangGraph**: chat agent, drafting workflow, checkpointing
- **FastAPI**: chat endpoint with validation, rate limiting, and background drafting
- **SQLite** (WAL): conversation checkpoints and session metadata
- **TypeSafe Jev**: conversation classification with calibrated probabilities
- **OpenAI-compatible gateway** ([9router](https://github.com/decolua/9router)): routes and falls back across model providers
- **LangSmith**: tracing and LangGraph Studio during development

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # fill in the values below
uv run --env-file .env uvicorn api:app --port 8000
```

PDF export needs Chromium. In development it is auto-detected (system Chromium or a Playwright install); the Docker image ships its own.

| Variable | Purpose |
|---|---|
| `ROUTER_BASE_URL`, `ROUTER_API_KEY`, `ROUTER_MODEL` | OpenAI-compatible endpoint and model for the chat and drafting |
| `TYPESAFE_API_KEY` | Jev, for nightly classification (`TYPESAFE_MODEL` defaults to `jev-latest`) |
| `REPORTE_WEBHOOK_URL`, `XAPI` | Team webhook (new intakes with the PDF, weekly report) and the value sent in its `xapi` header |
| `AGENDA_URL` | Booking link shown on the proposal's last slide |
| `CHROMIUM_BIN` | Optional path to Chromium for PDF export (auto-detected otherwise) |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Tracing, for development only (see Privacy) |
| `INTAKE_DB` | SQLite path (default `data/intake.db`) |

## API

`POST /api/chat`

```json
{ "thread_id": "3f1c…", "mensaje": "Tenho uma loja de roupas e perco muito tempo no WhatsApp" }
```

```json
{ "respuesta": "Entendi, 150 mensagens por dia é bastante…", "terminado": false }
```

The client generates `thread_id` once per session (8–64 characters, `[A-Za-z0-9-]`) and sends only the new message; history is kept server-side. When `terminado` is `true`, the session is closed. Limits: 2,000 characters per message, 30 messages per session, 60 messages per IP per hour.

## Notifications

Every finished intake posts to `REPORTE_WEBHOOK_URL` with the `xapi` header:

```json
{ "tipo": "nuevo_intake",
  "text": "Nuevo intake · Confirmación de turnos por WhatsApp\nMarina · Clínica Sorriso · …",
  "archivo": { "nombre": "<thread_id>.pdf", "mimetype": "application/pdf", "base64": "…" } }
```

The weekly report uses the same webhook with `"tipo": "reporte"`. In production an n8n flow forwards both to WhatsApp (Evolution API `sendMedia` for the PDF). A failed notification never loses data: the intake, brief, and deck are written to disk first.

## Operations

```bash
uv run --env-file .env python mantenimiento.py                    # retention + classification
uv run --env-file .env python mantenimiento.py reporte --enviar   # weekly report to the webhook
uv run --env-file .env python mantenimiento.py ver <thread_id>    # read a conversation
uv run --env-file .env python mantenimiento.py borrar <email>     # erase a person's data
```

Suggested crontab:

```cron
0 3 * * *  cd /path/to/guria-intake && uv run --env-file .env python mantenimiento.py
0 8 * * 1  cd /path/to/guria-intake && uv run --env-file .env python mantenimiento.py reporte --enviar
```

Retention runs before classification and does not depend on any external service.

## Deploy

The image bundles headless Chromium, which `deck.py` uses to print the proposal PDF.

```bash
docker build -t guria-intake .
docker run -d -p 8000:8000 --env-file .env -v guria-intake-data:/app/data guria-intake
```

- **Data:** mount a persistent volume at `/app/data` (SQLite, intakes, proposal HTML and PDF) and back it up.
- **Health:** `GET /health`, also used by the image's `HEALTHCHECK`.
- **Exposure:** the API needs no public domain. Put it on the same Docker network as the site and proxy `/api/*` to it (`reverse_proxy guria-intake:8000` in Caddy).
- **Scheduled jobs** (for example Coolify Scheduled Tasks, run inside the container):
  - `0 3 * * *` → `python mantenimiento.py`
  - `0 8 * * 1` → `python mantenimiento.py reporte --enviar`
- The PDF loads the brand fonts from Google Fonts at render time, so the container needs outbound HTTPS.

## Privacy

Built for LGPD. The chat widget on guria.lat tells visitors the conversation is stored, why, and for how long. Sessions that became leads are kept for 12 months and all others for 90 days. `borrar` removes a person's checkpoints, session row, stored intake, and generated proposal files in one step.

LangSmith tracing is off by default and meant for development only. Traces are a copy of the conversation stored outside this erasure flow, so production keeps a single source of truth: the local database.

## Development

```bash
uv run pytest -q                 # no network: models are replaced by scripted fakes
uv run --env-file .env python grafo.py          # run the drafting workflow on a sample intake
uv run --env-file .env python grafo.py --vaga   # same, with a vague description
uv run --env-file .env python chat.py           # chat from the terminal
uv run langgraph dev                            # inspect the drafting graph in LangGraph Studio
```

Tests cover session memory across restarts, intake validation, closing abusive sessions without further model calls, the draft review loop, classification, retention, and erasure.

## Layout

| File | Contents |
|---|---|
| `chat.py` | Conversational agent, its tools, and system prompt |
| `grafo.py` | Drafting workflow (`StateGraph`) |
| `intake.py` | Domain: reference projects, fit rules, brief schema, drafting prompt |
| `api.py` | HTTP endpoint, limits, background drafting |
| `db.py` | SQLite connection, checkpointer, session table |
| `mantenimiento.py` | Classification, retention, reporting, erasure |
| `interno.py` | Internal brief as an A4 document and PDF |
| `deck.py` | Proposal slides (HTML, guria.lat design) and PDF export |
| `avisos.py` | Team notifications through the webhook |
