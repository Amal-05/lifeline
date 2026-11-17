# Deployment and recovery guide

## Configuration

Run Compose only for local demo. Production requires managed PostgreSQL/PostGIS and Redis, TLS termination, restricted network ingress, pinned image digests, non-root containers, resource limits, database backups, monitoring, and a secret manager. Set `JWT_SECRET_KEY`, `REGISTRY_ENCRYPTION_KEY`, `DEMO_MODE=false`, and disable demo user seeding. Generate independent random keys and retain encrypted recovery copies under two-person control. Do not use `.env.example` values outside synthetic local demos.

## Startup and health

1. Provision PostgreSQL with PostGIS and Redis on private networks.
2. Inject secrets and service URLs at runtime.
3. Run `alembic upgrade head` as a release step, then start API and worker processes.
4. Start the web image behind TLS and set the API origin in its build config.
5. Check `/health`, `/docs`, database readiness, Celery queue depth, and a synthetic authenticated read before opening access.
6. Import only a source-reviewed, licensed GeoJSON risk layer through `PUT /api/v1/risk/cells/import`; each feature must carry a valid H3 resolution 8 `cell_id` and normalized component scores in `properties.factors`.

## Backup and restore

For local rehearsal, `./infra/backup-restore.ps1 -OutputPath .\backups\lifeline.dump` writes a custom-format dump using `pg_dump`, restores it into a new temporary database, checks the restored event count, then removes only that uniquely named temporary database. Preserve the dump if needed; remove it securely after the rehearsal. Production must encrypt backups, retain the matching registry key separately, and rehearse point-in-time recovery on an isolated environment.

## Offline operations

Preload approved offline app artifacts and tiles before deployment. Validate device clock tolerance, battery/network constraints, gateway sync, and mesh relay behavior with synthetic events. Keep official warning channels and emergency numbers visible; Lifeline does not replace them.
