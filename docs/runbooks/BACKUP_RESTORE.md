# PostgreSQL backup and restore

Status: procedure prepared; no restore has been executed in the current environment because PostgreSQL tools are absent.

## Backup boundary

PostgreSQL is the source of truth. Redis contains revocable sessions, counters and transient broker state and is rebuilt rather than restored into a new environment. Keep database credentials in a protected service file or secret manager; never place a connection URL in command history, logs or this repository.

Before backup, record the UTC timestamp, `alembic current`, application commit, dataset release IDs and a destination retention classification. Write only to an encrypted, access-controlled destination outside the repository.

```powershell
alembic current
pg_dump --format=custom --compress=9 --no-owner --no-acl --file "<secure-backup-path>\vmec.dump" "<database-name>"
Get-FileHash -Algorithm SHA256 -LiteralPath "<secure-backup-path>\vmec.dump"
```

Store the digest and metadata separately from the dump. Do not print row contents, prompts, rationales, appointment data or environment variables.

## Isolated restore drill

Use a disposable database that cannot receive production traffic. Never use `--clean` against the source database.

```powershell
createdb "<isolated-restore-database>"
pg_restore --exit-on-error --no-owner --no-acl --dbname "<isolated-restore-database>" "<secure-backup-path>\vmec.dump"
```

Point a dedicated validation process at the restored database, then run:

```powershell
alembic current
alembic upgrade head
python -m pytest tests/integration/test_postgres_embedding_backfill.py -q
```

Verify aggregate counts only:

```sql
SELECT model_id, dimensions, status, count(*)
FROM knowledge_embeddings
GROUP BY model_id, dimensions, status
ORDER BY model_id, dimensions, status;

SELECT count(*) AS missing_canonical_sources
FROM knowledge_record_sources krs
LEFT JOIN global_sources gs ON gs.id = krs.source_id
WHERE gs.id IS NULL;

SELECT status, count(*) FROM appointments GROUP BY status ORDER BY status;
SELECT count(*) FROM appointment_events;
SELECT count(*) FROM audit_events;
```

Acceptance requires: expected migration head, zero broken citation references, only the two exact 768-dimensional model spaces, expected aggregate row counts, successful API health/grounded retrieval smoke and no secret/PHI in logs. Record commands, hashes and aggregate results in `docs/TEST_EVIDENCE.md`.

Destroy the isolated database only after evidence is captured and the target name is independently checked:

```powershell
dropdb "<isolated-restore-database>"
```

Until a complete drill succeeds, keep `INFRA_VERIFIED=false` and `PRODUCTION_READY=false`.
