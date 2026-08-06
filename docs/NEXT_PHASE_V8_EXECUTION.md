# VMEC V8 external-stack execution ledger

Last updated: 2026-08-03 Asia/Saigon. This is append-only evidence; no skipped item is a pass.

## V8 intake and baseline

- Original V8 archive remains unchanged at SHA-256
  `cb4715bb0d97166eca1123676c61a62ed939bd46e49ab677e11f7343ec3183cd`.
- Guarded extraction validated 14 entries, including traversal/rooted-path/ADS/reparse/symlink/duplicate/file-directory
  collision/containment checks, and placed them under ignored `.codex/plans/VMEC_Codex_Next_Phase_Pack_v8/`.
- Pack manifest payload hashes and all listed V7 basis-document hashes match the repository at V8 intake.

## V8-1 toolchain result

- Winget is available. User-scope official packages were installed with the Winget-declared installer SHA-256 verified:
  `kubectl v1.36.3`, `Helm v4.2.3`, `kind v0.32.0`, and `age v1.3.1`.
- Docker Desktop `4.84.0` and Docker CLI `29.6.2` already exist. Its CLI path was added to the user PATH, but a
  bounded daemon health probe timed out. Docker Engine is therefore **NOT VERIFIED**.
- WSL executable/version exists, but Windows reports that the WSL and Virtual Machine Platform optional components are
  disabled. The one required elevated/reboot action is [V8_WSL_ADMIN_ACTION.md](blockers/V8_WSL_ADMIN_ACTION.md).
  Codex did not bypass UAC, change BIOS/UEFI, or reboot.
- Helm lint and template render pass offline. kind cannot list/create a cluster until Docker Engine is healthy; no
  Kubernetes cluster is claimed.

## V8-2 local secret and recovery preparation

- `.secrets/v8/` is ignored and ACL-restricted to the current Windows user. It contains generated local-only
  PostgreSQL credential URLs, four separate Ed25519 private keys, an unsigned trust-registry template, an unsigned
  embedding-authorization draft, age identity/recipient material, and local backup directory. No value is committed
  or printed.
- `scripts/provision_local_postgres_roles.py` provisions eight LOGIN members only after migration creates the V7
  capability groups. `docker-compose.yml` now requires the ignored runtime env file, runs the provisioner after
  migrations, and starts API/worker/scheduler only after it succeeds.
- `scripts/local_encrypted_backup.py` is prepared for Docker-based `pg_dump` -> age encryption and clean-target
  restore. It uses the dedicated read-only backup login, a separate restore login, `--no-owner --no-acl`, and a
  mandatory SHA-256 sidecar check before decryption. It cannot be executed until PostgreSQL is running.
- The generated age recipient/identity completed a non-sensitive in-memory encryption/decryption preflight. This
  verifies local encryption plumbing only; it is not a database backup/restore result.

## V8-2 continuation hardening

- Dedicated-role provisioning parses URLs with SQLAlchemy rather than manually splitting credentials. The backup
  helper uses `vmec_v8_backup` for the read-only dump, a separately declared restore login for the disposable target,
  portable `--no-owner --no-acl` dumps, and SHA-256 sidecar verification before decryption.
- Offline continuation verification: Ruff/mypy and five focused tests pass; full Python regression is `187 passed,
  16 skipped, 1 warning`. Compose config plus Helm lint/template also pass offline. Skips and Docker-dependent work
  remain not run, never PASS.

## Pending exact execution after the one administrator action

```powershell
# After completing docs/blockers/V8_WSL_ADMIN_ACTION.md and reopening PowerShell:
docker version
docker compose --env-file .secrets/v8/runtime.env config --quiet
docker compose --env-file .secrets/v8/runtime.env up -d postgres redis
docker compose --env-file .secrets/v8/runtime.env run --rm migrate
docker compose --env-file .secrets/v8/runtime.env up -d provision-roles api worker scheduler web
```

Then run dedicated login tests, persistent imports, governance verification/promotion only with real authorization,
embedding smoke/full only with valid authorization, encrypted backup/restore, kind/Helm staging, and all remaining
real-stack gates in that order.

## Current V8 flags

```text
TOOLCHAIN_READY=false
DOCKER_COMPOSE_VERIFIED=false
KUBERNETES_HELM_VERIFIED=false
CODE_COMPLETE=true
INFRA_VERIFIED=false
PERSISTENT_IMPORT_COMPLETE=false
GOVERNANCE_MANIFEST_VERIFIED=false
DATA_PROMOTION_COMPLETE=false
SUPERSESSION_REVOCATION_COMPLETE=false
DATABASE_LEAST_PRIVILEGE_VERIFIED=false
EMBEDDING_AUTHORIZATION_VERIFIED=false
EMBEDDING_SMOKE_COMPLETE=false
EMBEDDING_BACKFILL_COMPLETE=false
REAL_STACK_E2E_COMPLETE=false
SECURITY_LOAD_RESILIENCE_COMPLETE=false
BACKUP_RESTORE_VERIFIED=false
DATA_APPROVED=false
STAGING_VERIFIED=false
PRODUCTION_CUTOVER_COMPLETE=false
OPERATIONS_HANDOVER_COMPLETE=false
PRODUCTION_READY=false
```
