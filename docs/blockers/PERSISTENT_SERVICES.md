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
