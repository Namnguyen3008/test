# VMEC-01 Next Phase V4 Execution

Evidence is append-only. Last updated: 2026-08-03 Asia/Saigon.

## Recovery and environment truth

- Repository: `D:\ALL ABOUT PROJECT\PROJECT\P-208`.
- Branch: `codex/vmec-production-implementation`; recovery worktree was clean at `8ca8f98`.
- Source pack: `D:\ALL ABOUT PROJECT\SOURCE_DATASET\VMEC_Codex_Next_Phase_Pack_v4.zip`.
- The pack was opened read-only, every entry was checked for rooted paths, ADS names, traversal, duplicate destinations and Unix symlinks, then seven files were extracted to ignored `.codex/plans/VMEC_Codex_Next_Phase_Pack_v4/`. Source SHA-256 was identical before and after extraction.
- Alembic has one head: `20260803_0004_worker_delivery`.
- Docker, Docker Compose, `psql`, `redis-cli` and Helm are unavailable. No system software was installed.
- Process environment does not expose `DATABASE_URL`, `REDIS_URL`, `GEMINI_API_KEY`, `VMEC_ALLOW_FULL_EMBEDDING_BACKFILL` or `VMEC_PERSISTENT_PGVECTOR_VERIFIED`. Values were not read or printed. Local secret files remain ignored.
- Private data, reports, extracted plans and generated runtime artifacts remain ignored.

## V4 execution ledger

| Task | State | Evidence / next action |
|---|---|---|
| R0 recovery/truth audit | `COMPLETE` | Required status, evidence, decisions, blockers and V4 pack read in order; Git/migrations/tools/data state checked. |
| R1 persistent services | `BLOCKED_EXTERNAL` | Required CLIs and service URLs are absent; blocker remains truthful. |
| R2 PostgreSQL retrieval runtime | `IN_PROGRESS` | Highest-priority offline-capable task. Implement schema/runtime adapter/tests without claiming live PostgreSQL execution. |
| R3 import/backfill | `NOT_AUTHORIZED` | Full backfill flag absent; only dry-run/smoke-safe code is permitted. |
| R4 real auth/booking/worker | `BLOCKED_EXTERNAL` | Requires PostgreSQL/Redis processes. |
| R5 human approval workflow | `PENDING` | Continue after the R2 code milestone; never manufacture approval. |
| R6-R9 real-stack/release | `BLOCKED_OR_PENDING` | Continue all independent code/tests; runtime evidence remains NOT_RUN. |

## Baseline not repeated

The append-only baseline remains `125 passed, 1 skipped`, web lint/type/unit/build and three Playwright tests. V4 will rerun relevant and final gates after new implementation; prior PASS evidence is not relabeled as V4 runtime evidence.

## V4 completion ledger — 2026-08-03 12:00 Asia/Saigon

This section supersedes the earlier V4 task states while preserving the recovery evidence above.

| Task | State | Evidence / remaining gate |
|---|---|---|
| R0 recovery/truth audit | `COMPLETE` | `9a5b7ee`; source ZIP retained unchanged and safe extraction remains ignored. |
| R1 persistent services | `BLOCKED_EXTERNAL` | Docker/Compose/PostgreSQL/Redis/Helm CLIs and service URLs remain unavailable; no system software was installed. |
| R2 PostgreSQL retrieval runtime | `CODE_COMPLETE_OFFLINE` | `345855e`; PostgreSQL FTS + pg_trgm + isolated primary/fallback pgvector queries, canonical citation hydration, deterministic fusion, timeouts and lexical degradation are wired into the production graph selection. |
| R3 import/backfill | `EXECUTOR_COMPLETE_LIVE_RUN_BLOCKED` | `0988fa2`; persistent checkpoint/resume/dedupe/retry/rate-limit/quarantine executor and guarded CLI. Full and smoke provider runs are NOT RUN. |
| R4 real auth/booking/worker | `CODE_COMPLETE_OFFLINE_RUNTIME_BLOCKED` | Prior P0/P1/P7 evidence remains current; real PostgreSQL locks/races, Redis replicas and worker restart tests require services. |
| R5 human approval workflow | `CODE_COMPLETE_OFFLINE` | `367105f`; RBAC actions, evidence display, mandatory rationale, two-person safety review, optimistic concurrency, immutable decisions and fail-closed promotion report. No actual approval was created. |
| R6 grounded real-stack E2E | `BLOCKED_EXTERNAL` | Offline graph/security regressions and Playwright pass; PostgreSQL + Redis + live Gemini chain is NOT RUN. |
| R7 resilience/security | `CODE_COMPLETE_OFFLINE_RUNTIME_BLOCKED` | `1250629`, `3557152`; full static/security regression passes, Helm secret boundary fixed, CI pgvector contract prepared. Restart/load/container scans are NOT RUN locally. |
| R8 backup/restore | `RUNBOOK_COMPLETE_RESTORE_NOT_RUN` | Expanded aggregate-only encrypted PostgreSQL drill and rollback checks; tool/runtime absent. |
| R9 staging release | `BLOCKED_EXTERNAL` | Hardened Compose/Helm/CI artifacts exist; Helm/Docker rendering, images, SBOM, staging deploy and smoke are NOT RUN. |

### V4 commits

- `345855e` — persistent PostgreSQL hybrid retrieval runtime and migration `0005`.
- `367105f` — audited two-person clinical review workflow and migration `0006`.
- `0988fa2` — guarded persistent dual-embedding jobs and migration `0007`.
- `1250629` — repository formatter remediation for existing logging scripts.
- `3557152` — CI pgvector contract and Helm frontend secret isolation.

### Migration and data state

- One Alembic head: `20260803_0007_embedding_backfill`; the complete PostgreSQL SQL chain renders offline.
- Ignored development/review catalogs remain unchanged. Planner evidence remains 15,511 eligible chunks per model space.
- No persistent import, live embedding request, smoke backfill or full backfill was run.
- No clinical reviewer approval was created; production-approved row count remains zero.

### V4 end-state flags

```text
CODE_COMPLETE=true
INFRA_VERIFIED=false
EMBEDDING_BACKFILL_COMPLETE=false
DATA_APPROVED=false
PRODUCTION_READY=false
```

`CODE_COMPLETE=true` follows the V4 acceptance definition: the production-selected persistent retrieval adapter, isolated vector spaces, lexical degradation, approval workflow/audit, one migration head and offline tests are implemented with no known P0/P1 code gap. It does not imply infrastructure, data, backfill or production readiness.

## R3 importer completion — 2026-08-03 12:05 Asia/Saigon

Commit `5b4a8c0` closes the remaining offline R3 bridge: immutable SQLite catalogs are projected into citation-gated, minimal PostgreSQL retrieval records with deterministic release/record/chunk IDs, batch checkpoints, idempotent resume, source/content conflict refusal and a production zero-approved-row gate. Migration head is now `20260803_0008_persistent_import`.

The projection was run read-only against the ignored development catalog: 48,217 text candidates, 15,511 eligible records/chunks and registry digest `213b8dd1f6ce520df6bd87f0b560bcb14594a6c2a42e3659f3fd5f3670a86642`, matching prior planning evidence. PostgreSQL import remains NOT RUN. End-state flags above remain unchanged.
