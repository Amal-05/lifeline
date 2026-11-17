# Lifeline

Lifeline is an offline-first disaster-response coordination platform. It stores an SOS on the device before attempting sync, then helps coordinators receive and route requests when connectivity returns. It coordinates rescue and flags risk; it does not predict disasters or replace official emergency numbers and warnings.

This repository implements the M0 foundation and the M1 offline SOS and sync flow. All included data is synthetic.

## Requirements

- Docker Compose for the full local stack
- Node.js 26.13.0 LTS and npm 11+
- Python 3.12 or 3.13

## Run the demo

```powershell
Copy-Item .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

Open the field client at http://localhost:4173 and the API schema at http://localhost:8000/docs. For local development without Docker, install Python dependencies with `python -m pip install -r requirements.lock` followed by `python -m pip install --no-deps -e .`, install JavaScript dependencies with `npm install --include=optional`, start the API with `uvicorn services.api.main:app --reload`, and start Vite with `npm run dev --workspace @lifeline/web`.

## Checks

```powershell
python -m pytest
npm test
npm run typecheck
npm run build
npm run test:e2e --workspace @lifeline/web
```

## Scope and limitations

The first milestone provides a versioned protocol contract, Ed25519 signing and verification, event-set merge, HLC, Compose services, and CI. The second adds a four-language SOS form, IndexedDB outbox, offline persistence, and sync acknowledgment. Android mesh, triage, coordinator dashboard, authentication, and simulator are later milestones. The M1 API currently holds media only long enough to compute its content-derived ID; persistent media storage and secure key protection require deployment hardening. Do not submit real rescue requests to this demo.
