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

## 2026-08-03 14:15 Asia/Saigon — V5 Mode C verification

| Check | Command | Result |
|---|---|---|
| ZIP integrity and extraction policy | SHA-256 before/after plus pre-extraction entry validation | PASS — source hash unchanged; 8/8 entries passed traversal/root/ADS/symlink/reparse/type/duplicate/collision/containment checks. |
| Environment truth | command/service/listener and environment-presence audit | Mode C — Docker/Compose, psql, redis-cli and Helm absent; ports 5432/6379 closed; runtime URLs/key/gates absent. No value printed. |
| Migration graph | `python -m alembic heads`; `alembic upgrade head --sql` | PASS offline — one head `20260803_0008_persistent_import`; base-to-head SQL generated. Real migration is NOT RUN. |
| Catalog projection | `CatalogProjection(...).plan()` against ignored catalog | PASS read-only — development 48,217/15,511/15,511 and review 3,657/528/528 candidate/eligible/chunk counts; source unchanged; no persistent write. |
| Runtime wiring contracts | `pytest tests/test_security/test_runtime_wiring.py tests/test_security/test_container_hardening.py tests/test_api/test_readiness.py -q` | PASS — 11 tests for migration ordering, Redis isolation, scheduler, runtime data, Helm migration/probes/ingress and configurable approved manifest. Static evidence only. |
| Reviewer hardening | `pytest tests/test_review_workflow.py -q` | PASS — 7 tests, including atomic rollback, immutable replay mismatch and safety/adjudication priority. No real review performed. |
| Python format/lint/type | Ruff across `src tests services vmec_data apps migrations scripts`; mypy across source | PASS — 118 files formatted, lint clean, 63 typed source files. |
| Full Python suite | `python -m pytest -q` | PASS — 156 passed, 6 skipped, one dependency deprecation warning. Five skips require PostgreSQL/Redis; one is POSIX-only. Skips are not counted as PASS. |
| Web verification | lint, typecheck, Vitest, production build, `npm audit --audit-level=high` | PASS — 5 unit tests, all routes built, zero vulnerabilities. |
| Browser E2E | `npm.cmd run test:e2e` | PASS — 3 development safe-adapter scenarios in 15.8 seconds. |
| Manual browser/DevTools | local production web build + development API | PASS for local demo only — emergency warning rendered, chat POST returned HTTP 200, console warning/error count zero. Persistent/Gemini chain NOT RUN. |
| Persistent runtime contracts | `pytest tests/integration -q -rs` | NOT RUN locally — tests are prepared for PostgreSQL extensions/head, persistent import/backfill, Redis sessions/round-robin and PostgreSQL booking race; missing services caused explicit skips. |
| Secret scan | high-risk token-prefix scan of milestone paths | PASS — zero matches; local environment and secret files were not dumped. |

### V5 explicitly NOT RUN

- Docker Compose config/build/up/health/log and container vulnerability/SBOM checks.
- Empty real PostgreSQL migration, development/review persistent import and resume reconciliation.
- Live `gemini-embedding-2` plus `gemini-embedding-001` 768d smoke; full embedding backfill.
- Persistent auth/booking/worker/grounded-agent restart/load/recovery suite.
- Helm lint/template/install, backup restore drill, staging smoke/E2E/observability and rollback.
- Human reviewer approval and signed production governance promotion.
