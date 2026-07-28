# TradeLab — Technology Decisions

**Document type:** Phase 0 planning  
**Purpose:** Record *why* the chosen stack fits TradeLab Quant Engine v1, with alternatives considered.

---

## 1. Backend Framework — FastAPI (not Flask / Django)

### Decision
Use **FastAPI** as the HTTP framework.

### Why FastAPI
- Native **async** support and excellent sync interop for scientific libraries.
- First-class **Pydantic** validation and automatic **OpenAPI** docs — critical for API-first Phase A/C.
- Dependency injection fits JWT auth and DB sessions cleanly.
- High performance (Starlette/Uvicorn) sufficient for modular monolith on EC2.
- Strong typing culture aligns with maintainability NFRs.

### Alternatives

| Alternative | Pros | Cons vs TradeLab |
|-------------|------|------------------|
| **Flask** | Simple, familiar | Weaker built-in validation/OpenAPI; more boilerplate for large API surface |
| **Django + DRF** | Batteries-included admin/ORM | Heavier; less ideal for ML-centric modular engines; slower iteration for pure API |
| **Litestar / Starlette raw** | Fast | Smaller ecosystem / more DIY than FastAPI |

### Verdict
FastAPI best balances productivity, validation, docs, and performance for a quant API.

---

## 2. Database — PostgreSQL (not SQLite / MySQL alone)

### Decision
Use **PostgreSQL** as the system of record.

### Why PostgreSQL
- Robust **concurrency**, constraints, and indexing for multi-user SaaS-style data.
- Excellent support for **Numeric**, **JSON/JSONB** (strategy definitions, metrics, configs).
- Production-proven on AWS (RDS or self-managed on EC2 sibling host).
- Smooth path when splitting microservices later (logical databases / schemas).

### Alternatives

| Alternative | Pros | Cons |
|-------------|------|------|
| **SQLite** | Zero ops locally | Weak concurrent writes; not suitable as cloud multi-user primary store |
| **MySQL/MariaDB** | Common hosting | JSON/constraint ergonomics and tooling slightly less ideal for this design; team standardizes on Postgres |
| **MongoDB** | Flexible docs | Weaker relational integrity for orders, positions, FKs to versions |

### Verdict
SQLite may appear only as a *dev convenience* if ever — **not** the v1 architecture target. PostgreSQL is required for Phase A persistence design.

---

## 3. ORM & Migrations — SQLAlchemy + Alembic

### Decision
**SQLAlchemy 2.x** style ORM/Core + **Alembic** migrations.

### Why
- Clear separation: models/repositories vs services.
- Alembic provides reviewable, versioned schema evolution (NFR reliability).
- Mature Postgres support; works well with FastAPI session patterns.

### Alternatives
- **Raw SQL** — maximum control, poor velocity/safety for a broad domain model.
- **Django ORM** — couples to Django.
- **Prisma/other** — not idiomatic in Python quant stacks.
- **SQLModel** — convenient but thinner community for complex migrations; can be reconsidered later without changing Postgres.

---

## 4. Validation / Schemas — Pydantic

### Decision
**Pydantic v2** for request/response and settings.

### Why
- Integrated with FastAPI.
- Enforces API contracts for Phase C clients.
- Settings management via `BaseSettings` reduces config bugs.

### Alternatives
- Marshmallow / attrs — more glue with FastAPI.
- Dataclasses alone — weaker validation/serialization story.

---

## 5. Authentication — JWT (not server sessions alone)

### Decision
**JWT** access tokens + refresh tokens.

### Why
- **Stateless** API instances — scales horizontally later behind a load balancer.
- Natural fit for SPA frontend (Phase C) and future collaboration service trust boundaries.
- Refresh flow limits exposure of long-lived credentials.

### Alternatives

| Alternative | Pros | Cons |
|-------------|------|------|
| **Server-side sessions** | Easy revocation | Sticky session store required; less ideal for multi-service future |
| **OAuth2/OIDC only (Auth0/Cognito)** | Managed identity | Extra vendor cost/complexity for v1; can add later as IdP |
| **API keys only** | Simple | Poor end-user auth UX |

### Verdict
JWT for v1; optional upgrade path to Cognito/Auth0 later without changing domain modules.

---

## 6. Testing — Pytest

### Decision
**Pytest** as the sole primary test runner.

### Why
- De-facto Python standard; excellent fixtures and parametrization.
- Works cleanly with FastAPI TestClient and async plugins if needed.
- Fits engine-level unit testing without HTTP.

### Alternatives
- `unittest` — more verbose.
- Nose — legacy.

---

## 7. Market Data — yfinance (NSE via Yahoo symbols)

### Decision
**yfinance** for NSE historical OHLCV in v1.

### Why
- Fast path to **NSE** symbols (e.g., `*.NS`) without broker contracts.
- Adequate for research, indicators, backtests, and paper reference prices.
- Free/low friction for early product development.

### Alternatives

| Alternative | Pros | Cons |
|-------------|------|------|
| **Official exchange / paid vendors** (NSE data vendors, Polygon, etc.) | Quality, licensing clarity | Cost, contracts, integration time |
| **Broker APIs** | Trading-adjacent | Out of scope for v1; auth/regulatory overhead |
| **Direct scraping** | — | Fragile, ToS risk — rejected |

### Risks & mitigations
- Availability/rate limits → **cache in Postgres**, backoff, fixtures in CI.
- Data quality quirks → document adjusted close behavior; allow force refresh.
- Abstraction: `MarketDataProvider` interface so vendor can change later.

---

## 8. Technical Indicators — pandas-ta (preferred) vs `ta`

### Decision
Prefer **pandas-ta**; keep a thin **IndicatorEngine** adapter so `ta` can substitute.

### Why pandas-ta
- Broad indicator coverage and pandas-native workflows.
- Aligns with DataFrame-centric feature engineering for ML.

### Why not hard-bind the API to one library
- Library APIs change; adapter protects services/routes.
- Some environments have install friction — fallback option documented.

### Alternatives
- **ta-lib** — fast/C-based but painful binary installs on some hosts.
- Hand-rolled indicators — error-prone, reinventing tested formulas.

---

## 9. Machine Learning — scikit-learn + XGBoost (+ pandas/numpy)

### Decision
**scikit-learn** for baseline models/pipelines; **XGBoost** for strong tabular performance; **pandas/numpy** for features/matrices.

### Why scikit-learn
- Standard preprocessing, metrics, classical models; excellent for v1 baselines and teaching/research UX.

### Why XGBoost
- State-of-the-art practical performance on **tabular financial features**.
- Predictable train/infer APIs; artifacts easy to serialize.
- Widely understood hyperparameters for experimentation.

### Alternatives

| Alternative | Pros | Cons for v1 |
|-------------|------|-------------|
| **PyTorch / TensorFlow** | Deep learning | Heavier ops, longer train times, overkill for first tabular predictors |
| **LightGBM / CatBoost** | Strong boosters | Can add later; XGBoost sufficient as primary booster |
| **AutoML** | Convenience | Less control, heavier deps |

### Architecture note
ML code lives in an **engine package** independent of FastAPI — required for testability and future ML service extraction.

---

## 10. Deployment — AWS EC2 + S3 + CloudWatch (no Docker in v1)

### Decision
Run the app on **EC2**; artifacts on **S3**; logs/metrics via **CloudWatch**.

### Why EC2
- Straightforward VM hosting matching “no Docker in v1.”
- Full control of Python scientific stack installs.
- Enough for modular monolith until scale demands containers/orchestration.

### Why S3
- Durable, cheap object storage for **models, large simulation outputs, reports**.
- Keeps PostgreSQL lean.
- Natural share point for Phase B file features later.

### Why CloudWatch
- Native AWS observability without extra vendors in v1.
- Log groups + alarms for EC2 health and error rates.

### Alternatives

| Alternative | Pros | Cons vs stated v1 |
|-------------|------|-------------------|
| **Docker on EC2 / ECS / EKS** | Reproducible deploys | Explicitly out of v1 scope |
| **Heroku/Render** | Simpler PaaS | Less alignment with chosen AWS artifact/monitoring story |
| **Lambda** | Serverless | Poor fit for long ML/backtests and scientific deps without heavy design |

### Future
Containerize in Phase A+ when release repeatability becomes a bottleneck.

---

## 11. Explicit Non-Choices (v1)

| Technology | Status |
|------------|--------|
| Docker / Compose / Kubernetes | Out of scope v1 |
| Celery/RQ/SQS | Deferred unless job load requires (design allows addition) |
| Redis | Optional later for cache/rate limit; not required to start |
| WebSockets for market data | Out of scope v1 |
| Microservices runtime | Modular monolith first |

---

## 12. Decision Summary Table

| Area | Choice | Primary reason |
|------|--------|----------------|
| API | FastAPI | Typing, OpenAPI, speed, DI |
| DB | PostgreSQL | Integrity, JSONB, production multi-user |
| ORM | SQLAlchemy + Alembic | Clean layers + migrations |
| Auth | JWT | Stateless, frontend-ready |
| Tests | Pytest | Ecosystem standard |
| Market data | yfinance | NSE access, speed to value |
| Indicators | pandas-ta (+ adapter) | Coverage + pandas fit |
| ML | sklearn + XGBoost | Tabular strength, simplicity |
| Numerics | pandas + numpy | Dataframe/array standard |
| Deploy | EC2 | No-Docker v1 hosting |
| Artifacts | S3 | Blob offload |
| Monitoring | CloudWatch | Native AWS ops |

---

## 13. Revisit Triggers

Reconsider a decision if:

- yfinance becomes unreliable → paid market data provider behind same interface.
- Train/backtest jobs overwhelm EC2 process → introduce queue workers (still without requiring full k8s).
- Multiple services need shared login → move to managed OIDC.
- Team shipping friction dominates → introduce Docker despite v1 exclusion (as a version bump decision).
