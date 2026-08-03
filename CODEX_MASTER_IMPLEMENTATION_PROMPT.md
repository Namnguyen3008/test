# VMEC-01 — CODEX MASTER IMPLEMENTATION PROMPT v2

You are the lead engineer, product integrator and verification owner. Implement the complete VMEC-01 product in this repository. Do not stop at analysis, a plan, scaffolding, mockups, TODOs or unexecuted generated code. Write working code, import pipelines, migrations, tests, documentation, containers, CI/CD and deployment artifacts; execute the system and fix failures.

## Repository and available assets

Expected repository on the user's machine:

```text
D:\ALL ABOUT PROJECT\PROJECT\P-208
```

The user has configured Codex with broad local tooling and has configured `GEMINI_API_KEY`. Use available tools productively, but obey `AGENTS.md`; never reveal or commit secrets.

Immutable data files are expected under `data/source/`:

```text
VMEC_FULL_DATA_RESEARCH_MASTER.zip
VMEC_FULL_DATA_DEVELOPMENT_READY.zip
VMEC_GLOBAL_SOURCE_LEDGER.csv.gz
VMEC_FULL_DATA_MASTER_INDEX.xlsx
```

## Read before editing

1. `AGENTS.md`
2. `PROJECT_IMPLEMENTATION_SPEC.md`
3. `GEMINI_MODEL_ROUTING_POLICY.md`
4. `DATA_INGESTION_SPEC.md`
5. `ACCEPTANCE_CRITERIA.md`

Inspect the actual repository. Preserve valuable existing code and user changes. If the repository conflicts with the spec, document the migration decision rather than blindly replacing it.

## Exact AI configuration — non-negotiable

### Generative models

Only:

```text
gemini-3.1-flash-lite
gemini-3.5-flash-lite
```

Initial selection for each new logical model call must alternate globally through Redis:

```text
3.1 → 3.5 → 3.1 → 3.5
```

Transient failure may fail over to the other allowed model. Do not call any third generative model, alias or preview.

### Embeddings

```text
Primary:  gemini-embedding-2
Fallback: gemini-embedding-001 for text
Dimensions: 768
Distance: cosine
```

Create separate vector spaces and separate indexes. Never mix vectors from the two models.

## Product invariants

- Emergency rules run before Gemini, retrieval, memory and booking.
- The assistant routes to specialties; it does not diagnose or prescribe.
- Patient confirmation and staff approval are both required before confirmation.
- The model proposes tools; server-side domain code validates and executes them.
- Every clinical suggestion requires valid source mappings and the disclaimer.
- Unreviewed clinical data is never silently treated as production-approved.
- Source artifacts are immutable.
- No secret or PHI is printed, logged or committed.

## Initial actions

1. Inspect Git branch/status/history and all repository files.
2. Detect runtime/tool versions and existing architecture.
3. Hash and inspect the four source artifacts without modifying them.
4. Check only the presence of required variables; never print values.
5. Verify the four exact Gemini model IDs are available using a safe diagnostic.
6. Create/switch to `codex/vmec-production-implementation`; never discard user changes.
7. Create/update:
   - `docs/IMPLEMENTATION_STATUS.md`
   - `docs/DECISIONS.md`
   - `docs/THREAT_MODEL.md`
   - `docs/DATA_FLOW.md`
8. Establish a milestone plan with acceptance evidence.
9. If connectors are unavailable, continue locally and record the limitation.

## Multi-agent/worktree plan

Use up to six non-overlapping agents when the environment supports it:

1. Architecture/Data — audit, schemas, importer, PostgreSQL/pgvector, migrations.
2. Backend/Domain — auth, RBAC, appointments, APIs, workers.
3. AI/Safety — Gemini gateway, round-robin, embeddings, LangGraph, emergency, RAG/evals.
4. Frontend — patient/staff/reviewer/admin UX.
5. Security/Platform — privacy, observability, Docker/Helm/CI.
6. QA/Integrator — tests, race/load/E2E, cross-component review.

The lead agent owns shared contracts, merge consistency and final verification. Avoid simultaneous edits to critical shared files without coordination.

# MILESTONES

## M0 — Repository audit and architecture

- Inventory reusable code and gaps.
- Define target tree and migration plan.
- Define OpenAPI/domain boundaries.
- Define data modes and approval policy.
- Define threat/privacy/model/data flows.
- Define exact model gateway interface and embedding-space schema.
- Commit architecture/docs after validation.

## M1 — Monorepo and local platform

- Set up/repair Next.js web, FastAPI API and worker.
- Configure Python/uv and pnpm/Turborepo when appropriate.
- Add PostgreSQL/pgvector, Redis and Docker Compose.
- Enable `pg_trgm` and `unaccent`.
- Add config validation, health/readiness and migrations.
- Add lint/type/test commands.
- Verify smoke startup before commit.

## M2 — Data platform

Implement `DATA_INGESTION_SPEC.md` fully:

- stream all archives;
- classify every table;
- import staging/curated/source mappings;
- preserve provenance/uncommon columns;
- quarantine malformed/sensitive records;
- implement idempotent release/import/resume;
- create domain runtime tables;
- produce QA/import reports;
- add importer unit/integration/smoke tests.

Do not hard-code only a few CSV filenames.

## M3 — Dual embedding and retrieval foundation

- Create canonical chunker compatible with fallback text limits.
- Create `knowledge_embeddings` with exact model ID/dimension/content hash.
- Create independent HNSW indexes for Embedding 2 and Embedding 1.
- Add quota-aware, resumable Celery embedding jobs.
- Backfill Embedding 2 for all eligible records/assets.
- Backfill Embedding 1 for all eligible text chunks.
- Add FTS/trigram indexes.
- Implement primary and fallback retrieval paths with reciprocal-rank fusion.
- Prove no cross-space vector query is possible.
- Add embedding/index health diagnostics and reports.

## M4 — Identity, RBAC and privacy

- Patient/staff/reviewer/admin roles.
- Argon2id and Redis sessions.
- secure cookies, CSRF and rate limiting.
- consent and memory controls.
- field encryption abstraction.
- PHI-redacted logs.
- append-only audit.
- authorization/privacy tests.

## M5 — Catalog and booking domain

- Facility, specialty, service, practitioner, schedule and slot models.
- Search and filters.
- transactional hold TTL.
- patient confirmation.
- staff approval/rejection.
- reschedule proposal/reconfirmation.
- cancellation/timeline.
- idempotency and audit.
- race tests proving no double booking.

## M6 — Gemini model gateway

Implement `GEMINI_MODEL_ROUTING_POLICY.md`:

- exact allowlist validation;
- Redis distributed alternating initial selection;
- logical call IDs and PHI-safe telemetry;
- per-model timeouts/retries/backoff/jitter;
- failover only to the other allowed model;
- per-model Redis circuit breakers;
- deterministic fallback/handoff when both fail;
- admin-only model diagnostics;
- tests across multiple processes/replicas;
- no hidden SDK default model.

## M7 — LangGraph, emergency and grounded routing

- deterministic emergency node first;
- intent/clarification/routing structured schemas;
- hybrid retrieval through the dual-space retrieval service;
- allowlist/source/citation semantic validation;
- low-confidence/handoff logic;
- tool proposal/execution separation;
- durable checkpoints and human interrupts;
- citations/disclaimer in patient-facing routing;
- safety/grounding/hallucination/prompt-injection/API-failure tests.

## M8 — Patient frontend

Implement polished accessible Vietnamese UX:

- auth/consent;
- streaming chat;
- emergency alert and 115 guidance;
- specialty/citation cards;
- slot search and hold countdown;
- patient confirmation;
- appointment timeline;
- cancel/reschedule;
- profile/memory controls;
- data-mode and API-degraded warnings;
- responsive/accessibility states.

## M9 — Staff/reviewer/admin frontend

- approval queue and appointment details;
- approve/reject/reschedule;
- escalation/low-confidence queues;
- clinical review queue;
- source/citation viewer;
- model round-robin/health diagnostics;
- embedding job/index diagnostics;
- operational dashboard;
- safe report exports.

## M10 — Workers, notifications and analytics

- hold/offer expiry;
- reminder scheduling and deduplication;
- embedding rebuild/resume;
- source freshness and data quality;
- model-health probes;
- PHI-safe analytics;
- safe template rendering.

## M11 — Security, observability and deployment

- CSP/HSTS/clickjacking/permissions policy.
- OpenTelemetry, metrics, traces and PHI-redacted JSON logs.
- optional Sentry.
- non-root/read-only Docker hardening.
- Helm chart and docs.
- GitHub Actions full gates.
- secret/dependency/container scanning.
- backup/restore, Gemini outage/quota and incident runbooks.

## M12 — Full verification and remediation

Run and fix until passing:

- Python lint/type/unit/integration;
- TypeScript lint/type/unit;
- Alembic from empty DB;
- full/import smoke and resume;
- model allowlist/round-robin/failover/circuit-breaker tests;
- dual-index population and isolation tests;
- retrieval degradation tests;
- emergency/grounding/security regression suites;
- Playwright patient/staff/reviewer flows;
- Chrome DevTools console/network/accessibility inspection;
- double-booking race;
- reminder deduplication;
- Docker builds;
- acceptance audit.

Do not weaken tests to pass. Fix root causes.

## M13 — Delivery

- Update all docs and status evidence.
- Generate architecture/data-flow diagrams in source-controlled textual form.
- Ensure `.env.example` uses exact allowed model IDs.
- Provide one-command startup/import/test instructions.
- Commit complete verified work.
- Push feature branch/open draft PR only if configured and safe.

## End-of-run requirements

Before the Codex session ends:

1. Run the broadest practical tests.
2. Update `docs/IMPLEMENTATION_STATUS.md` with exact evidence.
3. Record decisions and blockers.
4. Commit coherent safe work.
5. If not complete, write exactly one highest-priority next executable task plus required commands.
6. Never claim completion unless `ACCEPTANCE_CRITERIA.md` is satisfied.
