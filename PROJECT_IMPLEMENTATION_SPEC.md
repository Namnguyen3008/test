# VMEC-01 — Complete Product Implementation Specification

## 1. Product

Build a Vietnamese AI assistant for:

- deterministic emergency-first safety screening;
- non-diagnostic specialty routing with citations;
- clarifying questions and human handoff;
- facility/service/practitioner/slot search;
- slot hold, patient confirmation, staff approval, rescheduling, cancellation and reminders;
- patient, staff, clinical-reviewer and admin interfaces;
- consent-aware profile memory;
- data governance, audit, analytics and operations.

## 2. Target architecture

### Monorepo

```text
apps/
  web/                      Next.js App Router patient/staff/reviewer/admin UI
  api/                      FastAPI REST + SSE
  worker/                   Celery/background jobs
packages/
  ui/                       shared design system
  contracts/                generated API types/schemas
  config/                   shared lint/build config
services/
  model_gateway/            Gemini rotation/failover/telemetry abstraction
  retrieval/                lexical + dual-space vector retrieval
  data_pipeline/            import, validation, embedding and reports
data/
  source/                   immutable private source artifacts
  staging/                  ignored extracted/intermediate data
  reports/                  ignored generated reports
infra/
  docker/
  helm/
scripts/
tests/
  e2e/
  load/
  safety/
  security/
docs/
```

### Stack

- Frontend: Next.js App Router, React, strict TypeScript, Tailwind CSS and accessible component primitives.
- Backend: Python 3.12+, FastAPI, Pydantic 2, SQLAlchemy 2 and Alembic.
- Database: PostgreSQL + pgvector + `pg_trgm` + `unaccent`.
- Redis: sessions, rate limits, distributed round-robin state, circuit breakers, Celery broker/result backend.
- Worker: Celery or an equivalently robust Python worker already present in the repo.
- Agent orchestration: LangGraph with persistence and explicit human interrupts.
- Gemini SDK: official Google Gen AI SDK.
- Object storage: local filesystem adapter for development; S3-compatible adapter for production.
- Observability: OpenTelemetry, Prometheus-compatible metrics and PHI-redacted JSON logs; optional Sentry.
- Local: Docker Compose.
- Production: separate containers and Helm chart.

## 3. Exact Gemini configuration

### Generative model allowlist

```text
gemini-3.1-flash-lite
gemini-3.5-flash-lite
```

New logical calls use Redis-backed distributed round-robin:

```text
3.1 → 3.5 → 3.1 → 3.5
```

Transient failure may fail over to the other allowed model. No third model is permitted.

### Embeddings

```text
Primary: gemini-embedding-2
Text fallback: gemini-embedding-001
Dimensions: 768
Distance: cosine
```

Build two independent vector indexes and lexical retrieval. See `GEMINI_MODEL_ROUTING_POLICY.md`.

## 4. Identity, access and privacy

- Roles: `PATIENT`, `STAFF`, `CLINICAL_REVIEWER`, `ADMIN`.
- Argon2id password hashing.
- Opaque Redis-backed sessions with HttpOnly/Secure/SameSite cookies.
- CSRF protection for state-changing requests.
- Optional OIDC adapter.
- RBAC enforced server-side and tested for every protected endpoint.
- Minimum-necessary patient profile data.
- Consent grants and revocation for memory/personalization.
- Field-encryption abstraction for free-text clinical data.
- Production logs contain no raw symptom text or PHI.
- Append-only audit events with actor, action, target, timestamp, trace and outcome, not sensitive content.

## 5. Catalog and appointment domain

Entities:

- facilities;
- departments;
- specialties;
- services;
- practitioners;
- schedules;
- slots;
- appointments;
- holds;
- reschedule offers;
- appointment events;
- notifications.

State machine:

```text
AVAILABLE
  → HELD
  → PATIENT_CONFIRMED
  → PENDING_STAFF_APPROVAL
  → CONFIRMED
```

Additional states:

```text
RESCHEDULE_PROPOSED
CANCELLED
REJECTED
EXPIRED
COMPLETED
NO_SHOW
```

Requirements:

- transactional slot holds with TTL;
- row-level locking or equivalent serializable protection;
- partial unique constraints for active reservations;
- idempotency keys on mutations;
- no confirmation without patient confirmation and staff approval;
- reschedule proposal requires reconfirmation;
- timeline/audit events for every transition;
- race and replay tests.

## 6. AI conversation graph

LangGraph nodes:

1. normalize input;
2. deterministic emergency gate;
3. classify intent using round-robin Gemini gateway;
4. retrieve grounded records;
5. ask clarification or propose specialty;
6. validate grounding/citations;
7. decide confidence/handoff;
8. propose an allowlisted tool call;
9. validate and execute server-side action;
10. assemble response with citations/disclaimer;
11. persist checkpoint and audit metadata.

The domain database remains the source of truth. The model never executes SQL or directly changes appointment state.

Approved tool proposals include:

- `search_slots`
- `hold_slot`
- `confirm_patient_choice`
- `cancel_appointment`
- `request_reschedule`
- `respond_to_reschedule_offer`
- `get_appointment_status`
- `handoff_to_staff`

## 7. Emergency-first safety

- Load deterministic adult, pediatric, maternal/newborn rules and hard negatives.
- Evaluate negation, temporality, quoted text and family-member context.
- Positive emergency result stops routine booking and model-led routing.
- Return clear Vietnamese action to call 115 or go to emergency care.
- Do not include a diagnosis.
- Log only rule IDs/category/action, not raw symptom content.
- Regression suites must prioritize critical recall.

## 8. Hybrid retrieval and citations

### Data layer

Create:

- `knowledge_records` with source/review/conflict/content metadata;
- `knowledge_chunks` with normalized text and token/chunk metadata;
- `knowledge_embeddings` with model-specific vectors;
- `knowledge_record_sources` / citation bridge;
- specialized runtime tables for emergency, routing, questions, FAQ, content and tests.

### Search

Normal route:

- PostgreSQL FTS + trigram;
- Embedding 2 vector search;
- reciprocal-rank fusion;
- metadata filters;
- Gemini round-robin reranking;
- citation validation.

Fallback route:

- PostgreSQL FTS + trigram;
- Embedding 1 vector search for text;
- reciprocal-rank fusion;
- citation validation.

If no valid citation mapping exists, do not present the recommendation as grounded.

## 9. Data modes

- `development`: conflict-free development data; UI/API show persistent non-approved warning.
- `review`: research master and reviewer queues.
- `production`: only verified `GOLD`/`ACCEPTED`, no conflicts, valid approval evidence and citations.

Production mode must fail closed. It must never silently fall back to development data.

## 10. Patient UI

- sign up/in/out;
- consent and privacy;
- streaming chat;
- prominent emergency UI;
- specialty cards with confidence, rationale, alternatives and citations;
- slot filtering/search;
- hold countdown;
- confirmation and appointment timeline;
- cancel/reschedule;
- profile/memory controls;
- accessibility and responsive Vietnamese UI;
- explicit model/API degraded state without exposing implementation secrets.

## 11. Staff/reviewer/admin UI

- pending appointment queue;
- approve/reject/reschedule;
- appointment and audit timeline;
- low-confidence and human-handoff queues;
- clinical data review queue;
- source/citation viewer;
- model health and rotation diagnostics for admins;
- embedding job/index status;
- operational dashboards;
- safe exports without raw PHI.

## 12. Worker jobs

- expire holds/offers;
- send reminders with deduplication;
- import datasets;
- build/resume Embedding 2 and Embedding 1 indexes;
- source freshness checks;
- data-quality reports;
- model-health probes;
- retention cleanup;
- PHI-safe aggregate analytics.

## 13. Security

- CSP, HSTS, clickjacking and permissions policy;
- CSRF and action-aware rate limits;
- strict validation/output encoding;
- no secrets in bundles/logs;
- append-only audit;
- dependency/container/secret scans;
- prompt-injection, indirect-injection and data-exfiltration tests;
- authorization tests for all protected routes;
- non-root/read-only container hardening where possible.

## 14. Observability

Metrics/traces include:

- API latency/errors;
- emergency triggers;
- handoffs;
- booking conflicts;
- selected initial Gemini model;
- fallback model and reason;
- per-model latency/errors/429/5xx;
- round-robin sequence integrity;
- retrieval mode and latency;
- embedding backlog/success/failure by model;
- source/citation validation failures;
- worker jobs.

No raw PHI or prompts in production telemetry.

## 15. Deployment

- `docker compose up --build` starts web, API, worker, PostgreSQL/pgvector and Redis.
- Separate images for web/API/worker.
- Alembic migration and data-import commands.
- Helm chart with secrets references, ingress, autoscaling, disruption budgets and resource limits.
- GitHub Actions for lint, typecheck, tests, migrations, import smoke, E2E, image build and security scans.
- Backup/restore and incident runbooks.
