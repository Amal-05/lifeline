# Decisions

- 2026-11-17: Use a new monorepo scaffold because the repository was empty; use SQLite only for direct local API development while Compose uses PostGIS-backed PostgreSQL.
- 2026-11-17: Use append-only signed ULID events; sync acknowledgements are idempotent by event ID. Browser key material is persisted in IndexedDB for reload continuity.
- 2026-11-17: Signature canonicalization covers every envelope field except `signature`, matching the event-envelope definition. Mesh hop mutation is a later M3 protocol migration.
- 2026-11-17: Pin the current Node LTS and latest stable compatible Python/JavaScript libraries. Add explicit Vite and Workbox `glob` overrides because the latest plugin lock otherwise selected versions covered by current npm audit advisories.
- 2026-11-17: Keep a worker process in M0 so the service topology is present; asynchronous triage work begins in M2.
- 2026-11-17: M1's local media route caps upload size and returns content-derived IDs. Durable object storage, resumable chunks, content scanning, auth ownership, and server-side media persistence are deferred to hardening.
- 2026-11-17: M1 supports GPS, last-known coordinates, and manual coordinate entry. A cached offline basemap for selecting a visual pin is deferred because no offline tile source was supplied.
- 2026-11-17: Docker is unavailable in this environment; Compose can be authored but its start-up acceptance cannot be demonstrated here.
- 2026-11-17: The package registry was initially unreachable in the restricted shell. Package installation succeeded after using the approved package-manager path, and both npm and Python lockfiles are generated from exact pins.
- 2026-11-17: A deterministic generated-set fallback keeps local protocol-law tests usable if Hypothesis cannot be installed; CI installs Hypothesis and runs its property-based cases.
- 2026-11-17: Docker's npm 11 clean install rejected a lock generated on Windows because it omitted foreign-platform optional packages (Lightning CSS and Rolldown). Use lockfile-aware `npm install --include=optional` in Linux image builds and CI to materialize the platform packages; this preserves locked versions while avoiding npm's cross-platform `npm ci` validation failure.
- 2026-11-17: TypeScript 7 needs its OS-specific native compiler package. Pin the Linux x64 package as an optional root dependency so it is represented in the cross-platform lockfile; use Debian slim for the build stage to provide a glibc Linux runtime.
