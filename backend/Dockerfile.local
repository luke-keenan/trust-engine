# ── Stage 1: Build ──
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .

# CPU-only torch FIRST (separate layer → cached on rebuilds)
RUN pip install --no-cache-dir --prefix=/install \
    torch --index-url https://download.pytorch.org/whl/cpu

# Remaining deps
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Stage 2: Runtime ──
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /install /usr/local

WORKDIR /app
COPY . .

RUN if [ ! -f ensemble.pt ]; then python backend/train.py; fi

RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

ENV PYTHONUNBUFFERED=1
ENV DATABASE_URL=sqlite+aiosqlite:///./governance.db

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["sh", "-c", "alembic -c alembic.ini upgrade head && uvicorn app:app --host 0.0.0.0 --port 8000"]   