# Phase C1 — Collaborative Rooms (chat + shared paper portfolio + grounded AI)

A room is a two-person workspace containing **one chat**, **one shared paper
portfolio**, and **one AI assistant that can read both**. The chat becomes the
decision log for the trades placed in that room, rather than a separate
conversation happening next to the trading screen.

## The one rule that shapes the design

> The AI can see everything the humans see. Only a human can place an order.

This is enforced structurally, not by prompt wording. The assistant's entire
tool surface lives in `app/collab/ai/tools.py` and contains no write
operations. `RoomService.place_order` is never exposed to a model. A test
(`test_no_tool_can_place_an_order`) asserts this so it cannot regress silently.

## Module layout

```
app/collab/
├── schemas.py             # Pydantic contracts (rooms, messages, trade ideas, WS frames)
├── models.py              # SQLAlchemy ORM: chat_rooms, chat_room_members, chat_messages
├── repository.py          # CRUD only
├── room_service.py        # Public surface: membership, messages, shared orders
├── connection_manager.py  # Per-room WebSocket fan-out
├── exceptions.py
└── ai/
    ├── tools.py           # Read-only tools over MarketDataGateway + room book
    ├── providers.py       # Gemini (primary) + Groq (fallback), raw httpx
    └── agent.py           # Provider chain, fallback, graceful degradation
```

`RoomService` is the only intended entry point, mirroring how
`MarketDataGateway` fronts the market-data repositories. Repositories and ORM
models are internal implementation details.

## Shared portfolio

Each room owns one `PaperTradingBook` (the existing A5.2 `SimulatedBroker`),
held in `RoomBookRegistry` keyed by `room_id`:

* The dashboard's global `get_paper_book()` singleton is **untouched** — the
  existing single-user dashboard keeps its own book.
* Rooms are isolated from each other (`test_rooms_have_isolated_books`).
* Order placement is serialized per room behind an `asyncio.Lock`, so two
  members clicking buy at the same instant cannot interleave broker mutations
  or race on SQLite writes.
* Every order outcome — filled **or rejected** — is written into the chat as an
  `ORDER_EVENT` message. That is what turns the room into a decision log.

## Message kinds

| Kind | Meaning |
|---|---|
| `CHAT` | Plain message from a member |
| `TRADE_IDEA` | Structured call: symbol, direction, thesis, entry/stop/target |
| `ORDER_EVENT` | A paper order was filled or rejected |
| `AI_REPLY` | Assistant answer, tagged with provider and tools consulted |
| `SYSTEM` | Joins, notices |

Trade ideas are stamped with `price_at_post` at write time. That single field
is what makes a call scoreable later without reconstructing when it was made —
the basis for per-person accuracy tracking.

## AI grounding

Seven read-only tools:

| Tool | Reads from |
|---|---|
| `get_latest_price` | Stored Parquet OHLCV via `MarketDataGateway` |
| `get_price_history` | Same, summarised (not raw bars) |
| `get_room_portfolio` | The room's shared book |
| `get_position` | The room's shared book |
| `get_recent_orders` | The room's order log |
| `get_recent_trade_ideas` | Room chat history |
| `get_strategy_analysis` | Your existing strategy engine |

`get_price_history` returns a **summary** (start/end close, % change, period
high/low, averages, last ten closes) rather than dumping bars. This keeps the
prompt small and stops the model doing arithmetic it gets wrong.

The system prompt forbids stating any price or position from memory, and
requires the model to say so plainly when a tool reports data is unavailable.

### Provider chain and fallback

Gemini is primary, Groq is fallback (reversible via `AI_PRIMARY_PROVIDER`).
Both are called over plain HTTP with `httpx` — already a project dependency —
so no vendor SDK is added.

* Unconfigured providers are dropped from the chain.
* If the primary errors, times out, or rate-limits, the next provider runs and
  the reply is tagged `fell_back: true`.
* If **all** providers fail, `ask()` returns an `AIReply` carrying the error
  instead of raising. The assistant says it cannot reach a provider and
  explicitly refuses to guess numbers. A dead API key never takes down a room,
  and never produces invented prices.

### Failing early and saying why

Two configuration mistakes look identical from a room — the assistant simply
says it cannot answer — so both are caught at startup instead:

* **A key of the wrong shape or a rejected key.** Each provider is probed once
  with a free `GET /models` call. A 400/401/403 becomes an `AIAuthError`
  carrying a one-line fix rather than a raw JSON blob, logged as a `WARNING`
  naming the environment variable. An AI Studio key starts `AIza`; a Groq key
  starts `gsk_`. A key that does not is flagged before the call is even made.
* **A retired model id.** A valid key with a decommissioned `GROQ_MODEL` or
  `GEMINI_MODEL` fails only on the first real call, with a 404. The same probe
  compares the configured model against the account's model list and names
  working alternatives.

Keys are stripped of wrapping quotes and whitespace when settings load —
pasting `GEMINI_API_KEY="AIza..."` into `.env` is otherwise an opaque 400.

Neither check can stop the server: an unreachable provider at boot may be fine
minutes later, and a broken assistant must never block chat or trading.

`GET /ai/status` carries the most recent failure as `last_error`
(`provider`, `reason`, `hint`, `is_auth_error`, `occurred_at`), with any key
material redacted, so the room UI can say "Gemini key invalid" rather than
"something went wrong".

Wire formats differ enough that each provider owns its own tool-calling loop:
Gemini uses `tools[].functionDeclarations` / `parts[].functionCall` /
`parts[].functionResponse`; Groq is OpenAI-compatible with `tool_calls` and
`role: "tool"` messages.

## API surface

All under `/api/v1/collab`.

| Method | Path | Purpose |
|---|---|---|
| POST | `/rooms` | Create a room (allocates its shared book) |
| GET | `/rooms` | List rooms with online rosters |
| GET | `/rooms/{id}` | Room detail |
| DELETE | `/rooms/{id}` | Delete room, messages, and book |
| POST | `/rooms/{id}/join?user=` | Join (capacity-checked) |
| POST | `/rooms/{id}/leave?user=` | Leave |
| GET | `/rooms/{id}/messages` | History, oldest first |
| POST | `/rooms/{id}/messages` | Post chat |
| POST | `/rooms/{id}/trade-ideas` | Post a structured idea |
| GET | `/rooms/{id}/portfolio` | Shared portfolio |
| GET | `/rooms/{id}/orders` | Shared order log |
| POST | `/rooms/{id}/orders` | Place a paper order |
| POST | `/rooms/{id}/ai` | Ask the assistant |
| GET | `/ai/status` | Which providers are configured (never exposes keys) |
| WS | `/ws/rooms/{id}?user=` | Live channel |

REST routes exist so every action is scriptable and testable without a socket
client; the WebSocket is the primary interface.

### WebSocket protocol

Client → server:

```json
{"type": "chat",       "text": "@ai what did RELIANCE close at?"}
{"type": "trade_idea", "idea": {"symbol": "RELIANCE", "direction": "LONG", "thesis": "..."}}
{"type": "order",      "order": {"side": "BUY", "symbol": "RELIANCE", "quantity": 10}}
{"type": "history",    "limit": 50}
{"type": "ping"}
```

Server → client: `history`, `message`, `presence`, `portfolio`, `ai_thinking`,
`error`, `pong`.

Notes:

* The order `author` is **forced to the socket's authenticated user**, so a
  client cannot place an order in someone else's name.
* A DB session is opened per frame rather than held for the socket's lifetime,
  keeping SQLite connections short-lived under concurrent members.
* One malformed frame returns an `error` and leaves the socket usable.
* A refused join is **accepted and then closed** with code `4404` (no such
  room) or `4409` (room full). Closing before the handshake completes would
  make the server return a bare HTTP 403, which a browser reports as `1006` —
  indistinguishable from a dropped network.
* A message containing `@ai` (configurable via `AI_TRIGGER`) routes to the
  assistant. Plain chat never calls the model — that is what keeps token cost
  near zero while two people talk.

## Configuration

```env
COLLAB_ENABLED=true
CHAT_HISTORY_LIMIT=50
ROOM_DEFAULT_CAPACITY=2

AI_ENABLED=true
AI_PRIMARY_PROVIDER=gemini      # or groq
GEMINI_API_KEY=                 # https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.0-flash
GROQ_API_KEY=                   # https://console.groq.com/keys
GROQ_MODEL=openai/gpt-oss-120b
AI_TRIGGER=@ai
AI_TIMEOUT_SECONDS=45
AI_MAX_TOOL_ITERATIONS=5
AI_MAX_OUTPUT_TOKENS=800
```

`AI_MAX_OUTPUT_TOKENS` and the `@ai`-only trigger are the two levers that keep
LLM spend predictable — the one cost in this feature that no cloud free tier
covers.

## Quick start

```bash
uvicorn app.main:app --reload --port 8080

# Bootstrap a symbol first, or every price tool reports "unavailable"
curl -X POST http://127.0.0.1:8080/api/v1/market/bootstrap/RELIANCE.NS

# Create a room
curl -X POST http://127.0.0.1:8080/api/v1/collab/rooms \
  -H 'Content-Type: application/json' \
  -d '{"name":"Nifty Desk","created_by":"sahil"}'

# Two-terminal demo client (see scripts/collab_demo_client.py)
python scripts/collab_demo_client.py --room <ROOM_ID> --user sahil
```

## Frontend

`/rooms` lists and creates rooms; `/rooms/:roomId` is the room itself — a real
URL, so opening the same room in two tabs is the whole two-person demo.

```
frontend/src/
├── types/collab.ts              # mirrors app/collab/schemas.py
├── api/collab.ts                # REST: list, create, join, portfolio, ai/status
├── hooks/useRoomSocket.ts       # the live channel
├── components/room/
│   ├── MembersPanel.tsx         # left:   roster + presence + connection state
│   ├── ChatStream.tsx           # centre: transcript + composer
│   ├── MessageRow.tsx           # one row per MessageKind
│   └── PortfolioPanel.tsx       # right:  shared book, order + idea forms
└── pages/RoomsPage.tsx, RoomPage.tsx
```

Each `MessageKind` renders differently because the transcript doubles as the
decision log: a `TRADE_IDEA` leads with **price when posted**, an
`ORDER_EVENT` is a green or red system row carrying its rejection reason, and
an `AI_REPLY` shows the provider badge plus the tools that grounded it. There
is no UI anywhere that lets the assistant place an order.

Two socket behaviours are load-bearing:

* **No local echo.** The server broadcasts the author's own message back, so
  the composer never appends optimistically. Messages are keyed by
  `message_id`, which also de-duplicates the history replayed on reconnect.
  (`scripts/collab_demo_client.py` double-prints for want of this.)
* **Refusals are not retried.** `4404` and `4409` end the connection with a
  specific message; anything else reconnects with exponential backoff.

The handle is held in React state, never `localStorage`, so two tabs on one
machine can be two different people.

## Deploying on AWS free tier

| Piece | Service | Cost |
|---|---|---|
| API + WebSocket | Lambda + API Gateway, or EC2 t3.micro | Lambda Always Free; EC2 draws credits on post-July-2025 accounts |
| Chat + room data | Current SQLite works for two users; DynamoDB (Always Free, 25 GB) or RDS Postgres for real concurrency | Free within limits |
| OHLCV Parquet | S3 | ~Free at this scale |
| Scheduled ingestion | EventBridge + Lambda | Always Free |
| Logs and alarms | CloudWatch | 10 metrics/alarms free |
| **LLM replies** | **Gemini / Groq** | **Not covered by any AWS tier — budget separately** |

The `ConnectionManager` holds sockets in process memory and assumes a single
uvicorn worker. Multiple workers would need a shared pub/sub broker (Redis or
similar), which is deliberately out of scope for a two-person room.

## Tests

```bash
python -m pytest tests/collab -q
```

53 tests: room lifecycle and capacity, chat and membership enforcement, trade
idea price stamping, shared-book isolation and order logging, all seven AI
tools, trigger parsing, both provider transports with mocked HTTP (including
full tool round-trips), provider chain ordering, Gemini→Groq fallback,
all-providers-down degradation, and the WebSocket channel end to end.
