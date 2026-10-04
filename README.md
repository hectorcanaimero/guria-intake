# guria-intake

Conversational intake agent for [guria.lat](https://guria.lat), an AI engineering practice serving businesses in Brazil and Latin America.

A visitor describes their project in a chat widget. The agent asks follow-up questions until the problem is clear, confirms a summary, and hands off. A LangGraph workflow then drafts an internal brief (scope, risks, effort range, open questions, related past work) for review before anyone replies. Conversations are persisted, classified nightly, and summarized in a weekly report, so the agent improves through reviewed changes rather than learning from raw chat input.

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
                                      └(clear)─▶ buscar → redactar ⇄ revisar
```

**Two parts with different jobs.** Conversation is open-ended, so it is an agent. Drafting is a known process, so it is a fixed graph where the model only works inside nodes (`triage`, `redactar`) and everything verifiable runs as plain code.

**Rules live in code, not prompts.** `revisar` checks the draft against the declared budget, inverted ranges, and invented references, and sends it back to `redactar` at most twice. Session state, turn limits, and rate limits are enforced by the API, so a closed session never reaches the model.

**No prices to clients.** Client-facing output never includes prices or dates. Estimates exist only in the internal brief.

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
- **LangSmith**: tracing (optional)

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync
cp .env.example .env   # fill in the values below
uv run --env-file .env uvicorn api:app --port 8000
```

| Variable | Purpose |
|---|---|
| `ROUTER_BASE_URL`, `ROUTER_API_KEY`, `ROUTER_MODEL` | OpenAI-compatible endpoint and model for the chat and drafting |
| `TYPESAFE_API_KEY` | Jev, for nightly classification (`TYPESAFE_MODEL` defaults to `jev-latest`) |
| `REPORTE_WEBHOOK_URL`, `XAPI` | Weekly report webhook and the value sent in its `xapi` header |
| `LANGSMITH_TRACING`, `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | Optional tracing |
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

## Privacy

Built for LGPD. The chat widget on guria.lat tells visitors the conversation is stored, why, and for how long. Sessions that became leads are kept for 12 months and all others for 90 days. `borrar` removes a person's checkpoints, session row, and stored intake in one step.

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
