# TradeLab — Functional Requirements

**Document type:** Phase 0 planning  
**Applies to:** Phase A Quant Engine (unless noted)  
**Priority legend:** **M** = Must have (v1), **S** = Should have, **C** = Could have / later

---

## 1. Authentication

| ID | Requirement | Priority |
|----|-------------|----------|
| AUTH-01 | Users shall register with email, password, and display name. | M |
| AUTH-02 | Passwords shall be stored only as strong one-way hashes (never plaintext). | M |
| AUTH-03 | Users shall log in with email and password and receive a JWT access token. | M |
| AUTH-04 | The system shall issue a refresh token to renew access tokens without re-entering credentials. | M |
| AUTH-05 | Users shall log out (client discards tokens; optional server-side refresh token revocation). | M |
| AUTH-06 | Authenticated users shall retrieve and update their profile (display name; email change rules TBD). | M |
| AUTH-07 | The system shall reject invalid credentials with generic error messaging (no user enumeration beyond necessary). | M |
| AUTH-08 | Access to protected resources shall require a valid, non-expired JWT. | M |
| AUTH-09 | The system shall support a `role` field on users (`user`, `admin`) for future authorization expansion. | S |
| AUTH-10 | Password reset via email token shall be designed; full email delivery may be stubbed or deferred if SMTP is not ready. | C |

### Business Rules

- Email must be unique.
- Minimum password length and complexity rules are enforced at the API validation layer.
- Refresh tokens have longer TTL than access tokens; access tokens are short-lived.

---

## 2. Market Data

| ID | Requirement | Priority |
|----|-------------|----------|
| MD-01 | The system shall fetch historical OHLCV data for NSE-listed symbols via yfinance. | M |
| MD-02 | Users shall request data for a symbol, interval (e.g., 1d, 1h where supported), and date range. | M |
| MD-03 | Fetched bars shall be persisted so repeated requests can be served from the database within a freshness window. | M |
| MD-04 | Users shall trigger an explicit refresh to re-fetch from the provider when cache is stale or forced. | M |
| MD-05 | The system shall record fetch metadata (symbol, range, provider, timestamp, status). | M |
| MD-06 | Users shall list/search supported or previously used symbols. | S |
| MD-07 | The system shall handle provider failures gracefully (clear error codes, no partial silent corruption). | M |
| MD-08 | Corporate actions / adjusted close handling shall be documented and consistently applied when available from the provider. | S |

### Business Rules

- Symbol identifiers follow an agreed NSE convention (e.g., `RELIANCE.NS` for yfinance).
- Overlapping fetches upsert bars keyed by `(symbol_id, interval, timestamp)`.
- Rate limiting and backoff apply to outbound yfinance calls.

---

## 3. Indicators

| ID | Requirement | Priority |
|----|-------------|----------|
| IND-01 | Users shall request computation of one or more technical indicators for a symbol and range. | M |
| IND-02 | Supported indicators shall include at least: SMA, EMA, RSI, MACD, Bollinger Bands, ATR. | M |
| IND-03 | Indicator parameters (period, window, etc.) shall be user-configurable within safe bounds. | M |
| IND-04 | Computed series shall be persistable and retrievable by job/request id. | M |
| IND-05 | Indicator computation shall use pandas-ta (preferred) or the `ta` library via a single internal adapter interface. | M |
| IND-06 | Invalid parameters or insufficient history shall return validation errors, not crash. | M |
| IND-07 | Users shall list available indicator types and default parameter schemas. | S |

### Business Rules

- Indicator jobs reference underlying OHLCV data; missing data triggers fetch or error per policy.
- Results are deterministic for the same inputs and library version (library version recorded in metadata).

---

## 4. Prediction

| ID | Requirement | Priority |
|----|-------------|----------|
| PRD-01 | Users shall create a training job specifying symbol, feature set, target (e.g., next-day return/direction), model type (sklearn / XGBoost), and hyperparameters. | M |
| PRD-02 | The system shall assemble features from stored prices and indicators. | M |
| PRD-03 | Training shall produce evaluation metrics (accuracy, precision/recall or RMSE/MAE as appropriate) on a held-out split. | M |
| PRD-04 | Trained model artifacts shall be stored in S3 (or local filesystem in early local-dev only); metadata in PostgreSQL. | M |
| PRD-05 | Users shall list models, view metrics, and select a model version for inference. | M |
| PRD-06 | Users shall request predictions for a symbol/date context using a specified model version. | M |
| PRD-07 | Training and inference logic shall live outside FastAPI route handlers (pure ML package). | M |
| PRD-08 | Long-running training may be asynchronous (job status: queued / running / succeeded / failed). | S |
| PRD-09 | Users shall delete or archive obsolete model versions (soft delete preferred). | C |

### Business Rules

- Model version identifiers are immutable once published.
- Inference fails clearly if features cannot be built for the requested context.

---

## 5. Monte Carlo

| ID | Requirement | Priority |
|----|-------------|----------|
| MC-01 | Users shall configure a Monte Carlo simulation: symbol or returns series, number of paths, horizon, seed (optional). | M |
| MC-02 | The system shall simulate price paths under documented assumptions (e.g., geometric Brownian motion or bootstrap of historical returns). | M |
| MC-03 | Outputs shall include path summaries (percentiles, mean, terminal distribution statistics). | M |
| MC-04 | Simulation runs shall be persisted with parameters and summary results; full path arrays may be S3-stored. | M |
| MC-05 | Users shall retrieve past simulation runs by id. | M |
| MC-06 | Optional portfolio-level simulation using position weights shall be supported. | S |

### Business Rules

- Random seed, when provided, must make runs reproducible.
- Maximum paths/horizon are capped for resource protection.

---

## 6. Strategy Builder

| ID | Requirement | Priority |
|----|-------------|----------|
| STR-01 | Users shall create a strategy definition with name, description, and structured rules. | M |
| STR-02 | Rules shall support conditions on indicators and/or price fields (e.g., RSI < 30 AND close > SMA). | M |
| STR-03 | Strategies shall define entry, exit, and optional position-sizing / risk parameters. | M |
| STR-04 | Users shall update, list, get, and soft-delete their strategies. | M |
| STR-05 | The system shall validate strategy schemas before save (unknown indicators, invalid operators). | M |
| STR-06 | Strategies shall be versioned so backtests reference an immutable definition snapshot. | S |
| STR-07 | Strategy definitions shall be portable JSON (no arbitrary code execution in v1). | M |

### Business Rules

- v1 strategies are declarative DSL/JSON only — no user-uploaded Python.
- Ownership: users can only mutate their own strategies (admins later).

---

## 7. Backtesting

| ID | Requirement | Priority |
|----|-------------|----------|
| BT-01 | Users shall start a backtest for a strategy version over a symbol and date range. | M |
| BT-02 | The engine shall simulate orders/fills using historical bars (bar-close or configurable fill assumption, documented). | M |
| BT-03 | Outputs shall include trade list, equity curve points, and metrics (total return, max drawdown, win rate, trade count). | M |
| BT-04 | Backtest jobs shall expose status and results via API. | M |
| BT-05 | Users shall compare multiple backtest runs for the same strategy. | S |
| BT-06 | Transaction costs and slippage shall be configurable parameters. | S |
| BT-07 | Backtests shall not mutate paper-trading accounts. | M |

### Business Rules

- Insufficient data for the range fails validation before run.
- Fill model and costs are recorded with the run for reproducibility.

---

## 8. Paper Trading

| ID | Requirement | Priority |
|----|-------------|----------|
| PT-01 | Each user shall have (or can create) a virtual paper-trading account with starting cash. | M |
| PT-02 | Users shall place market/limit-style paper orders (v1 may support market-on-next-bar or last-price fills — documented). | M |
| PT-03 | The system shall maintain positions, cash balance, and realized/unrealized P&L. | M |
| PT-04 | Users shall cancel open orders where applicable. | M |
| PT-05 | Users shall view order history and current portfolio. | M |
| PT-06 | Fills shall use reference prices from stored market data (not live broker). | M |
| PT-07 | Account reset (return to initial cash, clear positions) shall be supported. | S |
| PT-08 | Multiple paper accounts per user shall be optional. | C |

### Business Rules

- No order may spend more cash than available (buying power checks).
- Short selling policy is explicit (enabled/disabled in v1 — default disabled unless decided otherwise).

---

## 9. Reports

| ID | Requirement | Priority |
|----|-------------|----------|
| RPT-01 | Users shall generate a report aggregating selected analysis artifacts (market summary, indicators, prediction, Monte Carlo, backtest, paper P&L). | M |
| RPT-02 | Report metadata shall be stored in PostgreSQL; large payloads/files in S3. | M |
| RPT-03 | Users shall list and retrieve their reports. | M |
| RPT-04 | Reports shall include generation timestamp, parameters, and linked resource ids. | M |
| RPT-05 | Report format in v1 shall be structured JSON; PDF export is optional later. | S |
| RPT-06 | Reports shall be designed so Phase B can attach them to collaboration rooms. | S |

### Business Rules

- Users can only access their own reports in Phase A.
- Failed generation leaves a failed status with error detail, not a partial “success.”

---

## Cross-Cutting Functional Rules

| ID | Requirement | Priority |
|----|-------------|----------|
| X-01 | All mutating endpoints shall be authenticated except registration/login. | M |
| X-02 | All list endpoints shall support pagination (limit/offset or cursor). | M |
| X-03 | Long-running work (train, backtest, large MC) shall use a job pattern with status polling. | S |
| X-04 | API errors shall use consistent problem shapes (code, message, details). | M |
| X-05 | Every domain module shall expose service interfaces usable without HTTP (for tests and future workers). | M |
