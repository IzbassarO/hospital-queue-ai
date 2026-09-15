# frontend

Web UI of hospital-queue-ai (React 18 + Vite + TypeScript). Screen map, API calls per screen, design rules and
API gaps: [docs/frontend.md](../docs/frontend.md).

```bash
make web-install   # npm ci
make web-dev       # http://localhost:5173, /api proxied to the backend on localhost:8000
make web-test      # Vitest smoke tests
make web-lint      # ESLint + Prettier check
make web-build     # tsc + production build -> dist/
make up            # docker: nginx on http://localhost:3000 serving the build, /api proxied to backend
```

All user-visible strings: `src/i18n/ru.ts`.
