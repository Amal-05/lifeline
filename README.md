# Lifeline

Lifeline is an offline-first disaster-response coordination platform. It stores an SOS on the device before attempting sync, then helps coordinators receive and route requests when connectivity returns. It coordinates rescue and flags risk; it does not predict disasters or replace official emergency numbers and warnings.

This repository implements M0 through M4: an offline signed SOS outbox, server sync, coordinator triage and dispatch, Android nearby mesh foundation, and synthetic H3 risk/pre-registration workflows. All included data is synthetic.

## Requirements

- Docker Compose for the full local stack
- Node.js 26.13.0 LTS and npm 11+
- Python 3.12 or 3.13

## Run the demo

```powershell
Copy-Item .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Open the field client at http://localhost:4173, operations dashboard at http://localhost:4173/dashboard, and API schema at http://localhost:8000/docs. The synthetic coordinator login is `coordinator@example.com` / `demo-only-change-me` (override with `.env`). For local development without Docker, install Python dependencies with `python -m pip install -r requirements.lock` followed by `python -m pip install --no-deps -e .`, install JavaScript dependencies with `npm install --include=optional`, start the API with `uvicorn services.api.main:app --reload`, and start Vite with `npm run dev --workspace @lifeline/web`.

## Checks

```powershell
python -m pytest
npm test
npm run typecheck
npm run build
npm run test:e2e --workspace @lifeline/web
```

## Milestones and limitations

M2 adds authenticated incident filters and details, urgency explanations, merge review, audit history, team matching, assignment status, road reports, CSV/GeoJSON export, and a dashboard event WebSocket. M3 adds Android Nearby Connections and a synthetic mesh harness. M4 adds synthetic H3 risk map cells, encrypted household registration, three 10-seed simulator scenarios, a k6 script, backup/restore rehearsal, deployment notes, privacy checklist, and a demo script. See `docs/demo`, `docs/mesh-protocol.md`, `docs/deployment.md`, and `docs/privacy-checklist.md`. Local demo media is held only long enough to compute a content-derived ID; durable media storage, device-lab Android verification, licensed translation/embedding models, public licensed offline map tiles, and production routing remain deployment tasks. Do not submit real rescue requests to this demo.
