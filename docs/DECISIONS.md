# Architecture Decisions

## ADR-001: Incremental migration from the template

Keep the existing tested FastAPI package while introducing the target `apps/`, `services/`, `packages/`, `infra/`, and data-pipeline boundaries. Compatibility imports remain until all callers move. This preserves prior work and avoids a destructive rewrite.

## ADR-002: Exact Gemini model policy

The only generative IDs are `gemini-3.1-flash-lite` and `gemini-3.5-flash-lite`. Redis `INCR` is the authoritative global selector. A logical call increments once; retries and failover never increment it. Embeddings use `gemini-embedding-2` and text fallback `gemini-embedding-001` in independent spaces at 768 dimensions.

## ADR-003: Safe offline development

Network-dependent Gemini tests use injected transports and Redis abstractions. Missing credentials produce a deterministic handoff rather than hidden SDK defaults. Live diagnostics remain a separate readiness gate.

## ADR-004: Source immutability and production gating

The four source artifacts are ignored, hashed, streamed, and never modified. Development and research data remain distinct. Production import fails closed unless explicit approval/citation evidence is present.

## ADR-005: Privacy boundary

Emergency screening occurs before retrieval, model calls, memory, or booking. Model telemetry stores identifiers, purpose, model, timing, attempt status, and coded failure reasons only—never prompts, raw symptoms, authorization data, cookies, or secrets.

## ADR-006: Production corpus is an organizational gate

The supplied inventory reports zero production-ready rows. Code therefore permits development/review imports and rejects production mode before persistence. No automated transformation may manufacture clinical approval.

## ADR-007: Frontend dependency remediation

The web app uses Next.js 16.2.12 and explicit patched PostCSS/Sharp overrides because the upstream Next package manifest still pins versions covered by August 2026 advisories. `npm audit` reports zero vulnerabilities and the clean build/E2E suite passes. Remove overrides when an upstream Next release adopts patched dependency ranges.

## ADR-008: Persistent identity and booking transactions

Production identity and booking paths use SQLAlchemy/PostgreSQL mappings, opaque Redis session tokens and actor-scoped idempotency records. Slot and appointment mutations lock rows and emit append-only events plus outbox records in the same transaction. SQLite remains an offline test adapter, not evidence of PostgreSQL production concurrency.

## ADR-009: Development emergency rules retain conservative seeds

Compiled development/review snapshots merge the conservative seed rules to avoid losing previously verified high-risk phrases. Production snapshots do not merge unapproved seeds and continue to fail closed unless approved corpus rules exist.

## ADR-010: Grounded graph rejects rather than repairs model output

The graph calls emergency detection first, retrieves allowlisted/citation-mapped records, requests strict JSON, and rejects unknown specialties, unknown citations, low confidence, clinical claims or extra fields such as `analysis`. It returns human handoff instead of attempting to repair or infer missing grounding.

## ADR-011: Review queue is read-only until governance workflow exists

Reviewer and admin APIs expose only allowlisted, non-conflict review content and aggregate diagnostics. There is deliberately no endpoint that changes canonical status to ACCEPTED/GOLD; clinical approval must be a separately authorized, audited governance action.

## ADR-012: Outbox delivery is at-least-once with external idempotency keys

Workers claim rows with database locks, deliver outside the transaction using stable delivery keys, and persist retry/backoff/dead-letter state. External adapters must honor the key idempotently. Missing notification providers fail and retry; they are never treated as successful mock delivery.

## ADR-013: Telemetry records route templates only

OpenTelemetry and Prometheus record service, route template, method, status, latency and trace identifiers. Request/response bodies, query strings, concrete resource IDs, headers, cookies, prompts and symptoms are excluded. OTLP export is disabled until an endpoint is explicitly configured.

## ADR-014: Human review enables governance but never promotes by itself

ADR-011's read-only restriction is superseded by an audited workflow. Reviewer/admin users may claim, release and decide review items with mandatory rationales and optimistic versions. Safety-critical approval requires two distinct reviewers. Decisions are append-only, exports hash rationales, and promotion reports remain `production_approved=false`; an external authorized governance action is still required.

## ADR-015: Persistent embedding jobs deduplicate calls, not grounded chunks

Provider work is keyed by deterministic release/mode/model jobs and content hashes. Identical eligible text is embedded once per model, then the result is stored separately for every grounded chunk. The previous uniqueness constraint on `(model_id, dimensions, content_hash)` is removed because it suppressed duplicate grounded records; `(chunk_id, model_id)` remains the isolation boundary. Production eligibility requires both an approved canonical status and a clinical review status.

## ADR-016: Frontend pods receive no backend or AI secrets

Helm injects database and Redis secrets only into non-web workloads and the Gemini key only into the API. The web image receives no database, Redis or AI credential. CI statically enforces the template guards and contains a real pgvector migration/backfill contract job; local infrastructure readiness is still a separate evidence gate.

## ADR-017: Persistent import is a minimal deterministic projection

The source SQLite catalog is opened read-only and never copied wholesale into patient-facing persistence. Only retrieval-eligible text, a small allowlist of routing metadata, canonical source links, governance statuses and stable hashes are projected. Logical releases, records and chunks receive deterministic UUIDs, making resume idempotent. Source-ID/URL or content-hash conflicts fail closed, and production import refuses before writing when the approved eligible count is zero.

## ADR-018: Runtime workloads fail readiness when persistent dependencies drift

Compose and Helm run migrations before application rollout, use PostgreSQL retrieval explicitly, isolate session Redis from general counters/broker state and deploy Celery Beat as a singleton scheduler. A PostgreSQL-backed API reports ready only at the exact migration head with required extensions and both Redis connections healthy. Runtime corpora are mounted read-only and never baked into the image.

## ADR-019: Review evidence packages are atomic but not production approval

An admin review package is one transaction and replay must exactly match its immutable record/content/evidence/source/safety fields. Queue priority favors second-review and safety work. Safe exports have a versioned deterministic digest and hashed rationales, but remain audit evidence only; they cannot set production status without a separately authorized signed governance bridge and real reviewer evidence.

## ADR-020: Governance approval is a signed external trust boundary

Machine drafts use a distinct non-approvable schema with unresolved human fields set to null. Final approval uses
domain-separated Ed25519 signatures, strict canonical JSON, a capability-scoped public trust registry and an evidence
artifact that binds the immutable release, full source ledger, normalized content and policy classification. Reviewer
metadata is protected by the signature but is never manufactured by application code.

## ADR-021: Promotion creates an audited production overlay

Governance does not mutate the source SQLite catalog or overwrite development/review canonical statuses. A verified
manifest atomically creates a production-mode PostgreSQL overlay, per-row source-to-production audit records and a
separately signed receipt. Ordinary approved rows become ACCEPTED; only versioned policy candidates with two scoped
independent reviewers become GOLD. Exact replay returns the stored receipt, while modified or competing scope replay
fails closed.

## ADR-022: Revocation does not silently demote released data

Trust-key revocation blocks new operations. A committed receipt and row audit remain append-only. The supplied V6
schema has no signed supersession/revocation artifact, so the implementation rejects replacement rather than
inventing an unsigned demotion path. A future schema must define explicit authorization and audit semantics before
release supersession is enabled.
