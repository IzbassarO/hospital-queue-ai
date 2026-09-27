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

All user-visible strings: `src/i18n/ru.ts` (Kazakh: `src/i18n/kk.ts`).

## Synthetic layer

The control centre mixes two kinds of content and labels them: the published model (forecasts, thresholds,
severities, crossing dates, ranks, the registry) and a synthetic layer generated in the browser (the queue of
referrals `Н-####`, the fourteen-day simulation, the scenarios). The synthetic layer lives in one folder,
[`src/synthetic/`](src/synthetic/README.md): `config.json` (every generation parameter, `enabled`, `seed`),
`scenarios.json`, the generators, and a README (RU/EN) that says what is synthetic, what is real, and how to edit,
switch off or delete the folder. The product reaches it through one line in `src/tower/synthetic.ts`.

```bash
VITE_SYNTHETIC=off npm run dev     # or: VITE_SYNTHETIC=off npm run build
docker build --build-arg VITE_SYNTHETIC=off -t hqai-frontend:published-only frontend   # the nginx image without the layer
```

`VITE_SYNTHETIC=off` (or `"enabled": false` in `config.json`) switches the layer off: the map, the notifications
and the specialist's decisions stay, the queue and the day simulation are replaced by a labelled empty state.
There is no `.env` file in this folder; the variable is read by Vite from the environment at build or dev time.
