# hospital-queue-ai web UI. Build context: frontend/ (docker compose service `frontend`).
# Stage 1 builds the static bundle; stage 2 serves it with nginx and proxies /api to the backend service,
# so the browser talks to one origin (no CORS) and the API URL is never baked into the bundle.

FROM node:22-alpine AS build
WORKDIR /app
# dependencies first (cached until the lockfile changes)
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# optional API key compiled into the bundle (the demo key from .env via docker-compose build args)
ARG VITE_API_KEY=""
ENV VITE_API_KEY=${VITE_API_KEY}
RUN npm run build

FROM nginx:1.29-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
