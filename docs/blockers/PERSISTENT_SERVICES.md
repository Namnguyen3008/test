# Persistent Services Blocker

Status: external blocker verified 2026-08-03.

`psql`, `redis-cli` and configured persistent service URLs are unavailable in the current environment. SQLite/in-memory adapters prove offline behavior but do not verify PostgreSQL row-lock semantics or Redis behavior across real processes.

After Docker or managed services are available:

```powershell
docker compose up -d postgres redis
.\.venv\Scripts\alembic.exe upgrade head
.\.venv\Scripts\python.exe -m pytest tests/test_booking_persistence.py tests/test_security -q
celery -A apps.worker.__main__:app worker --loglevel=INFO
celery -A apps.worker.__main__:app beat --loglevel=INFO
```

Run the PostgreSQL concurrency test against the persistent URL and verify Redis session revocation, rate limiting and Gemini round robin from at least two API processes. Do not mark `INFRA_VERIFIED=true` until these pass.

## V4 update — 2026-08-03

CI now defines a `pgvector/pgvector:pg16` service, applies the full Alembic chain and runs `tests/integration/test_postgres_embedding_backfill.py`. That CI job is code prepared in commit `3557152`; it has not run in this local session and is not counted as PASS. When persistent services become available locally, run:

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m pytest tests\integration\test_postgres_embedding_backfill.py tests\test_booking_persistence.py tests\test_security -q
```

The first integration test requires `VMEC_TEST_POSTGRES_URL` pointing to an isolated migrated database. Real Redis multi-process and PostgreSQL booking-race evidence are still required.

After `5b4a8c0`, that PostgreSQL CI test also imports a synthetic read-only catalog twice and asserts stable record/chunk counts before exercising both model spaces. The required migration head is `20260803_0008_persistent_import`; the CI definition still has not been executed locally.

## V5 update — 2026-08-03 14:15 Asia/Saigon

Commit `fb4652f` adds a Redis service to the persistent CI job and environment-gated real-service contracts for extensions/head, cross-client session persistence/revocation, global Redis Gemini rotation and a true PostgreSQL booking contention race. Locally these five integration cases remain explicitly skipped because no service URL exists; they are not PASS evidence. Compose now publishes PostgreSQL/Redis only on loopback and applies migrations before starting runtime processes.

Exact local runtime command:

```powershell
docker compose up -d
docker compose exec -e VMEC_TEST_POSTGRES_URL=postgresql+psycopg://vmec:vmec@postgres:5432/vmec -e VMEC_TEST_REDIS_URL=redis://redis:6379/14 api python -m pytest tests/integration -q -rs
```
