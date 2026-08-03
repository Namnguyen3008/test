# V7 external production blockers

Observed 2026-08-03 16:37 Asia/Saigon. These are external inputs, not code failures.

- No Docker, PostgreSQL/pgvector, Redis, `psql`, `redis-cli`, Helm, or Kubernetes runtime/CLI was available; no
  listener existed on 5432 or 6379 and no persistent service URL was configured.
- No real signed final manifest, evidence/trust registry, promotion receipt, approval/receipt/lifecycle public key,
  or external private-key path was present. Reviewer/owner metadata and signatures were not invented.
- No separate role login URLs exist, so migration/grant/RLS, atomic promotion, lifecycle transitions, persistent
  imports, and backup/restore cannot be truthfully verified on PostgreSQL.
- Full embedding gates, persistent pgvector verification, and quota authorization are absent. No full backfill ran.
- Staging DNS/TLS, pinned image digests, deployment credentials, observability endpoint, backup destination, change
  window, notification provider, and named release/on-call operators are absent.

Consequently all real infrastructure, data approval/promotion, embedding, E2E, security/load/recovery,
backup/restore, staging, cutover, handover, and production-readiness gates remain false. Skips are NOT PASS.
