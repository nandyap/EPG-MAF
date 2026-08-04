# syntax=docker/dockerfile:1.7
# ── EGP MAF frontend — production image (Next.js standalone) ─────────
#
# Build context is expected to be ``epg-maf/egp_frontend/``:
#
#   docker build -t egp-maf-frontend:local .
#
# Uses Next 15's ``output: "standalone"`` (set in next.config.ts) to
# ship only the minimal server + traced deps.

# ── 1. Deps ──────────────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund

# ── 2. Builder ───────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

# ── 3. Runtime ───────────────────────────────────────────────────────
FROM node:20-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

# Non-root user.
RUN addgroup --system --gid 10001 app \
 && adduser  --system --uid 10001 --ingroup app --home /home/app app

# Next standalone output ships its own minimal node_modules.
COPY --from=builder --chown=app:app /app/.next/standalone ./
COPY --from=builder --chown=app:app /app/.next/static ./.next/static
COPY --from=builder --chown=app:app /app/public ./public

USER app

EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD wget -qO- --tries=1 --timeout=3 http://127.0.0.1:${PORT}/ >/dev/null || exit 1

CMD ["node", "server.js"]
