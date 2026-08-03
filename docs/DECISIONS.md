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
