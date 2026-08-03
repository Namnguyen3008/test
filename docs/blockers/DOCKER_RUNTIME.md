# Docker Runtime Blocker

Last verified: 2026-08-03 (Asia/Saigon)

## Diagnosis

`docker`, Docker Compose, `psql`, `redis-cli`, and `helm` are not available on this Windows host.
No system software was installed and no system setting was changed.

This blocks real Compose startup, migration against an empty PostgreSQL/pgvector database,
real Redis multi-process tests, container builds/scans, persistent imports, and Helm CLI validation.
It does not block offline implementation, unit tests, static Compose checks, or Alembic SQL generation.

## User action

Run these commands from an Administrator PowerShell only when you choose to install Docker Desktop:

```powershell
winget install --exact --id Docker.DockerDesktop
```

Start Docker Desktop manually, wait for the engine to become ready, then open a new PowerShell:

```powershell
cd "D:\ALL ABOUT PROJECT\PROJECT\P-208"
docker version
docker compose version
docker compose config
docker compose up --build -d
docker compose ps
docker compose logs --no-color --tail 200 api worker web postgres redis
```

After services are healthy, run:

```powershell
docker compose exec api alembic upgrade head
docker compose exec api python -m pytest -q
docker compose exec api python -m vmec_data --help
```

Do not mark infrastructure verified until these commands succeed against the real services.
