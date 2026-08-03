# VMEC-01 Implementation Status

Last updated: 2026-08-03 (Asia/Saigon)

## Current state

- Branch: `codex/vmec-production-implementation`
- Pre-implementation checkpoint: `bee1e30`
- Pack checksum verification: all declared files passed.
- Immutable source artifacts: all four copied to `data/source/`; local SHA-256 manifest generated and ignored.
- Baseline verification: `python -m pytest -q` -> 14 passed, 1 skipped; `python -m ruff check src tests` -> passed.
- External diagnostics: blocked because `GEMINI_API_KEY` is absent from this PowerShell process. No key value was printed.
- Container verification: blocked because Docker CLI/runtime is not installed or not on PATH.

## Milestones

| Milestone | State | Evidence / next work |
|---|---|---|
| M0 Architecture/audit | In progress | Pack/spec read; repository and archive inventories completed. |
| M1 Monorepo/platform | Not started | Existing project is a small FastAPI template only. |
| M2 Data importer | Not started | Development archive: 105 entries; research archive: 107 entries. |
| M3 Dual retrieval | Not started | No pgvector schema/indexes yet. |
| M4 Identity/RBAC/privacy | Not started | No application auth/session domain yet. |
| M5 Booking | Not started | No transactional booking domain yet. |
| M6 Gemini gateway | Partial | Existing gateway has process-local rotation and quota-only failover; must be replaced with Redis-backed policy. |
| M7 Safety/grounding graph | Not started | Existing two-node sample graph is not emergency-first. |
| M8 Patient web | Not started | No frontend exists. |
| M9 Operations web | Not started | No frontend exists. |
| M10 Workers/analytics | Not started | No worker exists. |
| M11 Security/deployment | Partial | Basic Dockerfile/CI only; no Redis/Postgres/web/worker/Helm. |
| M12 Verification | Not started | Baseline only. |
| M13 Delivery | Not started | Feature branch created. |

## External blockers

1. Live Gemini model visibility and API calls require `GEMINI_API_KEY` to be supplied to the execution environment.
2. Docker build/Compose/startup cannot be exercised until Docker is installed and its daemon is available.

These blockers do not prevent offline implementation and deterministic tests.

