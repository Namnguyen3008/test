# Backup and restore

Take encrypted PostgreSQL logical backups with `pg_dump --format=custom`, record the migration revision and artifact manifest hash, and keep Redis out of the clinical source of truth. Test restores into an isolated database with `pg_restore --clean --if-exists`, run `alembic current`, validate appointment/event counts and citation foreign keys, then destroy the test copy under the retention policy. Never place backups in Git or container images.
