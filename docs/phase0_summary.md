# TradeLab — Phase 0 Summary

**Status:** Planning complete (documentation only)  
**Date context:** Phase 0 kickoff  
**Code produced:** None (by design)

---

## 1. Completed Planning Documents

All artifacts live under `docs/`:

| # | Document | Purpose |
|---|----------|---------|
| 1 | [system_overview.md](./system_overview.md) | Vision, objectives, scope, out of scope, features, roadmap |
| 2 | [functional_requirements.md](./functional_requirements.md) | Must/should requirements for all Quant domains |
| 3 | [non_functional_requirements.md](./non_functional_requirements.md) | Performance, security, reliability, scale, testing, logging, monitoring |
| 4 | [system_architecture.md](./system_architecture.md) | Modular monolith layers, subsystems, data flows, lifecycle, Mermaid diagrams |
| 5 | [database_design.md](./database_design.md) | Entities, relationships, indexes, normalization (no SQL) |
| 6 | [api_design.md](./api_design.md) | REST endpoint contracts (no implementation) |
| 7 | [development_guidelines.md](./development_guidelines.md) | Standards, Git, commits, testing, errors, logging, env vars |
| 8 | [project_roadmap.md](./project_roadmap.md) | Phase A modules A1–A11 + Phase B/C summary |
| 9 | [technology_decisions.md](./technology_decisions.md) | Rationale and alternatives for the stack |
| 10 | [phase0_summary.md](./phase0_summary.md) | This summary |

**Not created (intentionally):** Python packages, FastAPI app, placeholder APIs, empty module folders, SQL migrations, Docker files.

---

## 2. Major Architectural Decisions

1. **Modular monolith first** — one FastAPI deployable on EC2; domain modules loosely coupled for later microservice extraction.
2. **Strict layering** — Routers → Services → Engines/Domain → Repositories/Gateways; ML/engines must not import FastAPI.
3. **PostgreSQL + SQLAlchemy + Alembic** as system of record; **S3** for model artifacts, large simulation outputs, and report blobs.
4. **JWT auth** with access + refresh tokens; ownership checks on all user resources.
5. **yfinance** behind a `MarketDataProvider` adapter for NSE historical data, with DB caching.
6. **pandas-ta** preferred for indicators via an adapter interface.
7. **scikit-learn + XGBoost** for tabular prediction; versioned model registry.
8. **Declarative strategy JSON DSL** (no user code execution) with immutable **strategy versions** for backtests.
9. **Paper trading only** in v1 — no live broker execution.
10. **No Docker in v1** — systemd-style EC2 process; CloudWatch for logs/metrics.
11. **Job pattern** for long-running train/backtest/Monte Carlo (exact runner TBD — see open decisions).

---

## 3. Risks Identified

| Risk | Impact | Mitigation |
|------|--------|------------|
| **yfinance reliability / rate limits / ToS changes** | Market data and all dependents fail or degrade | Cache aggressively; provider adapter; fixtures in CI; plan paid vendor fallback |
| **Long-running ML/backtest on same web process** | Timeouts, blocked workers, unstable UX | Decide job runner early; caps on paths/bars; move to background workers in A+ |
| **Indicator / equity time-series table growth** | DB bloat, slow queries | Index carefully; optional S3/Parquet storage decision before heavy use |
| **Strategy DSL ambiguity** | Backtests diverge from user intent | Freeze schema early; golden-file tests; version definitions |
| **Overfitting / misleading ML & backtest results** | Product trust issues | Document limitations; metrics honesty; disclaimers for Phase C |
| **Secret/config mismanagement on EC2** | Security incident | Env/IAM roles; no secrets in git; guidelines enforced |
| **Scope creep into Phase B/C during Phase A** | Delayed Quant Engine | Keep collaboration/frontend out of A modules; only extension points (e.g., report IDs) |
| **Scientific dependency installs on EC2** | Deploy friction without Docker | Document OS packages; pin versions; smoke install in A11 |
| **Single-instance availability** | Downtime on deploy/failure | Accept for v1; backups; health checks; maintenance window process |

---

## 4. Recommended Implementation Order

Follow Phase A modules as sequenced in `project_roadmap.md`:

1. **A1 Foundation** — app skeleton, DB, logging, health  
2. **A2 Auth** — JWT users  
3. **A3 Market Data** — yfinance + OHLCV cache  
4. **A4 Indicators** — pandas-ta engine  
5. **A5 Strategy Builder** — versioned DSL  
6. **A6 Backtesting** — engine + metrics  
7. **A7 Prediction** — train/serve ML (can overlap staffing with A6)  
8. **A8 Monte Carlo** — can proceed after A3 in parallel with A5–A7  
9. **A9 Paper Trading** — after A3; parallelizable with A6–A8  
10. **A10 Reports** — after core artifacts exist  
11. **A11 Hardening & EC2 deploy** — finalize production v1  

Then **Phase B (Collaboration)** → **Phase C (Frontend)**.

---

## 5. Decisions Needed Before Phase A Begins

Resolve these explicitly to avoid rework:

| # | Decision | Options / Notes |
|---|----------|-----------------|
| 1 | **Python version** | Recommend pin 3.11 or 3.12 |
| 2 | **Package manager** | poetry / uv / pip-tools — pick one |
| 3 | **Async job runner for v1** | FastAPI BackgroundTasks vs DB job table + worker loop vs defer queue (RQ/Celery/SQS) |
| 4 | **Postgres hosting** | RDS vs Postgres on same/other EC2 |
| 5 | **S3 for local dev** | Real S3 vs LocalStack/minio vs filesystem fallback flag |
| 6 | **Indicator series storage** | Relational `IndicatorValue` rows vs S3 blobs for series |
| 7 | **Central `Job` table** | Unified polling vs per-domain status only |
| 8 | **Paper trading policy** | Short selling on/off; one account vs many |
| 9 | **Fill model defaults** | Backtest and paper: close price vs next open; fees defaults |
| 10 | **JWT TTLs & refresh revocation** | Concrete minutes/days; store refresh hashes or not |
| 11 | **Password reset / email** | In A2 or defer; SMTP provider |
| 12 | **NSE symbol conventions** | Canonical `yahoo_symbol` list / onboarding rules |
| 13 | **EC2 sizing & region** | Instance type; AWS region; CloudWatch alarm thresholds |
| 14 | **Phase 0 sign-off** | Stakeholder approval of these docs before coding |

---

## 6. Phase 0 Exit Criteria

Phase 0 is complete when:

- [x] All ten documents exist under `docs/`
- [x] No implementation code or placeholder scaffolding was added
- [ ] Stakeholders review and approve architecture + open decisions above
- [ ] Open decisions log is closed or explicitly deferred with owners

**Next step after approval:** Begin **Module A1 — Project Foundation** per `project_roadmap.md`, creating the real codebase for the first time.
