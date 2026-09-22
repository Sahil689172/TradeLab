# ── Stage 1: dependency installer ────────────────────────────────────────────
FROM python:3.12-slim AS deps

WORKDIR /install
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install/packages -r requirements.txt


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=deps /install/packages /usr/local

# Copy application source
COPY app/ ./app/
COPY backend/ ./backend/

# Data directories (SQLite DB + Parquet files).
# Mount an EFS volume at /app/data in production for durability.
RUN mkdir -p /app/data/ohlcv /app/data/logs \
    && chown -R appuser:appuser /app/data

USER appuser

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    METADATA_DATABASE_URL="sqlite:////app/data/metadata.db" \
    DATABASE_URL="sqlite:////app/data/metadata.db" \
    PARQUET_STORAGE_DIR="/app/data/ohlcv" \
    LOG_DIRECTORY="/app/data/logs" \
    APP_ENV="production" \
    DEBUG="false" \
    HOST="0.0.0.0" \
    PORT="8000"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["python", "-m", "uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", \
     "--timeout-keep-alive", "75"]
