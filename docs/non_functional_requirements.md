# TradeLab — Non-Functional Requirements

**Document type:** Phase 0 planning  
**Applies to:** Phase A Quant Engine unless noted

---

## 1. Performance

| ID | Requirement | Target / Guidance |
|----|-------------|-------------------|
| NFR-PERF-01 | Synchronous API responses for CRUD and simple reads | p95 < 500 ms under expected v1 load (excluding cold provider calls) |
| NFR-PERF-02 | Market data cache hit path | p95 < 300 ms for DB-served OHLCV ranges of typical size (≤ 5 years daily) |
| NFR-PERF-03 | Indicator computation (single symbol, common indicators, ≤ 5y daily) | Complete within 10 s for typical requests; longer jobs use async job pattern |
| NFR-PERF-04 | ML training / large backtests / large Monte Carlo | Asynchronous; status pollable; no request thread blocked indefinitely |
| NFR-PERF-05 | Pagination | Default page size 50; max 200 for list endpoints |
| NFR-PERF-06 | Payload size | Large path arrays and model artifacts stored in S3; API returns references + summaries |
| NFR-PERF-07 | Outbound yfinance | Client-side rate limiting / backoff to avoid bursts |

**Notes:** Exact SLOs may be tuned after baseline load tests on EC2. Document measured baselines in Phase A+ hardening.

---

## 2. Security

| ID | Requirement |
|----|-------------|
| NFR-SEC-01 | All passwords hashed with a modern adaptive algorithm (e.g., bcrypt or argon2). |
| NFR-SEC-02 | JWT access tokens short-lived; refresh tokens longer-lived and rotatable/revocable where implemented. |
| NFR-SEC-03 | Secrets (DB URL, JWT secret, AWS keys) only via environment / secret store — never committed. |
| NFR-SEC-04 | HTTPS terminated at load balancer or reverse proxy in production (EC2 deployment guide). |
| NFR-SEC-05 | Input validation via Pydantic on all external inputs; reject unexpected fields where appropriate. |
| NFR-SEC-06 | Principle of least privilege for AWS IAM roles (S3 bucket prefix, CloudWatch). |
| NFR-SEC-07 | SQL injection prevention via SQLAlchemy parameterized queries/ORM only. |
| NFR-SEC-08 | No arbitrary user code execution in strategy definitions (JSON DSL only in v1). |
| NFR-SEC-09 | CORS configured for known frontend origins (Phase C); restrictive defaults in Phase A. |
| NFR-SEC-10 | Rate limiting on auth endpoints to mitigate brute force. |
| NFR-SEC-11 | Soft delete / ownership checks so users cannot access others’ strategies, jobs, reports, or accounts. |

---

## 3. Reliability

| ID | Requirement |
|----|-------------|
| NFR-REL-01 | Database migrations via Alembic; no manual prod schema drift. |
| NFR-REL-02 | Idempotent upserts for OHLCV bars on `(symbol, interval, timestamp)`. |
| NFR-REL-03 | Job failures recorded with error message and terminal `failed` status; retries are explicit. |
| NFR-REL-04 | Provider (yfinance) outages surface as controlled errors; cached data remains readable. |
| NFR-REL-05 | Application process restart-safe: in-flight async jobs either resume via worker design or mark failed for retry. |
| NFR-REL-06 | S3 writes for artifacts verified (or transactional metadata updated only after successful upload). |
| NFR-REL-07 | Health check endpoint for process liveness; readiness may include DB connectivity. |

---

## 4. Maintainability

| ID | Requirement |
|----|-------------|
| NFR-MAIN-01 | Modular package layout by domain (auth, market_data, indicators, ml, monte_carlo, strategy, backtest, paper_trade, reports). |
| NFR-MAIN-02 | Business logic in services; routers thin; repositories own persistence. |
| NFR-MAIN-03 | ML code has no FastAPI imports. |
| NFR-MAIN-04 | Shared error types, logging helpers, and config in cross-cutting packages. |
| NFR-MAIN-05 | Alembic migrations reviewed and reversible where practical. |
| NFR-MAIN-06 | API contracts documented (OpenAPI from FastAPI) and aligned with `api_design.md`. |
| NFR-MAIN-07 | Coding standards and naming follow `development_guidelines.md`. |

---

## 5. Scalability

| ID | Requirement |
|----|-------------|
| NFR-SCALE-01 | v1 is a modular monolith on a single EC2 instance (or app + managed Postgres). |
| NFR-SCALE-02 | Domain boundaries allow extraction to microservices without rewriting core logic. |
| NFR-SCALE-03 | Stateless app tier: session state in JWT/DB, not in process memory (except ephemeral job workers). |
| NFR-SCALE-04 | Heavy compute (train/backtest/MC) designed to move to background workers / separate instances later. |
| NFR-SCALE-05 | Object storage (S3) for large blobs so DB remains for metadata and relational queries. |
| NFR-SCALE-06 | Horizontal scale of API instances possible behind a load balancer once shared DB and object store are in place. |

**Explicit non-goal for v1:** Auto-scaling groups, Kubernetes, and Docker orchestration.

---

## 6. Testing

| ID | Requirement |
|----|-------------|
| NFR-TEST-01 | Pytest as the test runner. |
| NFR-TEST-02 | Unit tests for domain/services/ML with mocked I/O. |
| NFR-TEST-03 | API tests via FastAPI `TestClient` (or httpx AsyncClient) with test DB. |
| NFR-TEST-04 | Repository/integration tests against PostgreSQL (local or CI service). |
| NFR-TEST-05 | Deterministic tests for Monte Carlo when seed is fixed. |
| NFR-TEST-06 | No live yfinance calls in CI by default; use fixtures/recorded samples. |
| NFR-TEST-07 | Target: meaningful coverage on services and critical paths before each Phase A module is “done.” |

---

## 7. Logging

| ID | Requirement |
|----|-------------|
| NFR-LOG-01 | Structured logging (JSON preferred in production) with timestamp, level, logger name, message, request_id. |
| NFR-LOG-02 | Every HTTP request assigned a correlation / request ID propagated to service logs. |
| NFR-LOG-03 | Auth failures, provider failures, and job failures logged at warning/error with safe detail (no passwords/tokens). |
| NFR-LOG-04 | Log levels configurable via environment (`LOG_LEVEL`). |
| NFR-LOG-05 | Application logs shipped to CloudWatch Logs in production. |

---

## 8. Monitoring

| ID | Requirement |
|----|-------------|
| NFR-MON-01 | CloudWatch metrics for process health, error rates, and latency (custom metrics or log-based metrics). |
| NFR-MON-02 | Alarms on sustained 5xx rate and instance health (disk, CPU, memory thresholds). |
| NFR-MON-03 | Health and readiness endpoints for uptime checks. |
| NFR-MON-04 | Job queue depth / failed job counts visible via metrics or admin queries (Phase A+ if not in A). |
| NFR-MON-05 | S3 and DB connectivity failures detectable via health or error dashboards. |

---

## 9. Availability & Data Retention (Guidance)

| Topic | Guidance |
|-------|----------|
| Availability | Best-effort single-instance v1; maintenance windows acceptable |
| Backups | Automated PostgreSQL backups (snapshot or managed backup) |
| Artifact retention | S3 lifecycle rules for old model/report blobs (policy TBD before prod) |
| Audit | Auth and destructive actions should be attributable to `user_id` |

---

## 10. Compliance & Ethics (Lightweight)

- TradeLab v1 is an **analysis and paper-trading** tool, not regulated brokerage.
- Disclaimers for prediction/backtest results should be API-documentable for frontend display (Phase C).
- No collection of unnecessary PII beyond account needs.
