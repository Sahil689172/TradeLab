# TradeLab — API Design

**Document type:** Phase 0 planning  
**Base URL:** `/api/v1`  
**Auth scheme:** `Authorization: Bearer <access_token>` unless noted  
**Style:** REST + JSON  
**Constraint:** Design only — **no implementation**.

Common conventions:

- Timestamps: ISO-8601 UTC.
- IDs: UUID strings.
- Pagination query: `limit` (default 50, max 200), `offset` (default 0).
- Error body (illustrative): `{ "code": "string", "message": "string", "details": {} }`.
- Async jobs may return `202` with `{ "job_id": "...", "status": "queued" }`.

---

## 1. Authentication

### POST `/auth/register`
| Field | Value |
|-------|--------|
| **Purpose** | Register a new user |
| **Authentication** | None |
| **Request schema** | `{ "email": "string", "password": "string", "display_name": "string" }` |
| **Response schema** | `201` `{ "id": "uuid", "email": "string", "display_name": "string", "role": "user", "created_at": "datetime" }` |
| **Status codes** | `201` Created · `409` Email taken · `422` Validation · `500` Server error |

### POST `/auth/login`
| Field | Value |
|-------|--------|
| **Purpose** | Authenticate and obtain tokens |
| **Authentication** | None |
| **Request schema** | `{ "email": "string", "password": "string" }` |
| **Response schema** | `200` `{ "access_token": "string", "refresh_token": "string", "token_type": "bearer", "expires_in": 0 }` |
| **Status codes** | `200` OK · `401` Invalid credentials · `422` Validation · `429` Rate limited · `500` |

### POST `/auth/refresh`
| Field | Value |
|-------|--------|
| **Purpose** | Issue new access token from refresh token |
| **Authentication** | None (refresh token in body) |
| **Request schema** | `{ "refresh_token": "string" }` |
| **Response schema** | `200` `{ "access_token": "string", "refresh_token": "string", "token_type": "bearer", "expires_in": 0 }` |
| **Status codes** | `200` · `401` Invalid/revoked · `422` · `500` |

### POST `/auth/logout`
| Field | Value |
|-------|--------|
| **Purpose** | Revoke refresh token (if server-side revocation enabled) |
| **Authentication** | Bearer required |
| **Request schema** | `{ "refresh_token": "string" }` optional if derived from session policy |
| **Response schema** | `204` Empty |
| **Status codes** | `204` · `401` · `500` |

### GET `/auth/me`
| Field | Value |
|-------|--------|
| **Purpose** | Get current user profile |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` `{ "id": "uuid", "email": "string", "display_name": "string", "role": "string", "created_at": "datetime" }` |
| **Status codes** | `200` · `401` · `500` |

### PATCH `/auth/me`
| Field | Value |
|-------|--------|
| **Purpose** | Update profile fields |
| **Authentication** | Bearer required |
| **Request schema** | `{ "display_name": "string" }` (partial) |
| **Response schema** | `200` Profile object (same as GET) |
| **Status codes** | `200` · `401` · `422` · `500` |

---

## 2. Market Data

### GET `/market/symbols`
| Field | Value |
|-------|--------|
| **Purpose** | List/search symbols |
| **Authentication** | Bearer required |
| **Request schema** | Query: `q?: string`, `limit`, `offset` |
| **Response schema** | `200` `{ "items": [{ "id", "ticker", "yahoo_symbol", "exchange", "name" }], "total": 0 }` |
| **Status codes** | `200` · `401` · `422` · `500` |

### POST `/market/symbols`
| Field | Value |
|-------|--------|
| **Purpose** | Register/resolve a symbol for use in the system |
| **Authentication** | Bearer required |
| **Request schema** | `{ "yahoo_symbol": "string", "ticker?": "string", "name?": "string" }` |
| **Response schema** | `201` Symbol object |
| **Status codes** | `201` · `401` · `409` Duplicate · `422` · `500` |

### GET `/market/symbols/{symbol_id}/ohlcv`
| Field | Value |
|-------|--------|
| **Purpose** | Read OHLCV bars (DB cache) |
| **Authentication** | Bearer required |
| **Request schema** | Query: `interval: string`, `start: datetime`, `end: datetime`, `limit?`, `offset?` |
| **Response schema** | `200` `{ "symbol_id", "interval", "items": [{ "ts", "open", "high", "low", "close", "volume", "adjusted_close?" }] }` |
| **Status codes** | `200` · `401` · `404` · `422` · `500` |

### POST `/market/fetch`
| Field | Value |
|-------|--------|
| **Purpose** | Fetch/refresh OHLCV from yfinance into DB |
| **Authentication** | Bearer required |
| **Request schema** | `{ "symbol_id": "uuid", "interval": "string", "start": "datetime", "end": "datetime", "force?: boolean" }` |
| **Response schema** | `202` `{ "fetch_id": "uuid", "status": "queued" }` or `200` `{ "fetch_id", "status": "succeeded", "bars_upserted": 0 }` |
| **Status codes** | `200`/`202` · `401` · `404` · `422` · `502` Provider error · `500` |

### GET `/market/fetches/{fetch_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Get fetch job status |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` `{ "id", "symbol_id", "interval", "start", "end", "status", "bars_upserted", "error_message?", "created_at", "finished_at?" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

---

## 3. Indicators

### GET `/indicators/catalog`
| Field | Value |
|-------|--------|
| **Purpose** | List supported indicators and parameter schemas |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` `{ "items": [{ "name": "RSI", "params_schema": {} }] }` |
| **Status codes** | `200` · `401` · `500` |

### POST `/indicators/compute`
| Field | Value |
|-------|--------|
| **Purpose** | Compute indicators for a symbol/range |
| **Authentication** | Bearer required |
| **Request schema** | `{ "symbol_id": "uuid", "interval": "string", "start": "datetime", "end": "datetime", "indicators": [{ "name": "string", "params": {} }] }` |
| **Response schema** | `200`/`202` `{ "run_id": "uuid", "status": "string", "series?: { "INDICATOR_KEY": [{ "ts", "value" }] } }` |
| **Status codes** | `200`/`202` · `401` · `404` · `422` · `500` |

### GET `/indicators/runs/{run_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Retrieve indicator run metadata and series |
| **Authentication** | Bearer required |
| **Request schema** | Query: `keys?: string[]` (filter series) |
| **Response schema** | `200` `{ "id", "symbol_id", "specs", "status", "series", "created_at", "finished_at?" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### GET `/indicators/runs`
| Field | Value |
|-------|--------|
| **Purpose** | List current user’s indicator runs |
| **Authentication** | Bearer required |
| **Request schema** | Query: `symbol_id?`, `limit`, `offset` |
| **Response schema** | `200` `{ "items": [run_summary], "total": 0 }` |
| **Status codes** | `200` · `401` · `422` · `500` |

---

## 4. Prediction

### POST `/predictions/models`
| Field | Value |
|-------|--------|
| **Purpose** | Create ML model registry entry |
| **Authentication** | Bearer required |
| **Request schema** | `{ "name": "string", "symbol_id": "uuid", "problem_type": "classification|regression", "target_definition": {}, "feature_config": {} }` |
| **Response schema** | `201` Model object |
| **Status codes** | `201` · `401` · `404` · `422` · `500` |

### GET `/predictions/models`
| Field | Value |
|-------|--------|
| **Purpose** | List user’s models |
| **Authentication** | Bearer required |
| **Request schema** | Query: `limit`, `offset` |
| **Response schema** | `200` `{ "items": [model_summary], "total": 0 }` |
| **Status codes** | `200` · `401` · `500` |

### GET `/predictions/models/{model_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Get model + versions summary |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` Model detail with `versions: []` |
| **Status codes** | `200` · `401` · `404` · `500` |

### DELETE `/predictions/models/{model_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Soft-delete model |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `204` |
| **Status codes** | `204` · `401` · `404` · `500` |

### POST `/predictions/models/{model_id}/train`
| Field | Value |
|-------|--------|
| **Purpose** | Start training a new model version |
| **Authentication** | Bearer required |
| **Request schema** | `{ "algorithm": "xgboost|sklearn_rf|...", "hyperparameters": {}, "train_start": "datetime", "train_end": "datetime", "validation_split?: number" }` |
| **Response schema** | `202` `{ "job_id": "uuid", "model_version_id": "uuid", "status": "queued" }` |
| **Status codes** | `202` · `401` · `404` · `422` · `500` |

### GET `/predictions/versions/{version_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Get version metrics and status |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` `{ "id", "model_id", "version", "algorithm", "hyperparameters", "metrics", "status", "artifact_s3_key?", "created_at" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### POST `/predictions/infer`
| Field | Value |
|-------|--------|
| **Purpose** | Run inference with a model version |
| **Authentication** | Bearer required |
| **Request schema** | `{ "model_version_id": "uuid", "as_of": "datetime" }` |
| **Response schema** | `200` `{ "model_version_id", "as_of", "prediction": {}, "features_used?: {}" }` |
| **Status codes** | `200` · `401` · `404` · `409` Model not ready · `422` · `500` |

---

## 5. Monte Carlo

### POST `/monte-carlo/runs`
| Field | Value |
|-------|--------|
| **Purpose** | Start a Monte Carlo simulation |
| **Authentication** | Bearer required |
| **Request schema** | `{ "symbol_id": "uuid", "method": "gbm|bootstrap", "n_paths": 0, "horizon": 0, "interval": "1d", "seed?: number", "params?: {} }` |
| **Response schema** | `202` `{ "run_id": "uuid", "status": "queued" }` |
| **Status codes** | `202` · `401` · `404` · `422` · `500` |

### GET `/monte-carlo/runs/{run_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Get simulation status and summary |
| **Authentication** | Bearer required |
| **Request schema** | Query: `include_paths?: boolean` (may return URL/ref) |
| **Response schema** | `200` `{ "id", "config", "summary", "paths_ref?", "status", "created_at", "finished_at?" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### GET `/monte-carlo/runs`
| Field | Value |
|-------|--------|
| **Purpose** | List user’s Monte Carlo runs |
| **Authentication** | Bearer required |
| **Request schema** | Query: `limit`, `offset` |
| **Response schema** | `200` `{ "items": [run_summary], "total": 0 }` |
| **Status codes** | `200` · `401` · `500` |

---

## 6. Strategy Builder

### POST `/strategies`
| Field | Value |
|-------|--------|
| **Purpose** | Create strategy (version 1) |
| **Authentication** | Bearer required |
| **Request schema** | `{ "name": "string", "description?: string", "definition": { "entry": [], "exit": [], "sizing?: {}, "risk?: {} } }` |
| **Response schema** | `201` `{ "id", "name", "description", "latest_version": 1, "definition": {}, "created_at" }` |
| **Status codes** | `201` · `401` · `422` · `500` |

### GET `/strategies`
| Field | Value |
|-------|--------|
| **Purpose** | List strategies |
| **Authentication** | Bearer required |
| **Request schema** | Query: `limit`, `offset` |
| **Response schema** | `200` `{ "items": [strategy_summary], "total": 0 }` |
| **Status codes** | `200` · `401` · `500` |

### GET `/strategies/{strategy_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Get strategy with latest definition |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` Strategy detail |
| **Status codes** | `200` · `401` · `404` · `500` |

### POST `/strategies/{strategy_id}/versions`
| Field | Value |
|-------|--------|
| **Purpose** | Publish a new immutable strategy version |
| **Authentication** | Bearer required |
| **Request schema** | `{ "definition": {} }` |
| **Response schema** | `201` `{ "strategy_id", "version", "definition", "created_at" }` |
| **Status codes** | `201` · `401` · `404` · `422` · `500` |

### GET `/strategies/{strategy_id}/versions`
| Field | Value |
|-------|--------|
| **Purpose** | List versions |
| **Authentication** | Bearer required |
| **Request schema** | Query: `limit`, `offset` |
| **Response schema** | `200` `{ "items": [{ "version", "created_at" }], "total" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### GET `/strategies/{strategy_id}/versions/{version}`
| Field | Value |
|-------|--------|
| **Purpose** | Get immutable definition snapshot |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` Version detail |
| **Status codes** | `200` · `401` · `404` · `500` |

### DELETE `/strategies/{strategy_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Soft-delete strategy |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `204` |
| **Status codes** | `204` · `401` · `404` · `500` |

---

## 7. Backtesting

### POST `/backtests`
| Field | Value |
|-------|--------|
| **Purpose** | Start a backtest |
| **Authentication** | Bearer required |
| **Request schema** | `{ "strategy_id": "uuid", "strategy_version?: number", "symbol_id": "uuid", "interval": "string", "start": "datetime", "end": "datetime", "params?: { "initial_cash": 0, "fee_bps": 0, "slippage_bps": 0, "fill_model": "close" } }` |
| **Response schema** | `202` `{ "backtest_id": "uuid", "status": "queued" }` |
| **Status codes** | `202` · `401` · `404` · `422` · `500` |

### GET `/backtests/{backtest_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Get backtest status, metrics, trades summary |
| **Authentication** | Bearer required |
| **Request schema** | Query: `include_trades?: boolean`, `include_equity?: boolean` |
| **Response schema** | `200` `{ "id", "status", "metrics", "trades?", "equity?", "params", "created_at", "finished_at?" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### GET `/backtests`
| Field | Value |
|-------|--------|
| **Purpose** | List backtests |
| **Authentication** | Bearer required |
| **Request schema** | Query: `strategy_id?`, `limit`, `offset` |
| **Response schema** | `200` `{ "items": [backtest_summary], "total" }` |
| **Status codes** | `200` · `401` · `500` |

---

## 8. Paper Trading

### POST `/paper/accounts`
| Field | Value |
|-------|--------|
| **Purpose** | Create paper account |
| **Authentication** | Bearer required |
| **Request schema** | `{ "name?: string", "initial_cash": number }` |
| **Response schema** | `201` Account object `{ "id", "name", "cash_balance", "initial_cash", "currency", "status" }` |
| **Status codes** | `201` · `401` · `409` Policy limit · `422` · `500` |

### GET `/paper/accounts`
| Field | Value |
|-------|--------|
| **Purpose** | List paper accounts |
| **Authentication** | Bearer required |
| **Request schema** | None / pagination |
| **Response schema** | `200` `{ "items": [account], "total" }` |
| **Status codes** | `200` · `401` · `500` |

### GET `/paper/accounts/{account_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Account detail with positions snapshot |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` `{ "account": {}, "positions": [], "equity?: number` }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### POST `/paper/accounts/{account_id}/orders`
| Field | Value |
|-------|--------|
| **Purpose** | Place paper order |
| **Authentication** | Bearer required |
| **Request schema** | `{ "symbol_id": "uuid", "side": "buy|sell", "order_type": "market|limit", "quantity": number, "limit_price?: number" }` |
| **Response schema** | `201` `{ "order": {}, "fill?: {} }` |
| **Status codes** | `201` · `401` · `404` · `409` Insufficient cash / buying power · `422` · `500` |

### GET `/paper/accounts/{account_id}/orders`
| Field | Value |
|-------|--------|
| **Purpose** | List orders |
| **Authentication** | Bearer required |
| **Request schema** | Query: `status?`, `limit`, `offset` |
| **Response schema** | `200` `{ "items": [order], "total" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### POST `/paper/accounts/{account_id}/orders/{order_id}/cancel`
| Field | Value |
|-------|--------|
| **Purpose** | Cancel open order |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` Updated order |
| **Status codes** | `200` · `401` · `404` · `409` Not cancellable · `500` |

### POST `/paper/accounts/{account_id}/reset`
| Field | Value |
|-------|--------|
| **Purpose** | Reset account to initial cash; clear positions/orders |
| **Authentication** | Bearer required |
| **Request schema** | `{ "confirm": true }` |
| **Response schema** | `200` Account object |
| **Status codes** | `200` · `401` · `404` · `422` · `500` |

---

## 9. Reports

### POST `/reports`
| Field | Value |
|-------|--------|
| **Purpose** | Generate analysis report from selected artifacts |
| **Authentication** | Bearer required |
| **Request schema** | `{ "title": "string", "sections": [{ "type": "market|indicators|prediction|monte_carlo|backtest|paper", "ref_id": "uuid" }] }` |
| **Response schema** | `202` `{ "report_id": "uuid", "status": "generating" }` |
| **Status codes** | `202` · `401` · `404` · `422` · `500` |

### GET `/reports/{report_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Retrieve report metadata and body/ref |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` `{ "id", "title", "status", "sections", "artifact_url?", "created_at", "finished_at?" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

### GET `/reports`
| Field | Value |
|-------|--------|
| **Purpose** | List reports |
| **Authentication** | Bearer required |
| **Request schema** | Query: `limit`, `offset` |
| **Response schema** | `200` `{ "items": [report_summary], "total" }` |
| **Status codes** | `200` · `401` · `500` |

### DELETE `/reports/{report_id}`
| Field | Value |
|-------|--------|
| **Purpose** | Delete report metadata (and optionally S3 object) |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `204` |
| **Status codes** | `204` · `401` · `404` · `500` |

---

## 10. System

### GET `/health`
| Field | Value |
|-------|--------|
| **Purpose** | Liveness probe |
| **Authentication** | None |
| **Request schema** | None |
| **Response schema** | `200` `{ "status": "ok" }` |
| **Status codes** | `200` · `500` |

### GET `/ready`
| Field | Value |
|-------|--------|
| **Purpose** | Readiness (e.g., DB reachable) |
| **Authentication** | None |
| **Request schema** | None |
| **Response schema** | `200` `{ "status": "ready", "checks": { "database": "ok" } }` |
| **Status codes** | `200` · `503` Not ready · `500` |

### GET `/jobs/{job_id}` (optional unified)
| Field | Value |
|-------|--------|
| **Purpose** | Poll unified job status |
| **Authentication** | Bearer required |
| **Request schema** | None |
| **Response schema** | `200` `{ "id", "job_type", "status", "resource_type?", "resource_id?", "error_message?", "created_at", "finished_at?" }` |
| **Status codes** | `200` · `401` · `404` · `500` |

---

## 11. Endpoint Inventory Summary

| Domain | Methods |
|--------|---------|
| Auth | register, login, refresh, logout, me |
| Market | symbols CRUD/list, ohlcv read, fetch + status |
| Indicators | catalog, compute, runs |
| Prediction | models CRUD, train, version get, infer |
| Monte Carlo | create run, get, list |
| Strategy | CRUD, versions |
| Backtest | create, get, list |
| Paper | accounts, orders, cancel, reset |
| Reports | create, get, list, delete |
| System | health, ready, jobs |

All protected endpoints require a valid JWT except auth register/login/refresh and health/ready.
