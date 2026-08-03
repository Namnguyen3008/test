# VMEC-01 Implementation Status

Last updated: 2026-08-03 (Asia/Saigon)

## Outcome

The implementation pack is installed on `codex/vmec-production-implementation`. A production-oriented vertical foundation now runs and is tested, but the full Definition of Done is **not satisfied**. Three external gates remain: Docker/Compose is unavailable on this machine; the supplied corpus reports zero production-approved rows; and the full 842,742-row dual-embedding backfill was not executed against external quotas. Auth and booking primitives exist, but complete PostgreSQL-backed API/UI wiring and clinical approval remain delivery work.

## Milestones and commits

| Milestone | State | Commit / evidence |
|---|---|---|
| M0 Audit/architecture | Implemented | `4e0d2b8`; architecture, decisions, threat and data-flow docs. |
| M1 Platform | Implemented, Docker runtime unverified | `3f40677`; web/API/worker, Postgres/pgvector, Redis, Compose, Alembic. |
| M2 Data importer | Implemented | `9556cc9`; streaming/resume/quarantine/production gate. |
| M3 Dual retrieval | Implemented foundation | `96d7b0c`; exact independent spaces, stable chunks, resume/dedupe and degradation. Full live backfill pending. |
| M4 Identity/privacy | Foundation implemented | `d77e8a4`; Argon2id, opaque Redis session, RBAC, CSRF, field encryption. Endpoint persistence/wiring pending. |
| M5 Booking | Domain implemented | `d77e8a4`; concurrency, TTL, idempotency, patient/staff confirmation and reschedule reconfirmation. PostgreSQL API wiring pending. |
| M6 Gemini gateway | Implemented/tested | `497d5a6`; Redis INCR selection, retry semantics, peer-only failover, circuit state, safe handoff, PHI-safe telemetry. |
| M7 Safety/grounding | Implemented foundation | `497d5a6`, `e6dfdd6`; emergency-first graph, allowlisted routing/tool/source validation and disclaimer. Full retrieval-to-graph integration pending. |
| M8 Patient web | Implemented vertical flow | `3f40677`, `512aa2f`; responsive Vietnamese portal and emergency E2E. Full authenticated booking screens pending. |
| M9 Operations web | Implemented dashboard shell | `3f40677`, `512aa2f`; masked queue/dashboard. Full staff/reviewer/admin API wiring pending. |
| M10 Workers/notifications | Foundation implemented | `e6dfdd6`; Celery entrypoint and reminder deduplication. Full schedules/analytics pending. |
| M11 Security/deployment | Implemented foundation | `5217320`; metadata-only AI logging, external submission off, security headers, hardened containers, CI, Helm and runbooks. |
| M12 Verification | Partial | Offline, live model capabilities, browser and E2E evidence below; Docker/Postgres integration not runnable locally. |
| M13 Delivery | Partial | Focused commits and docs complete; no push/PR requested. |

## Data evidence

- Four immutable artifacts detected, SHA-256 hashed and ignored.
- Development import: 101 tables, 447,525 rows, 0 quarantined.
- Review import: 101 classified tables, 395,217 rows, 11 quarantined.
- Catalog total: 842,742 imported rows; 947 canonical ledger sources per release.
- Resume rerun of `vmec-development-v2`: 0 new rows.
- Production import: rejected before database creation because the source summary has 0 production-ready rows.
- Local catalog/reports: ignored under `data/staging/` and `data/reports/`.

## Gemini/model evidence

`VERIFY_GEMINI_MODELS.ps1` passed without displaying the key:

```text
AVAILABLE: gemini-3.1-flash-lite
AVAILABLE: gemini-3.5-flash-lite
AVAILABLE: gemini-embedding-2
AVAILABLE: gemini-embedding-001
```

Live synthetic capability calls passed for both generative IDs and both embedding IDs; each embedding response contained exactly 768 values. Unit tests prove 3.1 → 3.5 → 3.1 alternation, shared-state multi-replica ordering, retry counter integrity, peer-only failover, safe both-model handoff, forbidden model rejection and PHI-safe telemetry.

## Verification evidence

```text
ruff format --check: pass
ruff check: pass
mypy: pass (38 source files at last full run)
pytest: 63 passed, 1 skipped
npm audit --audit-level=high: 0 vulnerabilities
web lint: pass
web strict typecheck: pass
web unit: 1 passed
Next.js production build: pass (/, /appointments, /operations)
Playwright E2E: 2 passed
Alembic PostgreSQL offline SQL generation: pass
production import fail-closed: pass
```

Manual local browser validation covered patient emergency submission, masked operations data, no browser console errors and a 390×844 responsive viewport without horizontal overflow. The real API returned `emergency=true`, contained 115 guidance, set `routine_booking_blocked=true` and exposed no `analysis` field.

## External blockers and remaining risk

1. Docker and Helm CLIs are unavailable, so Compose startup, empty-PostgreSQL migration, real Redis multi-process behavior, image hardening/scans and Helm rendering were not exercised locally.
2. The supplied corpus has no approved production rows. Production mode correctly fails closed; clinical/data-governance approval cannot be created by code.
3. Full live dual-embedding population was not run. This requires external quota/cost authorization and persistent PostgreSQL/pgvector infrastructure.
4. Auth/RBAC/booking are tested domain primitives but are not yet wired end-to-end through persistent APIs and all portal screens.
5. The emergency detector is a tested seed rule set; importing and validating the complete supplied emergency corpus into runtime rules remains required before clinical use.

Highest-priority next executable task: install/start Docker, run `docker compose up --build`, apply Alembic to empty PostgreSQL, import both releases into PostgreSQL, execute full dual-embedding backfill with checkpoints, then wire and test authenticated booking APIs/UI against that real stack.

## Continuation evidence — 2026-08-03 11:04 Asia/Saigon

This section supersedes the earlier remaining-work statements where new commits provide evidence. Historical evidence above is retained unchanged.

### Completed in this continuation

| Priority | State | Evidence |
|---|---|---|
| P0 persistent auth/RBAC/consent/audit | `CODE_COMPLETE_OFFLINE` | `7d4d7fb`, `2bd800f`; PostgreSQL mappings, Argon2id, opaque Redis sessions, CSRF rotation/revocation, distributed rate limiting and negative authorization tests. |
| P1 booking lifecycle | `CODE_COMPLETE_OFFLINE` | `7d4d7fb`, `e239f4a`; real APIs/portals, TTL holds, patient/staff confirmation, reschedule reconfirmation, idempotency, row locks and SQLite concurrency test. Real PostgreSQL race remains unverified. |
| P2 emergency runtime | `CODE_COMPLETE_DEVELOPMENT` | `a9dea1b`, `1496e65`, `e239f4a`; versioned catalog compiler plus conservative seed preservation. Production remains fail closed with zero approved rules. |
| P3 dual retrieval | `FOUNDATION_COMPLETE_BACKFILL_BLOCKED` | `8aab80d`; two isolated 768d spaces, citation/eligibility gate, deterministic lexical degradation, checkpoint/retry/quarantine planner. Full persistent backfill was not authorized or run. |
| P4 Gemini gateway | `CODE_COMPLETE_OFFLINE` | `a9dea1b`, prior `497d5a6`; exact two-model Redis round robin, retry/failover semantics, safe handoff and PHI-safe telemetry. Exact four model IDs were live capability-checked without printing the key. |
| P5 emergency-first grounded graph | `CODE_COMPLETE_OFFLINE` | `6ea19bc`; emergency → retrieval → structured Gemini JSON → validation → route/handoff. Unknown specialties/citations and extra `analysis` fields are rejected. |
| P6 role portals | `CODE_COMPLETE_OFFLINE` | `e239f4a`, `ecef5b5`; login/logout, patient booking, staff queue, read-only clinical review queue, admin audit/data/model diagnostics and explicit degraded states. No mock patient identity is used. |
| P7 worker/outbox/reminders/analytics | `CODE_COMPLETE_OFFLINE` | `fd82cf9`; Beat schedules, hold expiry, fixed-key reminders, idempotency-keyed outbox delivery, retry/backoff/dead-letter, no-show/reschedule events and identifier-free aggregate analytics. External notification provider is not configured. |
| P8 observability/security/deployment | `CODE_COMPLETE_OFFLINE` | `7cad58e`; OpenTelemetry FastAPI spans with OTLP option, Prometheus metrics, template-only structured request logs, existing hardened images/CI/runbooks. Docker/Helm execution remains blocked. |

### Current migrations

`20260803_0001 -> 20260803_0002_identity -> 20260803_0003_booking -> 20260803_0004_worker_delivery (head)`

`0004` adds retry/dead-letter state to `booking_outbox`, persistent unique reminders and the audited `NO_SHOW` appointment state.

### Current data and retrieval evidence

- Development catalog: 447,525 imported rows and 947 canonical sources; review catalog remains present from prior import evidence.
- Emergency development snapshot: 4,650 corpus rules plus conservative seed rules, 2,330 hard negatives, zero approved production rules.
- Dual-embedding plan: 48,217 text candidates; 15,511 citation-gated eligible chunks per independent model space; registry digest `213b8dd1f6ce520df6bd87f0b560bcb14594a6c2a42e3659f3fd5f3670a86642`.
- Full backfill remains refused because `VMEC_ALLOW_FULL_EMBEDDING_BACKFILL` is not enabled and persistent PostgreSQL/pgvector is not verified.
- Real catalog routing smoke: lexical-only safe degradation returned six grounded hits, one canonical source and 14 allowlisted specialty IDs for the aggregate smoke query.
- Reviewer runtime smoke: read-only queue returned three sample items; no status mutation endpoint exists, so code cannot manufacture ACCEPTED/GOLD approval.

### Final verification in this continuation

See `docs/TEST_EVIDENCE.md` for commands and timestamped output. Summary: Ruff format/check pass; mypy pass for 55 source files; pytest `125 passed, 1 skipped`; pip check pass; npm audit reports zero vulnerabilities; web lint/typecheck/3 unit tests/build pass; Playwright `3 passed`; Alembic offline chain and single head pass.

### End-state flags

```text
CODE_COMPLETE=false
INFRA_VERIFIED=false
EMBEDDING_BACKFILL_COMPLETE=false
DATA_APPROVED=false
PRODUCTION_READY=false
```

### V4 R3 addendum — 2026-08-03 12:05 Asia/Saigon

`5b4a8c0` adds the fail-closed persistent catalog importer and migration `20260803_0008_persistent_import` (new single head). The importer reads SQLite with `mode=ro`, stores no unallowlisted payload fields, preserves canonical source mapping/content hashes, checkpoints batches and produces zero duplicate persistent identities on resume. Its production path refuses before persistence when eligible approved count is zero.

Read-only real-catalog projection passed with 48,217 candidates, 15,511 eligible chunks and the established registry digest. Targeted retrieval/import tests pass (`34 passed, 2 infrastructure-gated skips`), and the complete Alembic chain renders offline to 42,796 bytes. No persistent row or vector was written; the five state flags remain exactly as recorded above.

Final post-importer regression supersedes the earlier V4 totals: Ruff format 116 files, Ruff lint PASS, mypy 63 source files, `148 passed, 3 skipped`, and no broken Python requirements. The three skips are two explicit PostgreSQL integration cases plus the POSIX-only shim test.

`CODE_COMPLETE=false` is intentional: the production graph still uses the safe lexical catalog adapter until the persistent PostgreSQL FTS/pg_trgm/dual-pgvector adapter and live backfill are implemented and verified. The external runtimes also block notification-provider and multi-process validation. No offline pass is promoted to production readiness.

## V4 implementation update — 2026-08-03 12:00 Asia/Saigon

This append-only update supersedes the earlier code-gap statement above. Runtime/readiness claims remain unchanged unless explicitly updated here.

### Completed code milestones

| Area | State | Commit / evidence |
|---|---|---|
| Persistent retrieval | `COMPLETE_OFFLINE` | `345855e`; migration `0005`, bounded PostgreSQL FTS/pg_trgm, independent 768d model predicates/indexes, citation hydration, deterministic fusion, timeouts and lexical-only degradation. |
| Human approval | `COMPLETE_OFFLINE` | `367105f`; migration `0006`, reviewer/admin workflow, patient/staff negative authorization, rationale, claims, optimistic versions, immutable decisions and two distinct safety reviewers. Reports never set production approval. |
| Persistent embedding jobs | `COMPLETE_OFFLINE_LIVE_BLOCKED` | `0988fa2`; migration `0007`, exact document instructions, checkpoint/resume, deduplicated provider work, per-chunk vectors, `SKIP LOCKED`, retry/backoff, quarantine and progress diagnostics. Full CLI fails closed without explicit gates. |
| CI/deployment hardening | `PREPARED_NOT_EXECUTED` | `3557152`; CI pgvector migration/backfill contract and Helm guards that keep database/Redis/Gemini secrets out of the web pod. CI/container/Helm execution is not local PASS evidence. |
| Backup and rollback | `RUNBOOK_COMPLETE_NOT_VERIFIED` | Aggregate-only PostgreSQL restore drill and exact embedding rebuild/rollback commands documented. |

### Current migration

`20260803_0001 -> 0002_identity -> 0003_booking -> 0004_worker_delivery -> 0005_retrieval_runtime -> 0006_clinical_review -> 0007_embedding_backfill (head)`

### Final available verification

- Ruff format: 112 files pass; Ruff lint passes.
- Mypy: 62 source files pass; `pip check` reports no broken requirements.
- Pytest: `145 passed, 2 skipped`; skips are the explicitly gated live PostgreSQL integration and a POSIX-only shim test.
- Web: dependency audit zero vulnerabilities; lint/typecheck pass; 5 Vitest tests pass; Next.js production build pass; 3 Playwright tests pass.
- Alembic: one head and full offline PostgreSQL SQL generation pass. Applying migrations to PostgreSQL is NOT RUN.
- Secret scan: staged changes contain no recognized live credential prefix. No environment or secret value was dumped.

### Remaining external gates

1. Start real PostgreSQL/pgvector and Redis, apply migrations, then run the CI-equivalent persistent test, auth/session/booking races and multi-process Gemini round robin.
2. Import the development/review release into persistent storage and run the bounded smoke backfill. Full backfill still requires explicit quota/cost authorization and both gates.
3. Obtain real authorized governance evidence; code and synthetic tests cannot set `DATA_APPROVED=true`.
4. Execute Compose/Helm/container scans, backup restore drill, real grounded E2E and staging deployment.

```text
CODE_COMPLETE=true
INFRA_VERIFIED=false
EMBEDDING_BACKFILL_COMPLETE=false
DATA_APPROVED=false
PRODUCTION_READY=false
```

## V5 Mode C execution update — 2026-08-03 14:15 Asia/Saigon

This append-only update supersedes earlier runtime-wiring gaps but does not change any persistent/live readiness claim. The V5 archive was safely extracted without changing its SHA-256 or source file. Runtime audit found no Docker/Compose, PostgreSQL CLI/service, Redis CLI/service, Helm, persistent URLs, Gemini credential or backfill gates; no system software was installed.

Commit `fb4652f` adds the feasible Mode C remediation: migration-ordered Compose, explicit PostgreSQL retrieval, distinct Redis session wiring, Celery Beat, dependency-aware readiness, Helm migration/scheduler/TLS/runtime-data wiring, PostgreSQL+Redis CI contracts, persistent booking/session/round-robin tests, deterministic reviewer evidence and atomic/tamper-detecting package import. No migration was needed; the single head remains `20260803_0008_persistent_import`.

Read-only projection reconfirmed development `48,217 candidates / 15,511 eligible` and review `3,657 / 528`; neither was written to PostgreSQL. Full Python regression is `156 passed, 6 skipped`; five skips are explicit missing PostgreSQL/Redis gates and one is platform-specific. Web lint/type/5 unit/build/audit and three Playwright scenarios pass. Manual browser validation observed an emergency short-circuit, HTTP 200 from the local development API and no console warnings/errors. This safe-adapter evidence is not `REAL_STACK_E2E_COMPLETE`.

Remaining hard blockers are real PostgreSQL/pgvector and Redis activation, persistent imports, two live 768d embedding smoke calls, explicitly authorized full backfill, restore drill, staging deploy and real reviewer/governance approval. Exact continuation commands are in `docs/NEXT_PHASE_V5_EXECUTION.md`.

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

## V6 signed governance update — 2026-08-03 15:42 Asia/Saigon

This append-only update adds a fail-closed signed governance bridge and migration
`20260803_0009_governance_bridge` in commit `945ba1b`. Machine draft generation against the immutable development release produced
15,511 eligible rows: 12,345 policy GOLD candidates and 3,166 ordinary ACCEPTED candidates, with 528
safety-critical rows and all 947 canonical ledger sources bound by digest. The draft and evidence artifacts are
ignored; their unresolved identity/authorization/signature fields are `null`.

Ed25519 verification, trust-key capability/validity/revocation, evidence recomputation, scope/content/source binding,
GOLD classification, transaction locking, source-preserving production overlay, append-only per-row audit, signed
receipt, replay/idempotency and tamper refusal are implemented. No promotion endpoint exists. Compose/Helm promotion
contracts are explicit and disabled by default.

Available Python regression is 173 passed and 7 skipped. The real-catalog governance contract passed locally. Six
integration skips require PostgreSQL/Redis URLs and one is platform-specific; skipped checks are not PASS. Live
PostgreSQL migration/promotion, persistent import, embeddings, backup/restore, real-stack E2E and staging remain
blocked by missing runtimes and artifacts. See `docs/NEXT_PHASE_V6_EXECUTION.md` and
`docs/blockers/V6_EXTERNAL_RUNTIME_AND_APPROVAL.md`.

The user's external-approval statement does not satisfy the signed manifest contract by itself. No reviewer,
authorization reference, signature or clinical approval was fabricated; no source row or canonical status was
changed.

```text
CODE_COMPLETE=false
INFRA_VERIFIED=false
PERSISTENT_IMPORT_COMPLETE=false
GOVERNANCE_BRIDGE_COMPLETE=true
GOVERNANCE_MANIFEST_VERIFIED=false
DATA_PROMOTION_COMPLETE=false
EMBEDDING_SMOKE_COMPLETE=false
EMBEDDING_BACKFILL_COMPLETE=false
REAL_STACK_E2E_COMPLETE=false
BACKUP_RESTORE_VERIFIED=false
DATA_APPROVED=false
STAGING_VERIFIED=false
PRODUCTION_READY=false
```
