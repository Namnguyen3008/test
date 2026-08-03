# V6 external runtime and approval blockers

Observed 2026-08-03 Asia/Saigon. This file records `NOT_RUN`/blocked work; it is not PASS evidence.

- PostgreSQL, Redis, Docker, Helm and Kubernetes runtimes are unavailable locally. No listeners exist on 5432/6379.
- `VMEC_TEST_POSTGRES_URL` and `VMEC_TEST_REDIS_URL` are absent. PostgreSQL governance integration tests are skipped
  locally; CI is configured to run them after `alembic upgrade head`.
- No completed final manifest, real reviewer/owner metadata, authorization references, trusted public-key registry,
  approval signature or receipt-signing private key is present.
- Governance promotion and production overlay therefore remain unexecuted.
- Full embedding backfill remains disabled because `VMEC_ALLOW_FULL_EMBEDDING_BACKFILL=true` and verified persistent
  pgvector are both absent. No live provider backfill was started.
- Backup/restore, real-stack E2E, Helm rendering and staging verification cannot run without their external runtimes.
- The V6 manifest schema has no signed revocation/supersession artifact. The implementation blocks a second
  production scope rather than inventing an unsigned rollback or bypass.
- Runtime database least-privilege separation has not been verified on real PostgreSQL. Until it is, append-only
  triggers are DB-enforced against normal DML, not proof against a table-owner credential.

Commands to run when infrastructure and real signed artifacts exist:

```powershell
docker compose up -d postgres redis
docker compose run --rm migrate
.\.venv\Scripts\python.exe -m pytest tests\integration -q
.\.venv\Scripts\python.exe -m scripts.import_catalog_to_postgres --data-mode development --logical-release-id vmec-development-v2
# Follow docs/runbooks/GOVERNANCE_PROMOTION.md, then prepare embedding jobs for vmec-production-v1.
docker compose config
helm lint infra\helm\vmec
```
