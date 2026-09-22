# TradeLab — Deployment Guide

> **Important:** AWS services are **not permanently free**. The free-tier covers limited hours/month and expires after 12 months for new accounts. This guide uses the lowest-cost options and documents what will be charged. Read every cost note before deploying.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Prerequisites](#2-prerequisites)
3. [AWS Free-Tier Precautions and Cost Estimates](#3-aws-free-tier-precautions-and-cost-estimates)
4. [Services Used and Why](#4-services-used-and-why)
5. [Environment Variables](#5-environment-variables)
6. [Database Setup](#6-database-setup)
7. [Backend Deployment](#7-backend-deployment)
8. [Frontend Deployment](#8-frontend-deployment)
9. [CORS Configuration](#9-cors-configuration)
10. [Authentication Notes](#10-authentication-notes)
11. [Secrets Management](#11-secrets-management)
12. [Market Data Configuration](#12-market-data-configuration)
13. [Paper Trading Persistence](#13-paper-trading-persistence)
14. [Chat Room Persistence](#14-chat-room-persistence)
15. [HTTPS / Domain](#15-https--domain)
16. [Health Checks](#16-health-checks)
17. [Logs and Monitoring](#17-logs-and-monitoring)
18. [Backups and Restore](#18-backups-and-restore)
19. [Updates and Rollback](#19-updates-and-rollback)
20. [Troubleshooting](#20-troubleshooting)
21. [AWS Cost Monitoring](#21-aws-cost-monitoring)
22. [Resource Cleanup](#22-resource-cleanup)
23. [Security Checklist](#23-security-checklist)

---

## 1. Architecture Overview

```
Browser
  │
  ▼
Amazon CloudFront (HTTPS CDN)
  ├── /api/* ──────────────► AWS App Runner (FastAPI, Docker)
  │                               │
  │                               ├── SQLite DB  (ephemeral /app/data/)
  │                               ├── Parquet files (ephemeral)
  │                               └── AWS Secrets Manager (AI keys)
  │
  └── /* (SPA) ────────────► Amazon S3 (static frontend build)
```

**Key design decisions:**
- **Single App Runner instance** — no ECS cluster, no ALB, no NAT Gateway. Keeps monthly cost under $10.
- **SQLite on ephemeral disk** — simple, zero extra cost. Market-data parquet files survive between requests (same container) but are lost on deploy. Run bootstrap after each deploy or mount EFS (see §13).
- **CloudFront** handles HTTPS, caches static assets, and reverse-proxies `/api/*` to App Runner — no extra certificate cost.
- **No RDS** — SQLite is sufficient for single-user paper trading and a small number of collab rooms.

---

## 2. Prerequisites

**Local machine (Windows CMD):**
- Docker Desktop — [https://docs.docker.com/desktop/install/windows-install/](https://docs.docker.com/desktop/install/windows-install/)
- AWS CLI v2 — [https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html)
- Terraform >= 1.5 — [https://developer.hashicorp.com/terraform/install](https://developer.hashicorp.com/terraform/install)
- Node.js >= 18 (for frontend build)

**AWS account:**
```cmd
aws configure
REM Enter: Access Key ID, Secret Access Key, region (ap-south-1), output (json)
```

Verify:
```cmd
aws sts get-caller-identity
```

---

## 3. AWS Free-Tier Precautions and Cost Estimates

| Service | Free Tier | After Free Tier |
|---|---|---|
| App Runner | None (App Runner has no free tier) | ~$5–15/month (0.25 vCPU, 0.5 GB, low traffic) |
| ECR | 500 MB/month storage | $0.10/GB/month |
| S3 | 5 GB storage, 20K GET, 2K PUT/month | Fractions of a cent for a small app |
| CloudFront | 1 TB transfer + 10M requests/month (12 months) | ~$0.0085/GB |
| Secrets Manager | First 30 days free per secret | $0.40/secret/month |

**Cost control steps:**
1. Set a **billing alert** at $10/month (see §21) before deploying anything.
2. After testing, **pause App Runner** in the AWS Console (Actions → Pause) — paused instances cost ~$0/month for compute (you still pay for the stored image).
3. Use `terraform destroy` to remove all resources when not needed.
4. The lifecycle policy in `aws/app_runner.tf` keeps only the last 3 ECR images to prevent storage accumulation.

> **These are not guaranteed to be free.** AWS pricing changes. Always verify at [https://aws.amazon.com/pricing/](https://aws.amazon.com/pricing/).

---

## 4. Services Used and Why

| Service | Role | Why Not Alternative |
|---|---|---|
| AWS App Runner | Run FastAPI container | No EC2 setup, auto-HTTPS, scales to zero when paused |
| Amazon ECR | Store Docker image | Required by App Runner |
| Amazon S3 | Host compiled React SPA | Cheapest static hosting on AWS |
| Amazon CloudFront | HTTPS + API proxy | Free tier is generous; handles SSL automatically |
| AWS Secrets Manager | Store AI API keys | Never put secrets in env vars or code |

**Not used:**
- ECS/Fargate — more expensive, more config
- RDS/Aurora — SQLite is sufficient; RDS starts at ~$15/month
- Elastic Load Balancer — App Runner has built-in load balancing
- NAT Gateway — ~$45/month, completely unnecessary here

---

## 5. Environment Variables

Create a `.env` file locally (never commit it — it is already in `.gitignore`):

```
# Application
APP_ENV=production
DEBUG=false
HOST=0.0.0.0
PORT=8000

# Database (SQLite, relative to container workdir)
METADATA_DATABASE_URL=sqlite:////app/data/metadata.db
DATABASE_URL=sqlite:////app/data/metadata.db

# Storage
PARQUET_STORAGE_DIR=/app/data/ohlcv
LOG_DIRECTORY=/app/data/logs

# CORS — set to your CloudFront URL after first deploy
ALLOWED_ORIGINS=https://YOUR_CLOUDFRONT_DOMAIN.cloudfront.net

# AI providers (injected from Secrets Manager in production)
GEMINI_API_KEY=
GROQ_API_KEY=

# Market data
BOOTSTRAP_HISTORY_YEARS=5
YFINANCE_TIMEOUT_SECONDS=30
BOOTSTRAP_RATE_LIMIT_SECONDS=0.75

# Chat
CHAT_HISTORY_LIMIT=50
ROOM_DEFAULT_CAPACITY=2
```

**In App Runner**, environment variables are set in `aws/app_runner.tf` under `runtime_environment_variables`. Secrets are injected separately via `runtime_environment_secrets` — they never appear as plaintext in Terraform state.

---

## 6. Database Setup

TradeLab uses SQLite with SQLAlchemy's `create_all()` — **no migration tool is required**.

Tables are created automatically on first startup:
- `company_metadata` — stock metadata
- `ingestion_state` — OHLCV bootstrap tracking
- `chat_rooms`, `chat_room_members`, `chat_messages` — collab rooms
- `paper_trading_accounts`, `paper_trading_positions`, `paper_trading_orders` — persistent paper trading

**Local development:**
```cmd
REM Tables are created when the server starts. No manual step needed.
python -m uvicorn app.main:app --reload
```

**In production (App Runner):**  
Tables are created by the lifespan handler at container startup. The SQLite file lives at `/app/data/metadata.db` inside the container.

> **Warning:** App Runner's filesystem is ephemeral. Data is lost when the container is replaced (deploys, crashes, scaling). For durable data:
> - Mount **Amazon EFS** at `/app/data` (adds ~$0.30/GB/month).
> - Or periodically back up the SQLite file to S3 (see §18).

---

## 7. Backend Deployment

### Step 1 — Build the Docker image

From the project root (where `Dockerfile` lives):

```cmd
docker build -t tradelab:latest .
```

### Step 2 — Push to ECR

```cmd
SET REGION=ap-south-1
SET ACCOUNT_ID=YOUR_12_DIGIT_ACCOUNT_ID

aws ecr get-login-password --region %REGION% | docker login --username AWS --password-stdin %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com

docker tag tradelab:latest %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:latest
docker push %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:latest
```

### Step 3 — Store secrets

```cmd
aws secretsmanager create-secret --name tradelab/gemini-api-key --secret-string "YOUR_GEMINI_KEY" --region %REGION%
aws secretsmanager create-secret --name tradelab/groq-api-key   --secret-string "YOUR_GROQ_KEY"   --region %REGION%
```

Note the ARNs printed — you will need them for Terraform.

### Step 4 — Deploy with Terraform

```cmd
cd aws
terraform init
terraform apply ^
  -var="ecr_image_uri=%ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:latest" ^
  -var="gemini_api_key_arn=arn:aws:secretsmanager:%REGION%:%ACCOUNT_ID%:secret:tradelab/gemini-api-key-XXXXXX" ^
  -var="groq_api_key_arn=arn:aws:secretsmanager:%REGION%:%ACCOUNT_ID%:secret:tradelab/groq-api-key-XXXXXX"
```

Terraform prints the App Runner URL and CloudFront URL when complete.

### Step 5 — Verify

```cmd
curl https://YOUR_APPRUNNER_URL/health
REM Expected: {"status": "ok", "database": "connected"}
```

---

## 8. Frontend Deployment

### Step 1 — Build

```cmd
cd frontend
REM Set the API base URL to your CloudFront domain (it proxies /api/* to App Runner)
set VITE_API_BASE=https://YOUR_CLOUDFRONT_DOMAIN.cloudfront.net
npm run build
```

> If your `vite.config.ts` uses a proxy for `/api`, remove it for production. The React app should use relative paths (`/api/v1/...`) so CloudFront routes them correctly.

### Step 2 — Upload to S3

```cmd
aws s3 sync dist/ s3://tradelab-frontend-%ACCOUNT_ID%/ --delete --region %REGION%
```

### Step 3 — Invalidate CloudFront cache

```cmd
aws cloudfront create-invalidation --distribution-id YOUR_CF_DIST_ID --paths "/*"
```

Find the distribution ID with:
```cmd
aws cloudfront list-distributions --query "DistributionList.Items[*].{Id:Id,Domain:DomainName}"
```

---

## 9. CORS Configuration

For production, update `app/main.py` to read allowed origins from the environment:

```python
import os
_origins_raw = os.getenv("ALLOWED_ORIGINS", "http://localhost:5173")
allow_origins = [o.strip() for o in _origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allow_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

Set `ALLOWED_ORIGINS=https://YOUR_CLOUDFRONT_DOMAIN.cloudfront.net` in the App Runner environment.

> The current code hard-codes localhost origins. This must be changed before production traffic is served — without a correct `Access-Control-Allow-Origin` header, browser requests from your CloudFront domain will be blocked.

---

## 10. Authentication Notes

TradeLab currently has **no authentication**. User identity in the collab system is a trust-on-assertion string handle. Paper trading is isolated per user handle (persisted to DB per `user_handle` string).

For a production deployment with real users you would need to add:
- A `users` table with hashed passwords
- JWT token issuance (`/auth/login`)
- `get_current_user` FastAPI dependency replacing `user: str = Query(...)`

This is out of scope for the current build. The existing handle-based system is fine for demos and private deployments where you control who has the URL.

---

## 11. Secrets Management

**Never put API keys in code, `.env` files in the repo, or environment variable strings visible in the AWS Console.**

All secrets are stored in AWS Secrets Manager and injected at runtime:

```cmd
REM View a secret (confirm it was stored correctly)
aws secretsmanager get-secret-value --secret-id tradelab/gemini-api-key --region %REGION%

REM Rotate a key
aws secretsmanager update-secret --secret-id tradelab/gemini-api-key --secret-string "NEW_KEY" --region %REGION%
REM Then redeploy the App Runner service to pick up the new value.
```

---

## 12. Market Data Configuration

Market data is stored as **Parquet files** in `PARQUET_STORAGE_DIR` and **metadata** in SQLite. Both are inside the container's ephemeral filesystem by default.

**Bootstrap after first deploy:**

```cmd
REM Trigger a full bootstrap via the admin API endpoint:
curl -X POST https://YOUR_APPRUNNER_URL/api/v1/market/bootstrap/all
```

> This downloads up to 10 years of daily OHLCV for ~500 NIFTY 500 symbols from Yahoo Finance. It takes 15–60 minutes and makes many network requests. Only run once. For subsequent updates use `/api/v1/market/update/all`.

**To preserve market data across deploys**, mount an EFS volume:
1. Create an EFS filesystem in the same AWS region.
2. Add an EFS volume mount to your App Runner service configuration.
3. Set `PARQUET_STORAGE_DIR=/mnt/efs/ohlcv` and `METADATA_DATABASE_URL=sqlite:////mnt/efs/metadata.db`.

---

## 13. Paper Trading Persistence

Paper trading state (cash, positions, orders) is now stored per `user_handle` in three SQLite tables:
- `paper_trading_accounts` — cash and realized P&L per user
- `paper_trading_positions` — open positions per user
- `paper_trading_orders` — order history per user (up to 500 most recent loaded on startup)

Tables are created automatically at startup. Data survives server restarts **as long as the SQLite file is preserved** (i.e., you have an EFS mount or are not redeploying).

The `user` query parameter on portfolio/order endpoints defaults to `"default"` for backward compatibility:
```
GET /api/v1/portfolio?user=alice
POST /api/v1/orders/buy?user=alice
```

---

## 14. Chat Room Persistence

Chat rooms, members, and messages are persisted to the SQLite database (`chat_rooms`, `chat_room_members`, `chat_messages` tables). Room paper books (positions/cash) are **in-memory** and reset on restart — only the initial_capital is stored in `chat_rooms`.

**Authorization** (added in this release):
- `GET /rooms/{id}/messages?user=X` — X must be a room member
- `GET /rooms/{id}/portfolio?user=X` — X must be a room member  
- `GET /rooms/{id}/orders?user=X` — X must be a room member
- `DELETE /rooms/{id}?user=X` — X must be the room owner (`created_by`)

---

## 15. HTTPS / Domain

CloudFront provides HTTPS automatically using its default `*.cloudfront.net` certificate at no cost.

**Custom domain:**
1. Register a domain in Route 53 (or bring your own).
2. Request an ACM certificate in `us-east-1` (required for CloudFront).
3. Update the `viewer_certificate` block in `aws/app_runner.tf`:
   ```hcl
   viewer_certificate {
     acm_certificate_arn      = "arn:aws:acm:us-east-1:ACCOUNT:certificate/UUID"
     ssl_support_method       = "sni-only"
     minimum_protocol_version = "TLSv1.2_2021"
   }
   ```
4. Add a CNAME record pointing your domain to the CloudFront domain.

---

## 16. Health Checks

Backend health endpoint: `GET /health`

Expected response:
```json
{"status": "ok", "database": "connected"}
```

App Runner polls this every 20 seconds (configured in Terraform). If it fails 5 consecutive times, App Runner replaces the container.

Check manually:
```cmd
curl https://YOUR_APPRUNNER_URL/health
```

---

## 17. Logs and Monitoring

**App Runner logs** are automatically sent to Amazon CloudWatch Logs:
```cmd
REM List log groups
aws logs describe-log-groups --log-group-name-prefix /aws/apprunner --region %REGION%

REM Tail recent logs
aws logs tail /aws/apprunner/tradelab/SERVICE_ID/application --follow --region %REGION%
```

**S3 access logs:** Enable S3 server access logging in the bucket's properties if you want request logs for the frontend.

**CloudFront access logs:** Enable in the distribution settings (logs go to an S3 bucket of your choice).

---

## 18. Backups and Restore

Since SQLite lives on ephemeral container storage, back up to S3 periodically.

**Manual backup (Linux command inside the container, or via AWS SSM):**
```bash
# Linux (run inside container or on EFS mount)
aws s3 cp /app/data/metadata.db s3://YOUR_BUCKET/backups/metadata-$(date +%Y%m%d).db
```

**Restore:**
```bash
aws s3 cp s3://YOUR_BUCKET/backups/metadata-20250101.db /app/data/metadata.db
```

**Recommended:** Mount EFS at `/app/data` so data is durable by default (no manual backup needed for the DB). Parquet files can be re-bootstrapped from Yahoo Finance if lost.

---

## 19. Updates and Rollback

**Deploy a new version:**
```cmd
docker build -t tradelab:latest .
docker tag tradelab:latest %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:latest
docker push %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:latest

REM Trigger App Runner to deploy the new image:
aws apprunner start-deployment --service-arn YOUR_SERVICE_ARN --region %REGION%
```

**Rollback to previous image:**
```cmd
REM Tag a previous image as latest
aws ecr list-images --repository-name tradelab --region %REGION%
docker pull %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:PREVIOUS_TAG
docker tag %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:PREVIOUS_TAG %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:latest
docker push %ACCOUNT_ID%.dkr.ecr.%REGION%.amazonaws.com/tradelab:latest
aws apprunner start-deployment --service-arn YOUR_SERVICE_ARN --region %REGION%
```

---

## 20. Troubleshooting

| Symptom | Likely Cause | Fix |
|---|---|---|
| `/health` returns 502 | App Runner container failed to start | Check CloudWatch logs for Python import errors |
| Frontend loads, API calls fail with CORS error | `ALLOWED_ORIGINS` not set to CloudFront domain | Update env var and redeploy |
| `No market price available` on buy order | Symbol not bootstrapped | `POST /api/v1/market/bootstrap/SYMBOL` |
| Chat messages not appearing after reconnect | WebSocket `user` handle mismatch | Use the exact same handle string you joined with |
| Monte Carlo hangs at "Loading trades" | Symbol has no OOS trade history | Bootstrap symbol, run strategy replay first |
| 403 on `/rooms/{id}/messages` | Caller not a room member | Join the room first via `POST /rooms/{id}/join?user=X` |
| `sqlite3.OperationalError: no such table` | Container restarted before `create_all` ran | Restart App Runner service; tables are created at startup |
| Terraform error: `InvalidParameterException: Access role is invalid` | ECR access role not propagated yet | Wait 30 seconds and retry `terraform apply` |

---

## 21. AWS Cost Monitoring

Set up a billing alert immediately:

```cmd
REM Create a billing alert at $10 USD
aws cloudwatch put-metric-alarm ^
  --alarm-name "TradeLab-Billing-10USD" ^
  --alarm-description "Alert when estimated charges exceed $10" ^
  --metric-name EstimatedCharges ^
  --namespace AWS/Billing ^
  --statistic Maximum ^
  --period 86400 ^
  --threshold 10 ^
  --comparison-operator GreaterThanThreshold ^
  --dimensions Name=Currency,Value=USD ^
  --evaluation-periods 1 ^
  --alarm-actions arn:aws:sns:us-east-1:%ACCOUNT_ID%:YOUR_SNS_TOPIC ^
  --region us-east-1
```

> Billing metrics are only available in `us-east-1` regardless of your deployment region.

Check current month costs:
```cmd
aws ce get-cost-and-usage ^
  --time-period Start=2025-01-01,End=2025-01-31 ^
  --granularity MONTHLY ^
  --metrics "UnblendedCost" ^
  --region us-east-1
```

**Pause App Runner when not in use** (AWS Console → App Runner → your service → Actions → Pause). This stops compute charges. The service URL remains valid and resumes in ~30 seconds when you unpause.

---

## 22. Resource Cleanup

To completely remove all AWS resources and stop all charges:

```cmd
REM 1. Destroy Terraform-managed resources
cd aws
terraform destroy

REM 2. Delete ECR images manually (Terraform may not clean these)
aws ecr delete-repository --repository-name tradelab --force --region %REGION%

REM 3. Delete secrets
aws secretsmanager delete-secret --secret-id tradelab/gemini-api-key --force-delete-without-recovery --region %REGION%
aws secretsmanager delete-secret --secret-id tradelab/groq-api-key --force-delete-without-recovery --region %REGION%

REM 4. Verify no running resources remain
aws apprunner list-services --region %REGION%
aws s3 ls
```

---

## 23. Security Checklist

- [ ] No secrets in `.env`, code, or Terraform state — use Secrets Manager
- [ ] `.env` is in `.gitignore` — never committed
- [ ] Docker image runs as non-root user (`appuser`, UID 1000)
- [ ] ECR repository has `scan_on_push = true` for vulnerability scanning
- [ ] CloudFront uses `redirect-to-https` — HTTP is always upgraded
- [ ] S3 bucket has all public access blocked — only CloudFront OAC can read it
- [ ] App Runner instance role only has `secretsmanager:GetSecretValue` on the two specific secret ARNs
- [ ] `ALLOWED_ORIGINS` in CORS set to the exact CloudFront domain (not `*`)
- [ ] Billing alert set at $10/month
- [ ] Chat endpoints require membership (`require_member` enforced on GET message/portfolio/orders and DELETE)
- [ ] Paper trading data isolated per `user_handle` in DB (no cross-user queries)
- [ ] WebSocket closes with `1000` on clean leave so server records departure
- [ ] AI tools are read-only — no order placement from the LLM side
- [ ] `DEBUG=false` in production (prevents stack trace exposure in API responses)
