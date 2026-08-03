# VMEC V7 final production execution ledger

Last updated: 2026-08-03 16:37 Asia/Saigon. This ledger is append-only.

## Completed locally

- V7 ZIP extracted through entry-by-entry traversal/rooted-path/symlink/ADS/duplicate/containment checks. Original
  SHA-256 remained `746d2cd302d44fe6ed449319ec2a38ea4f80afa2bacadcde2a1bf7ba5f0dda1d`.
- V6 governance regression stayed green and was not rebuilt.
- Commit `6756667` adds domain-separated signed supersession/revocation, capability keys, active generation route,
  immutable lifecycle artifacts/transitions, replay/staleness/tamper guards, candidate release promotion, fail-closed
  route-aware retrieval/readiness, immutable completed imports, and CLI verify/apply commands.
- Migration `20260803_0010_signed_lifecycle_least_privilege` adds eight NOLOGIN capability roles, explicit grants,
  RLS, safe reporting views, immutable completed release/content triggers, and lifecycle persistence.
- Compose and Helm require separate migration/API/worker/governance database secret contracts.
- The ignored review draft was deterministically regenerated: 528 eligible rows, SHA-256
  `82678883780c91697f704b4155ea10ed12ddd48160feF4eaa3b4e09ad8df7d0a` (case-insensitive digest).

## Real execution order

1. Provision PostgreSQL/pgvector and Redis and external logins mapped one-to-one to the V7 group roles.
2. Apply migrations to an empty database as migrator and run all dedicated-login negative tests.
3. Import development/review persistently as importer and prove identical replay is a no-op.
4. Supply and verify the real final manifest/evidence/trust registry and receipt key; promote as governance.
5. Verify receipt and exact active-route/file/DB digest binding. Run signed lifecycle tamper/replay and emergency
   revocation drills on staging with authorized test artifacts.
6. Run bounded embedding smoke for both exact 768d spaces. Run full backfill only with both explicit gates/quota.
7. Execute real-stack auth, RBAC, booking races, worker/outbox, emergency-first grounded agent, browser E2E, load,
   outage/recovery, backup/restore, observability, and secret/dependency/container scans.
8. Deploy pinned digests to staging, complete operations handover, then execute the approved cutover window.

Exact lifecycle, least-privilege, backup, cutover, and handover procedures are in `docs/runbooks/`.
