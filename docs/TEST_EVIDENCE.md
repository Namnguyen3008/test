# VMEC-01 Test Evidence

Evidence is append-only. Secrets, prompt bodies and patient data are intentionally omitted.

## 2026-08-03 11:04 Asia/Saigon — continuation verification

| Check | Command | Result |
|---|---|---|
| Python formatting | `.venv\\Scripts\\python.exe -m ruff format --check src tests services vmec_data apps migrations` | PASS — 91 files formatted. |
| Python lint | `.venv\\Scripts\\python.exe -m ruff check src tests services vmec_data apps migrations` | PASS. |
| Static typing | `.venv\\Scripts\\python.exe -m mypy src services vmec_data apps --ignore-missing-imports` | PASS — 55 source files. |
| Backend/unit/integration/security | `.venv\\Scripts\\python.exe -m pytest -q` | PASS — 125 passed, 1 skipped. Skip is the pre-existing optional live/runtime gate; no skipped test is reported as passed. |
| Python dependencies | `.venv\\Scripts\\python.exe -m pip check` | PASS — no broken requirements. |
| Web dependency audit | `npm.cmd audit --audit-level=high` | PASS — 0 vulnerabilities. |
| Web lint/type/unit | `npm.cmd run lint:web`, `typecheck:web`, `test:web` | PASS — 3 unit tests. |
| Production web build | `npm.cmd run build:web` | PASS — `/`, `/admin`, `/appointments`, `/login`, `/operations`, `/review`. |
| Browser E2E | `npm.cmd run test:e2e` | PASS — 3 Playwright tests: emergency short-circuit, unauthenticated operations denial, real-API appointment empty states. |
| Migrations | `.venv\\Scripts\\alembic.exe heads`; `alembic upgrade head --sql` | PASS offline — single head `20260803_0004_worker_delivery`, full SQL chain generated. Persistent PostgreSQL application not run. |
| Real catalog review diagnostics | role-restricted read-only smoke | PASS — release completed, 447,525 rows, 947 sources, queue read-only, production approval false. |
| Real catalog lexical routing | aggregate smoke, no content printed | PASS — 6 hits, 1 canonical source, 14 allowlisted specialties. |
| Emergency catalog regression | compiler/detector tests plus aggregate smoke | PASS — 4,650 development rules, 2,330 hard negatives; production approved count remains zero. |
| Embedding planner | `scripts/plan_embedding_backfill.py` against ignored catalog | PASS planning only — 15,511 eligible per independent 768d space; full run refused. |
| Secret check | staged/tracked high-risk token-prefix scan | PASS after excluding intentional synthetic redaction fixtures; no live secret committed. |

### Tests explicitly covering mandatory risk areas

- Auth/RBAC negative cases and distributed rate limiting: PASS.
- Booking concurrency/idempotency/TTL/reconfirmation/no-show: PASS offline; real PostgreSQL race remains blocked.
- Emergency negation/hard-negative/version/production fail-closed: PASS.
- Gemini round-robin/retry/peer-only failover/both-model handoff: PASS.
- Dual-index isolation and lexical-only degradation: PASS.
- Citation/specialty grounding, extra-field/chain-of-thought rejection: PASS.
- Production import fail-closed: PASS.
- PHI-safe logs/metrics, secret redaction and forbidden review data: PASS.
- Docker Compose, real Redis replicas, real PostgreSQL migration/race, Helm render and full embeddings: NOT RUN; see blocker documents.

## 2026-08-03 12:00 Asia/Saigon — V4 final available verification

| Check | Command | Result |
|---|---|---|
| Python formatting | `.venv\Scripts\python.exe -m ruff format --check src tests services vmec_data apps migrations scripts` | PASS — 112 files formatted. Five pre-existing logging scripts were mechanically remediated in `1250629`. |
| Python lint | `.venv\Scripts\python.exe -m ruff check src tests services vmec_data apps migrations scripts` | PASS. |
| Static typing | `.venv\Scripts\python.exe -m mypy src services vmec_data apps --ignore-missing-imports` | PASS — 62 source files. |
| Full Python suite | `.venv\Scripts\python.exe -m pytest -q -rs` | PASS — 145 passed, 2 skipped, 1 deprecation warning. Skips: `VMEC_TEST_POSTGRES_URL` absent; POSIX-only shim on Windows. Neither skip is counted as PASS. |
| Python dependencies | `.venv\Scripts\python.exe -m pip check` | PASS — no broken requirements. |
| R2 retrieval contract | `pytest tests/test_retrieval/test_postgres_runtime.py` plus full suite | PASS offline — model predicates, dimensions, production filters, timeouts, failover and lexical degradation. Live PostgreSQL retrieval is NOT RUN. |
| R5 review workflow | `pytest tests/test_review_workflow.py tests/test_api/test_operations_routes.py -q` | PASS — 8 tests, including patient/staff denial and distinct second safety reviewer. |
| R3 backfill contract | `pytest tests/test_retrieval -q` | PASS — 31 tests; exact document instructions, guarded execution, persistent SQL contract, resume/dedupe/failure behavior. |
| Backfill refusal | `scripts/run_embedding_backfill.py --execution full ...` with both gates forced false and key empty | PASS — exit 2 before connection/provider creation; no live API call. |
| Migrations | `python -m alembic heads`; `alembic upgrade head --sql` | PASS offline — one head `20260803_0007_embedding_backfill`; full SQL chain rendered (40,016 bytes). PostgreSQL application is NOT RUN. |
| CI YAML | PyYAML safe parse and job assertions | PASS static — jobs `python`, `web`, `persistent-contract`, `containers`; CI itself is NOT RUN locally. |
| Helm secret boundary | `pytest tests/test_security/test_container_hardening.py -q` | PASS static — web pod is outside DB/Redis/Gemini secret guards. Helm render is NOT RUN. |
| Web dependencies | `npm.cmd audit --audit-level=high` | PASS — zero vulnerabilities. |
| Web lint/type/unit | `npm.cmd run lint:web`; `typecheck:web`; `test:web` | PASS — 5 Vitest tests. |
| Web production build | `NEXT_TELEMETRY_DISABLED=1 npm.cmd run build:web` | PASS — `/`, `/admin`, `/appointments`, `/login`, `/operations`, `/review`. |
| Browser E2E | `npm.cmd run test:e2e` | PASS — 3 Playwright tests in 15.7 seconds. This is local safe-adapter E2E, not the persistent/live Gemini chain. |
| Staged secret patterns | high-risk credential-prefix scan before each commit | PASS — zero matches. Values from local secret files/environment were not printed. |

### Explicitly NOT RUN

- Docker/Compose build/start/health and container vulnerability scan.
- Helm render/lint/install and staging deploy.
- Alembic against real PostgreSQL, real pgvector query, Redis multi-process behavior and worker restart/load tests.
- Persistent catalog import, Gemini embedding smoke/full backfill and real grounded agent chain.
- Backup restore drill and real clinical governance approval.

These omissions keep `INFRA_VERIFIED`, `EMBEDDING_BACKFILL_COMPLETE`, `DATA_APPROVED` and `PRODUCTION_READY` false.

### R3 persistent import addendum — 2026-08-03 12:05 Asia/Saigon

| Check | Command | Result |
|---|---|---|
| Minimal catalog projection | `pytest tests/test_retrieval/test_persistent_import.py -q` | PASS — deterministic IDs, citation gating, private-field exclusion, production zero-approved refusal and execution gates. |
| Real ignored catalog projection | `CatalogProjection(...).plan()` with aggregate-only output | PASS read-only — 48,217 candidates, 15,511 eligible/chunks, established registry digest; no row text printed. |
| Retrieval/import suite | `pytest tests/test_retrieval tests/integration/test_postgres_embedding_backfill.py -q` | PASS offline — 34 passed, 2 skipped because PostgreSQL URL is absent. |
| Migration | `alembic heads`; `alembic upgrade head --sql` | PASS offline — one head `20260803_0008_persistent_import`, 42,796-byte SQL chain. Live application NOT RUN. |
| Import refusal | `scripts/import_catalog_to_postgres.py ...` with persistent gate forced false | PASS — exit 2 before database connection; source catalog unchanged. |
| Post-importer full regression | Ruff format/check, mypy, `pip check`, `pytest -q -rs` | PASS — 116 formatted files, 63 typed source files, 148 passed and 3 explicit skips (two PostgreSQL-gated, one POSIX-only). |
