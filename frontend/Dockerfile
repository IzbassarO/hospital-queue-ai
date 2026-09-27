# hospital-queue-ai web UI. Build context: frontend/ (docker compose service `frontend`).
# Stage 1 builds the static bundle; stage 2 serves it with nginx and proxies /api to the backend service,
# so the browser talks to one origin (no CORS) and the API URL is never baked into the bundle.

FROM node:22-alpine@sha256:0a7108bf6c7bf5de370ffb1a3ed6be93d405b43ff159f681a8d18c0e2bc2e402 AS build
# tag node:22-alpine, digest resolved 2026-09-27 with `docker buildx imagetools inspect node:22-alpine`
WORKDIR /app
# dependencies first (cached until the lockfile changes)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# no API key is compiled into the bundle: the proxy adds it server-side at request time (nginx.conf.template).
# --build-arg VITE_SYNTHETIC=off builds the UI without the synthetic layer (src/synthetic/README.md); empty = on.
ARG VITE_SYNTHETIC=
ENV VITE_SYNTHETIC=$VITE_SYNTHETIC
RUN npm run build

FROM nginx:1.29-alpine@sha256:5616878291a2eed594aee8db4dade5878cf7edcb475e59193904b198d9b830de
# tag nginx:1.29-alpine, digest resolved 2026-09-27 with `docker buildx imagetools inspect nginx:1.29-alpine`
# rendered to /etc/nginx/conf.d/default.conf at start; only DEMO_API_KEY is substituted
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=DEMO_API_KEY
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
