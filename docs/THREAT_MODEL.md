# VMEC-01 Threat Model

## Assets and trust boundaries

Sensitive assets include patient identity, symptoms and notes, sessions, consent, audit events, appointment state, source datasets, encryption keys, and Gemini credentials. Browser, API, worker, PostgreSQL, Redis, Gemini, and object storage are separate trust boundaries.

## Principal threats and controls

- Credential disclosure: secrets remain server-side, are redacted from logs, and are never included in browser bundles or diagnostics.
- PHI leakage: structured allowlisted telemetry, encrypted free text, minimum-necessary access, retention controls, and export sanitization.
- Broken authorization: deny-by-default RBAC, server-side ownership checks, CSRF, secure sessions, and endpoint matrix tests.
- Prompt/indirect injection: untrusted corpus is data, not instructions; tool proposals and all IDs are schema- and database-validated.
- Unsafe clinical output: deterministic emergency gate first, non-diagnostic policy, citation validation, disclaimer, confidence threshold, and handoff.
- Booking races/replays: database transactions, row locks, partial uniqueness, TTL holds, idempotency keys, and append-only transitions.
- Model substitution/outage: exact allowlists, Redis rotation, bounded failover only to the peer model, per-model circuit breakers, deterministic handoff.
- Vector-space confusion: model ID/dimension constraints and model-specific indexes/query APIs.
- Supply chain/deployment: pinned lockfiles, CI scans, non-root containers, read-only filesystem where practical, network policy and secret references.

Clinical, legal, privacy, and security approval remain organizational gates; passing tests does not constitute certification.

