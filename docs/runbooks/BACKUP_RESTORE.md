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

## V8 local encrypted rehearsal

When Docker Engine and PostgreSQL are healthy, V8 uses the ignored age recipient and identity under `.secrets/v8/`.
The helper keeps the raw custom dump in a temporary private directory, encrypts it before preserving it, records only
the archive digest, and restores into an explicitly named clean database.

```powershell
python -m scripts.local_encrypted_backup backup `
  --backup-directory .secrets/v8/backups `
  --recipient .secrets/v8/backup.recipient.txt `
  --backup-database-user vmec_v8_backup

python -m scripts.local_encrypted_backup restore `
  --archive ".secrets/v8/backups/<archive>.dump.age" `
  --identity .secrets/v8/backup.agekey `
  --restore-database-user vmec `
  --restore-database vmec_restore_v8
```

The restore helper verifies the archive SHA-256 sidecar before decryption. `vmec_v8_backup` is a read-only dedicated
login; the separately supplied restore login is used only to create and populate the disposable restore database.
This is prepared, not executed: encryption setup or an archive alone is not restore-drill evidence.

## Compose drill sequence

The following sequence is prepared but was not run in the V5 Mode C environment. Use only a disposable restore database and an encrypted backup destination outside this repository.

```powershell
docker compose up -d postgres redis
docker compose exec postgres pg_isready -U vmec -d vmec
docker compose exec api alembic current
docker compose exec postgres pg_dump --format=custom --compress=9 --no-owner --no-acl --file /tmp/vmec.dump vmec
docker compose cp postgres:/tmp/vmec.dump "<secure-backup-path>\vmec.dump"
Get-FileHash -Algorithm SHA256 -LiteralPath "<secure-backup-path>\vmec.dump"
docker compose exec postgres createdb -U vmec vmec_restore_drill
docker compose cp "<secure-backup-path>\vmec.dump" postgres:/tmp/vmec-restore.dump
docker compose exec postgres pg_restore --exit-on-error --no-owner --no-acl -U vmec --dbname vmec_restore_drill /tmp/vmec-restore.dump
```

Point an isolated validation process at `vmec_restore_drill`; do not change the running API database in place. Capture pre-backup and post-restore aggregate counts for releases, records, chunks, source joins, both vector spaces, users, appointments/events, outbox/reminders and audit events. Require exact reconciliation, migration head `20260803_0010_signed_lifecycle_least_privilege`, zero broken citation links, successful auth/session/booking/retrieval smoke and PHI-safe logs. Also reconcile active route state/generation, manifest and receipt digests, lifecycle artifact/transition counts, and exercise the read-only backup identity with a separate restore operator. Only then may `BACKUP_RESTORE_VERIFIED=true` be considered.
