# PostgreSQL least-privilege operations

Migration `20260803_0010_signed_lifecycle_least_privilege` creates NOLOGIN capability roles and grants/RLS. Login
identities and passwords are external infrastructure concerns and must not be committed.

Use one external login per capability: `vmec_migration_owner`, `vmec_api`, `vmec_worker`, `vmec_importer`,
`vmec_analytics`, `vmec_clinical_reporter`, `vmec_governance`, and `vmec_backup`. Never put a runtime login in the
migration-owner group. API, worker, importer, and governance must use distinct URLs.

The migration runner needs `CREATEROLE` during V7 migration. Capability roles are NOLOGIN, non-superuser,
non-creator, and non-replication. `vmec_backup` is read-only with `BYPASSRLS` solely for complete audited dumps; it
has no DML or DDL grant.

```powershell
python -m pytest tests/integration/test_postgres_least_privilege.py -q -rs
```

Supply all eight `VMEC_TEST_*_DATABASE_URL` variables through the secret manager. A skip is NOT a pass. Acceptance
requires positive application operations, negative DML/DDL attempts, RLS visibility, immutable completed releases,
and immutable governance/audit rows through the actual dedicated logins.
