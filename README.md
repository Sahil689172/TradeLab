# TradeLab

AI-powered Indian Stock Market Analysis Platform — **Quant Engine** foundation.

This repository currently contains **Phase A1: Quant Foundation** — a clean, minimal FastAPI backend ready for the Indian Market Data Service (Phase A2).

## Features (Phase A1)

- FastAPI application factory with lifespan hooks
- Environment-based configuration (Pydantic Settings + python-dotenv)
- SQLite + SQLAlchemy engine, session dependency, and declarative base
- Structured console logging (startup, shutdown, requests, exceptions)
- Global exception handlers with consistent JSON error envelopes
- `GET /` root metadata and `GET /health` connectivity check
- Versioned API mount at `/api/v1`
- OpenAPI, Swagger UI (`/docs`), and ReDoc (`/redoc`)
- Pytest suite for health, root, startup, and database initialization

## Requirements

- Python **3.12+**
- pip

## Project setup

```bash
# Clone / enter the project
cd TradeLab

# Create and activate a virtual environment (Windows PowerShell)
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt

# Copy environment file
copy .env.example .env
```

On macOS/Linux:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Running locally

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Then open:

| Resource | URL |
|----------|-----|
| Root | http://127.0.0.1:8000/ |
| Health | http://127.0.0.1:8000/health |
| API v1 | http://127.0.0.1:8000/api/v1/ |
| Swagger UI | http://127.0.0.1:8000/docs |
| ReDoc | http://127.0.0.1:8000/redoc |
| OpenAPI JSON | http://127.0.0.1:8000/openapi.json |

## Environment variables

Configured via `.env` (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_NAME` | Application name | `TradeLab` |
| `APP_VERSION` | Semantic version | `0.1.0` |
| `APP_DESCRIPTION` | Short description | TradeLab Quant Engine… |
| `APP_ENV` | `development` / `staging` / `production` / `test` | `development` |
| `DEBUG` | Debug mode | `true` |
| `API_V1_PREFIX` | Versioned API prefix | `/api/v1` |
| `HOST` | Bind host (for reference) | `0.0.0.0` |
| `PORT` | Bind port (for reference) | `8000` |
| `DATABASE_URL` | SQLAlchemy URL | `sqlite:///./data/tradlab.db` |
| `LOG_LEVEL` | `DEBUG`/`INFO`/`WARNING`/`ERROR`/`CRITICAL` | `INFO` |
| `LOG_FORMAT` | `console` or `json` | `console` |

The SQLite data directory is created automatically on startup when needed.

## Running tests

```bash
pytest
```

Tests use an isolated temporary SQLite database and do not touch `./data/tradlab.db`.

## Project structure

```text
TradeLab/
├── app/
│   ├── api/
│   │   ├── routes/
│   │   │   ├── system.py      # GET /, GET /health
│   │   │   └── v1_root.py     # GET /api/v1
│   │   └── router.py
│   ├── core/
│   │   ├── config.py          # Settings / env loading
│   │   ├── exceptions.py      # Global error handlers
│   │   └── logging.py         # Logging setup
│   ├── db/
│   │   ├── base.py            # SQLAlchemy DeclarativeBase
│   │   └── session.py         # Engine, sessions, init
│   ├── middleware/
│   │   └── request_logging.py
│   ├── schemas/
│   │   └── responses.py       # Standard response models
│   ├── __init__.py
│   └── main.py                # Application factory
├── tests/
│   ├── conftest.py
│   └── test_system.py
├── docs/                      # Phase 0 architecture docs
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

## Architecture (A1)

Layered and separated:

- **API routes** — HTTP only; no business logic
- **Core** — configuration, logging, exceptions
- **DB** — engine/session/base isolated from routes
- **Schemas** — Pydantic response contracts
- **Middleware** — cross-cutting request logging

Dependency injection is used for `Settings` and the SQLAlchemy engine/session.

## Out of scope (not in A1)

Authentication, users, JWT, market data, indicators, ML, Monte Carlo, strategies, paper trading, AWS, Docker, and collaboration features are intentionally omitted and will arrive in later phases.
