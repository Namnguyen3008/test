# AGENTS.md — VMEC-01 Production Implementation Rules

## Mission

Build a complete production-oriented Vietnamese medical specialty-routing and appointment-booking product. Do not stop at plans, scaffolds, mock screens, partial demos, or generated code that has not been executed and tested.

## Repository boundary

- Work inside this repository unless the master prompt explicitly requires a read-only external check.
- Inspect current Git state before editing. Preserve user work.
- Work on `codex/vmec-production-implementation` or a similarly named feature branch.
- Never push directly to `main`/`master`, force-push, rewrite shared history, or delete remote branches.
- Keep focused commits after verified milestones.

## Secrets and privacy

- Never print, log, copy, screenshot, commit, or disclose secrets.
- Never enumerate the complete environment.
- It is permitted to check whether `GEMINI_API_KEY` exists, but never display its value.
- Do not expose Gemini credentials to the browser.
- Do not commit source datasets, extracted data, runtime volumes, caches, generated embeddings, or `.env` files.
- Never log raw symptom text, medical notes, free-text PHI, session cookies, authorization headers, or prompts containing patient data.
- Do not claim clinical, legal, privacy, or security approval without explicit evidence.

## Immutable product rules

- Emergency detection executes before LLM, RAG, memory, or booking.
- The assistant may suggest a specialty; it must not diagnose, prescribe, change medication, or give individualized treatment.
- Every patient-facing specialty suggestion includes citations and the Vietnamese disclaimer.
- Patient confirmation and staff approval are both required before an appointment reaches `CONFIRMED`.
- Rescheduling requires patient reconfirmation.
- Gemini may propose tools; trusted server code validates and executes them.
- No model-generated specialty, service, practitioner, facility, slot, source, or action may bypass allowlists and database checks.
- Production data mode fails closed when an approved corpus is absent.

## Exact Gemini model allowlist

### Generative model pool

Only these model IDs are permitted:

```text
gemini-3.1-flash-lite
gemini-3.5-flash-lite
```

No implicit `*-latest`, preview, pro, flash, or other fallback is allowed.

Initial model selection for new logical calls must alternate globally:

```text
3.1 → 3.5 → 3.1 → 3.5
```

Use Redis atomic state, not process-local state. Failover within a logical request may use the other allowed model for transient errors. If both fail, use deterministic fallback/human handoff.

### Embedding model pool

```text
Primary:  gemini-embedding-2
Fallback: gemini-embedding-001, text only
Dimension: 768
```

- Maintain independent vector spaces and independent pgvector indexes.
- Never query an Embedding 2 index with an Embedding 1 vector or vice versa.
- Lexical retrieval remains available if embedding services are degraded.
- No other embedding model is allowed.

Read `GEMINI_MODEL_ROUTING_POLICY.md` before implementing AI code.

## Required workflow

1. Read:
   - `CODEX_MASTER_IMPLEMENTATION_PROMPT.md`
   - `PROJECT_IMPLEMENTATION_SPEC.md`
   - `GEMINI_MODEL_ROUTING_POLICY.md`
   - `DATA_INGESTION_SPEC.md`
   - `ACCEPTANCE_CRITERIA.md`
2. Audit the repository and immutable data files.
3. Create/update `docs/IMPLEMENTATION_STATUS.md` and `docs/DECISIONS.md`.
4. Implement in coherent milestones.
5. After every milestone:
   - run relevant lint/type/tests;
   - fix failures rather than weaken tests;
   - update status evidence;
   - create a focused commit.
6. Run full acceptance verification before declaring completion.

## Tool usage

- Use multi-agent worktrees/subagents when available, with non-overlapping ownership and one lead integrator.
- Use GitHub integration for repository metadata/PR if available; otherwise local Git is sufficient.
- Use Linear if available, but never block implementation on it.
- Use 21st.dev/Figma as optional UI acceleration; review and test all generated code.
- Playwright and Chrome DevTools are mandatory for browser validation.
- DBHub/source SQLite access is read-only. Runtime schema changes use Alembic.
- Observability/Sentry integrations must be optional in local development.

## Code quality

- Python 3.12+, Ruff, strict typing, pytest and structured errors.
- TypeScript strict mode; avoid broad `any`.
- Validate Gemini structured output with Pydantic and semantic domain rules.
- Use database transactions, row locks, constraints and idempotency keys for appointment correctness.
- Implement tests for model rotation, model allowlist, embedding-space isolation, emergency handling, citations, prompt injection, PHI leakage, RBAC and double-booking.
- No TODO/FIXME or fake implementation in critical paths at final completion.
