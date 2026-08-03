# VMEC-01 — CODEX CONTINUE IMPLEMENTATION PROMPT v2

Continue the existing implementation in this repository. Do not restart the project, discard working code, or redo a milestone already verified with evidence.

## Recovery

Read:

1. `AGENTS.md`
2. `PROJECT_IMPLEMENTATION_SPEC.md`
3. `GEMINI_MODEL_ROUTING_POLICY.md`
4. `DATA_INGESTION_SPEC.md`
5. `ACCEPTANCE_CRITERIA.md`
6. `docs/IMPLEMENTATION_STATUS.md`
7. `docs/DECISIONS.md`

Then inspect:

- current branch/status/diff/recent commits;
- uncommitted/partial work;
- test failures and last logs;
- current containers/migrations if relevant;
- required source data presence/hashes;
- presence, not values, of required environment variables;
- model diagnostic status if it is part of the current milestone.

## Configuration that must never drift

Generative model allowlist:

```text
gemini-3.1-flash-lite
gemini-3.5-flash-lite
```

Initial model selection:

```text
Redis distributed round-robin: 3.1 → 3.5 → 3.1 → 3.5
```

Embeddings:

```text
Primary: gemini-embedding-2
Text fallback: gemini-embedding-001
Dimensions: 768
Separate vector spaces/indexes
```

Do not introduce another model to solve a failure. Fix configuration/code or use the specified safe fallback.

## Continuation rule

- Resume the highest-priority incomplete milestone from the status document.
- Preserve verified code and migration history.
- Review partial subagent work before merging.
- Do not weaken acceptance gates.
- Run tests before and after changes.
- Fix integration inconsistencies across web/API/worker/database/model gateway/data pipeline.
- Update status/decisions and commit each coherent milestone.
- Continue into subsequent milestones while the session permits.

## Mandatory checks when touching AI/retrieval

- exact model allowlist;
- Redis round-robin integrity;
- logical-call retry semantics;
- failover only to the other allowed model;
- PHI-safe telemetry;
- separate embedding spaces/indexes;
- no cross-model vector comparisons;
- lexical and text-embedding fallback;
- citation validation and production data gating.

## End of this run

- Run the broadest practical test suite.
- Update `docs/IMPLEMENTATION_STATUS.md` with commands/results.
- Commit safe completed work.
- State whether full acceptance is satisfied.
- If incomplete, record one precise next executable task and any genuine external blocker.
