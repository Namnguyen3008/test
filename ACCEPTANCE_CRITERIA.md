# VMEC-01 — Acceptance Criteria / Definition of Done

Codex must not declare completion until applicable criteria pass or a true external blocker is documented with reproducible evidence.

## 1. Repository and developer experience

- Clean documented monorepo.
- `.env.example` based on `.env.vmec.example` and no committed secrets.
- One-command local startup.
- Focused commits on a feature branch.
- `docs/IMPLEMENTATION_STATUS.md` contains milestone evidence and exact commands/results.
- `docs/DECISIONS.md` records significant architecture choices.

## 2. Local startup

```powershell
docker compose up --build
```

Starts PostgreSQL/pgvector, Redis, API, worker and web with health/readiness checks.

## 3. Exact model configuration

- Generative allowlist contains exactly:
  - `gemini-3.1-flash-lite`
  - `gemini-3.5-flash-lite`
- No forbidden Gemini generative model can pass config validation.
- Initial logical calls alternate through Redis-backed round-robin 3.1/3.5 across replicas.
- Counter increments once per logical call, not per retry.
- Transient failure can fail over only to the other allowed model.
- Both failing returns deterministic safe fallback/handoff.
- Admin diagnostics report model health without secrets/PHI.

## 4. Embeddings and retrieval

- Primary model is exactly `gemini-embedding-2` at 768 dimensions.
- Text fallback is exactly `gemini-embedding-001` at 768 dimensions.
- Separate vector spaces and separate pgvector indexes exist.
- Tests prove cross-model vector/index mixing is impossible.
- Development corpus imports idempotently.
- Both eligible embedding indexes can be built/resumed.
- Normal retrieval uses lexical + Embedding 2.
- Primary degradation uses lexical + Embedding 1 for text.
- Both embedding services unavailable results in lexical-safe degradation or handoff.
- Grounded results map to valid global sources.

## 5. Data

- Four immutable source artifacts detected and hashed.
- Development archive imports with streaming and bounded memory.
- Research corpus is restricted to review/audit paths.
- Source ledger imports and citation bridges validate.
- Quarantine/reporting works.
- Production mode fails closed without approved clinical corpus.

## 6. API/security

- OpenAPI available.
- Auth, RBAC, CSRF, rate limiting and error contracts tested.
- Patient/staff/reviewer/admin endpoints implemented.
- No raw PHI/prompts/secrets in logs.
- Append-only audit trail.
- Protected metrics/admin diagnostics in production.

## 7. Safety and AI

- Emergency detector runs before Gemini/RAG/memory/booking.
- Emergency cases stop routine booking.
- Structured outputs are syntactically and semantically validated.
- Invalid specialty/tool/source IDs are rejected.
- Recommendations include valid citations and disclaimer.
- Low confidence or Gemini failure routes safely to human handoff.
- Prompt-injection, indirect-injection and PHI-exfiltration suites pass.

## 8. Booking

- Search → hold → patient confirm → staff approve → confirmed works E2E.
- Concurrent users cannot book the same slot.
- Hold/offer expiration is correct.
- Reschedule requires patient reconfirmation.
- Mutations are idempotent.
- Reminder deduplication works.

## 9. UI

- Patient and staff/reviewer/admin portals are responsive and accessible.
- Loading, empty, error, offline, API-degraded and permission-denied states exist.
- Development-data warning is persistent when applicable.
- Citations and source details are accessible.
- Playwright E2E passes.
- Chrome DevTools inspection has no critical console/network/accessibility failures.

## 10. Quality gates

- Python Ruff/typecheck/pytest pass.
- TypeScript lint/strict typecheck/unit tests pass.
- Alembic migration from empty DB passes.
- Data-import smoke and resume tests pass.
- Model rotation/failover tests pass.
- Dual-embedding/index isolation tests pass.
- Emergency/grounding/security regression tests pass.
- Playwright E2E passes.
- Double-booking race test passes.
- Docker images build.
- CI has no unresolved critical secret/dependency/container findings.

## 11. Deployment and operations

- Hardened Docker Compose.
- Helm chart and deployment guide.
- OpenTelemetry/metrics/logging.
- Backup/restore runbook.
- Gemini outage/quota/circuit-breaker runbook.
- Embedding rebuild/rollback runbook.
- Incident response and known limitations.

## 12. Final completion evidence

`docs/IMPLEMENTATION_STATUS.md` must include:

- commit SHAs per milestone;
- test command and result summaries;
- data import counts;
- model diagnostics;
- embedding index counts;
- E2E/race/security evidence;
- remaining external blockers, if any.
