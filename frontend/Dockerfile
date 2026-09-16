# hospital-queue-ai web UI. Build context: frontend/ (docker compose service `frontend`).
# Stage 1 builds the static bundle; stage 2 serves it with nginx and proxies /api to the backend service,
# so the browser talks to one origin (no CORS) and the API URL is never baked into the bundle.

FROM node:22-alpine AS build
WORKDIR /app
# dependencies first (cached until the lockfile changes)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# no API key is compiled into the bundle: the proxy adds it server-side at request time (nginx.conf.template)
RUN npm run build

FROM nginx:1.29-alpine
# rendered to /etc/nginx/conf.d/default.conf at start; only DEMO_API_KEY is substituted
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
ENV NGINX_ENVSUBST_FILTER=DEMO_API_KEY
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
