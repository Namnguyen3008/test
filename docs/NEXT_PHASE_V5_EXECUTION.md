# VMEC-01 next phase V5 execution

Last updated: 2026-08-03 14:15 Asia/Saigon. Evidence is append-only and contains aggregate results only.

## Recovery and safe extraction

- Repository root: `D:\ALL ABOUT PROJECT\PROJECT\P-208`.
- Branch at recovery: `codex/vmec-production-implementation`; starting commit `1e027a6`; worktree was clean.
- Source archive retained unchanged at `D:\ALL ABOUT PROJECT\SOURCE_DATASET\VMEC_Codex_Next_Phase_Pack_v5.zip`.
- SHA-256 before and after extraction: `9B533607670778C38A2634EDF08EF32423401B5E185A03D4D56DAE54765A9CF7`.
- Eight files were extracted through a temporary directory and atomically moved to `.codex/plans/VMEC_Codex_Next_Phase_Pack_v5/`.
- Every ZIP entry was validated before extraction for containment, rooted paths, `.`/`..` segments, ADS/colon syntax, symlink/reparse metadata, unsupported Unix file types, case-insensitive duplicate destinations and file/directory collisions. The first validator attempt failed closed before creating the target; the corrected unsigned-attribute check then passed.
- All required policy/status/blocker/V5 files were read completely in the requested order.

## Environment truth and execution mode

Mode C is active. `docker`, Docker Compose, `psql`, `redis-cli` and `helm` are unavailable. No matching Windows service or listener exists on ports 5432 or 6379. `DATABASE_URL`, `REDIS_URL`, `GEMINI_API_KEY` and both full-backfill gate variables are absent from the process environment. Values were never printed. No system software was installed.

Therefore PostgreSQL migrations, persistent import, live embedding smoke, real Redis behavior, backup restore and staging deployment remain `NOT_RUN`; none is reported as PASS.

## V5 remediation completed

Commit `fb4652f` fixes runtime configuration defects that static V4 evidence did not cover:

- Compose now runs a one-shot migration before API/worker/scheduler, uses PostgreSQL retrieval, passes a separate Redis session database, publishes database/cache only on loopback and runs Celery Beat.
- PostgreSQL-backed `/ready` verifies migration head, `vector`/`pg_trgm`/`unaccent`, general Redis and session Redis before reporting ready.
- Helm adds a migration hook, scheduler workload, TLS ingress, valid web TCP readiness, backend-only secrets, session Redis, and a read-only runtime-data PVC for the approved manifest and emergency catalog.
- CI persistent contract now provisions PostgreSQL/pgvector plus Redis and contains explicit real-service tests for migration/extensions, durable Redis sessions, global multi-replica Gemini rotation and PostgreSQL booking contention.
- Redis resources owned by the Gemini gateway close during application shutdown.
- Reviewer package imports are atomic and reject replay with changed immutable evidence; the queue prioritizes second-review/safety items; PHI-safe exports are deterministic and digest-bound.
- Reviewer provisioning/separation-of-duties, evidence handling and human-only promotion rules are documented in `docs/runbooks/CLINICAL_REVIEW_OPERATIONS.md`.

No migration was added; the single head remains `20260803_0008_persistent_import`.

## Verification performed

- Alembic single head: PASS offline. Full base-to-head SQL generation: PASS offline; this is not a database migration PASS.
- Targeted persistent/reviewer tests: `12 passed, 2 skipped` before remediation; skips were PostgreSQL-gated.
- Real catalog projection, read-only: development `48,217 candidates / 15,511 eligible / 15,511 chunks`; review `3,657 / 528 / 528`. Development digest remains `213b8dd1f6ce520df6bd87f0b560bcb14594a6c2a42e3659f3fd5f3670a86642`. Full backfill remained refused.
- Ruff format/check: PASS across 118 files. Mypy: PASS across 63 source files.
- Full Python suite: `156 passed, 6 skipped`; five skips are explicit PostgreSQL/Redis integration gates and one is the POSIX-only shim on Windows.
- Web lint/typecheck: PASS. Vitest: 5 passed. Next.js production build: PASS. `npm audit --audit-level=high`: zero vulnerabilities.
- Playwright: 3 passed. Manual in-app-browser demo: emergency short-circuit rendered, `POST /api/v1/chat` returned 200, and console had zero warning/error entries. This used the development safe adapter and is not real-stack evidence.
- Secret-prefix scan before commit: zero matches. Source ZIP and ignored catalog were not modified.

## Exact continuation commands

After the user independently makes Docker available, run from the repository root:

```powershell
docker version
docker compose version
docker compose config
docker compose build
docker compose up -d
docker compose ps --all
docker compose logs --no-color --tail 200 migrate api worker scheduler web postgres redis
docker compose exec api alembic current
docker compose exec -e VMEC_TEST_POSTGRES_URL=postgresql+psycopg://vmec:vmec@postgres:5432/vmec -e VMEC_TEST_REDIS_URL=redis://redis:6379/14 api python -m pytest tests/integration -q -rs
```

Then import development and review releases, rerunning each command to prove idempotency:

```powershell
docker compose exec api python scripts/import_catalog_to_postgres.py --catalog data/staging/vmec_catalog.sqlite3 --logical-release-id vmec-development-v2 --data-mode development
docker compose exec api python scripts/import_catalog_to_postgres.py --catalog data/staging/vmec_catalog.sqlite3 --logical-release-id vmec-review-v2 --data-mode review
```

With the Gemini key supplied through the runtime secret store and after PostgreSQL verification, run bounded smoke only:

```powershell
docker compose exec api python scripts/run_embedding_backfill.py --execution smoke --release-id "<persistent-release-uuid>" --data-mode development --space both --smoke-items 10
```

Do not run the full backfill unless quota/cost is accepted and both required gates are explicitly true. Follow `docs/runbooks/EMBEDDING_REBUILD.md` and `docs/runbooks/BACKUP_RESTORE.md` for the guarded full job and isolated restore drill.

## End state

```text
CODE_COMPLETE=true
INFRA_VERIFIED=false
PERSISTENT_IMPORT_COMPLETE=false
EMBEDDING_SMOKE_COMPLETE=false
EMBEDDING_BACKFILL_COMPLETE=false
REAL_STACK_E2E_COMPLETE=false
BACKUP_RESTORE_VERIFIED=false
DATA_APPROVED=false
STAGING_VERIFIED=false
PRODUCTION_READY=false
```
