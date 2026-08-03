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
