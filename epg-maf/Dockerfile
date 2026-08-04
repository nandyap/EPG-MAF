# syntax=docker/dockerfile:1.7
# ── EGP MAF backend — production image ───────────────────────────────
#
# Multi-stage:
#   1. builder installs the wheel with build deps.
#   2. runtime is a slim, non-root distro-less-ish image.
#
# Build context is expected to be ``epg-maf/``:
#
#   docker build -t egp-maf-backend:local .
#
# The image serves the FastAPI app on port 8080 via uvicorn. Container
# Apps injects the port via PORT — we honour it and fall back to 8080.

# ── 1. Builder ───────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Only files needed to resolve + install the wheel.
COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip \
 && pip wheel --wheel-dir /wheels .

# ── 2. Runtime ───────────────────────────────────────────────────────
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8080

# Non-root user (uid 10001 — arbitrary, avoids clashing with distro users).
RUN groupadd --system --gid 10001 app \
 && useradd  --system --uid 10001 --gid 10001 --home /home/app --create-home app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN pip install --no-index --find-links=/wheels egp-maf \
 && rm -rf /wheels

# Ship the prompt bundle so PromptService can load without network.
COPY src/egp_maf/prompts /app/prompts

USER app

EXPOSE 8080

# Health probe — Container Apps calls /health.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python -c "import urllib.request,os,sys; \
url='http://127.0.0.1:'+os.environ.get('PORT','8080')+'/health'; \
sys.exit(0 if urllib.request.urlopen(url,timeout=3).status==200 else 1)"

# Honour Container Apps' $PORT.
CMD ["sh", "-c", "exec uvicorn egp_maf.api.main:app --host 0.0.0.0 --port ${PORT:-8080} --workers 2 --proxy-headers --forwarded-allow-ips='*'"]
