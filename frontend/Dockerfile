# frontend/Dockerfile
# =============================================================================
# AIRP — Frontend PRODUCTION image (T-073)
#
# Multi-stage build: compile the React/Vite app to static assets, then
# serve them with nginx. This is the deployable artifact — the actual
# AIRP frontend deploys to Vercel directly from Git (see README.md), so
# this image exists for: (a) containerized deployment as an alternative
# to Vercel, (b) local verification of a real production build, and
# (c) parity with the backend's Docker packaging for the portfolio's
# DevOps story.
#
# NOT used by docker-compose.yml — local dev uses Dockerfile.dev's live
# Vite dev server instead. Build/run this one standalone:
#   docker build -t airp-frontend -f frontend/Dockerfile frontend
#   docker run -p 8080:80 -e BACKEND_UPSTREAM=http://api:8000 airp-frontend
#
# Build context: ./frontend
# =============================================================================

# ── Stage 1: build ────────────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# `npm run build` = `tsc && vite build` (package.json) — a real
# TypeScript compile plus the production Vite bundle, so this stage
# fails loudly on the same type errors CI's `npm run type-check` would
# catch, rather than shipping a broken bundle.
RUN npm run build


# ── Stage 2: serve ────────────────────────────────────────────────────────────
FROM nginx:1.27-alpine AS runtime

# gettext provides envsubst, used below to inject BACKEND_UPSTREAM into
# the nginx config at container start without baking a fixed backend
# hostname into the image.
RUN apk add --no-cache curl

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Where nginx proxies /api and /auth (see nginx.conf.template). Defaults
# to the docker-compose service name; override with
# `-e BACKEND_UPSTREAM=https://airp-api.onrender.com` for other targets.
ENV BACKEND_UPSTREAM=http://api:8000

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost/ || exit 1

# The official nginx image's entrypoint already runs envsubst over every
# file in /etc/nginx/templates/*.template into /etc/nginx/conf.d/ before
# exec'ing nginx — no custom entrypoint script needed.
CMD ["nginx", "-g", "daemon off;"]
