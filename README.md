# TradeLab

AI-powered Indian Stock Market Analysis Platform — **Quant Engine**.

This repository contains:

- **Phase A1** — FastAPI application foundation
- **Phase A2.1** — Market data storage infrastructure (SQLite + Parquet)
- **Phase A2.2** — Yahoo Finance ingestion, bootstrap, incremental sync, market API

## Features

### Phase A1 — Quant Foundation

- FastAPI application factory with lifespan hooks
- Environment-based configuration (Pydantic Settings + python-dotenv)
- Structured console logging and global exception handlers
- `GET /` root metadata and `GET /health` connectivity check
- Versioned API mount at `/api/v1`
- OpenAPI, Swagger UI (`/docs`), and ReDoc (`/redoc`)

### Phase A2.1 — Market Data Storage

- Configurable storage paths (no hardcoded directories)
- SQLite metadata database (`backend/data/metadata.db`)
- Parquet OHLCV file store (`backend/data/ohlcv/`)
- ORM models: `company_metadata`, `ingestion_state`
- Pydantic contracts: `CompanyMetadata`, `IngestionState`, `OHLCVRecord`
- Repository layer (SQLite + Parquet) with CRUD only
- OHLCV validator before Parquet writes
- `MarketDataGateway` as the single public storage interface
- Comprehensive unit tests (no download/API/ingestion logic)

### Phase A2.2 — Market Data Ingestion

- Yahoo Finance provider abstraction and implementation
- First-time bootstrap for new symbols
- Incremental update engine using `last_available_date`
- Metadata synchronization into SQLite
- Gateway orchestration for bootstrap/update/metadata refresh
- Market ingestion API endpoints under `/api/v1/market/*`
- Mock-based provider and API test coverage

## Requirements

- Python **3.12+**
- pip

## Project setup

```bash
cd TradeLab
python -m venv .venv
.\.venv\Scripts\Activate.ps1    # Windows
pip install -r requirements.txt
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

| Resource | URL |
|----------|-----|
| Root | http://127.0.0.1:8000/ |
| Health | http://127.0.0.1:8000/health |
| API v1 | http://127.0.0.1:8000/api/v1/ |
| Market bootstrap | http://127.0.0.1:8000/api/v1/market/bootstrap/RELIANCE.NS |
| Swagger UI | http://127.0.0.1:8000/docs |
| ReDoc | http://127.0.0.1:8000/redoc |
| **Dashboard UI** | http://127.0.0.1:5173/ (see `frontend/README.md`) |

### Trading dashboard (frontend + API)

Backend dashboard routes live under `/api/v1/` (`stocks`, `strategies`, `portfolio`, `orders`, `market-data/refresh`, `system/status`). Paper buy/sell uses the existing A5.2 `SimulatedBroker` — no live broker.

```bash
# Terminal 1 — API
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Terminal 2 — UI
cd frontend
npm install
npm run dev
```

Bootstrap at least one symbol before charts/strategies (e.g. `POST /api/v1/market/bootstrap/RELIANCE` or use **Refresh Data** in the UI).


```text
backend/data/metadata.db
backend/data/ohlcv/     # Parquet history files created by bootstrap/update
backend/data/logs/
```

## Environment variables

| Variable | Description | Default |
|----------|-------------|---------|
| `APP_NAME` | Application name | `TradeLab` |
| `APP_VERSION` | Semantic version | `0.1.0` |
| `APP_ENV` | Runtime environment | `development` |
| `DEBUG` | Debug mode | `true` |
| `API_V1_PREFIX` | Versioned API prefix | `/api/v1` |
| `METADATA_DATABASE_URL` | SQLite URL for metadata | `sqlite:///backend/data/metadata.db` |
| `PARQUET_STORAGE_DIR` | OHLCV Parquet directory | `backend/data/ohlcv` |
| `LOG_DIRECTORY` | Log file directory | `backend/data/logs` |
| `DATABASE_URL` | App DB URL (health check) | `sqlite:///backend/data/metadata.db` |
| `BOOTSTRAP_HISTORY_YEARS` | First-time history window | `10` |
| `YFINANCE_TIMEOUT_SECONDS` | Provider timeout | `30` |
| `LOG_LEVEL` | Log level | `INFO` |
| `LOG_FORMAT` | `console` or `json` | `console` |

## Running tests

```bash
python -m pytest
```

Tests use isolated temporary directories and do not modify committed storage paths.

## Project structure

```text
TradeLab/
├── app/
│   ├── api/                   # HTTP routes (Phase A1)
│   ├── core/
│   │   ├── config.py          # Settings
│   │   ├── database.py        # SQLAlchemy engine/session/base
│   │   ├── storage_paths.py   # Directory initialization
│   │   ├── exceptions.py
│   │   └── logging.py
│   ├── db/                    # Re-exports from core.database
│   ├── market_data/           # Phase A2.x market data module
│   │   ├── models/            # SQLAlchemy ORM
│   │   ├── providers/         # Yahoo Finance integration
│   │   ├── schemas/           # Pydantic contracts
│   │   ├── repositories/      # SQLite + Parquet CRUD
│   │   ├── validators/        # OHLCV validation
│   │   ├── services/          # Gateway + bootstrap/update services
│   │   └── exceptions.py
│   ├── middleware/
│   ├── schemas/               # API response models
│   └── main.py
├── backend/data/
│   ├── ohlcv/                 # Parquet files (empty initially)
│   └── logs/
├── tests/
│   ├── test_system.py
│   └── market_data/           # Storage layer tests
├── docs/                      # Architecture documentation
├── requirements.txt
└── README.md
```

## Storage architecture

Future modules (ingestion, indicators, ML, backtesting, etc.) must use **`MarketDataGateway`** only:

```python
from app.core.database import get_session_factory
from app.market_data.services import MarketDataGateway

session = get_session_factory()()
gateway = MarketDataGateway(session)
```

Repositories and validators remain internal implementation details.

## Out of scope (not in A2.2)

indicators, feature engineering, ML, Monte Carlo, backtesting, paper trading, schedulers, caching, and non-market modules.
