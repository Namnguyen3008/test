# Signed governance promotion

This workflow never edits the immutable SQLite source catalog. A verified manifest creates a separate
`vmec-production-v1` PostgreSQL overlay whose rows are linked to their source records by append-only audit rows.

## 1. Generate the machine draft

```powershell
.\.venv\Scripts\python.exe -m scripts.governance_bridge draft `
  --catalog data\staging\vmec_catalog.sqlite3 `
  --release-id vmec-development-v2 `
  --mode development `
  --output data\governance\drafts\vmec-development-v2-governance-draft.json
```

The current draft is explicitly `vmec.governance-approval-draft.v1`. Identity, authorization, timestamps and
signature remain `null`; the draft cannot pass final validation. Its companion evidence package binds the source
archive hash, all 947 Global Source Ledger entries, exact row scope, normalized-text hashes and policy flags.

Current deterministic scope:

- 15,511 eligible rows;
- 12,345 policy GOLD candidates, including 528 safety-critical rows;
- 3,166 ordinary ACCEPTED candidates;
- 32,706 retrieval candidates excluded for missing citation/ineligibility;
- source archive SHA-256 `8ae42c51379c470c123eeef063b7c3da219311c8ca75475de24c4214d8b97b46`;
- source registry digest `996a95e678b11bed868baaa1a12a77ddad3adf02a9ff0889ea0ecddce5b1ba98`.

## 2. Complete and sign outside Git

Create a final document following `vmec.governance-approval.v1`. Supply only real reviewer IDs, organizations,
authorization references, owner authorization and timestamps. Use two distinct reviewers with
`SAFETY_CRITICAL_AND_GOLD_CANDIDATES` scope when GOLD is enabled. Set the signature envelope's key ID to the
SHA-256 fingerprint of the raw Ed25519 public key and leave `value_base64` empty before signing.

The trust-registry file has schema `vmec.governance-trust-registry.v1` and contains public keys only. Each key entry
contains `key_id`, `algorithm`, `public_key_base64`, `capabilities`, `valid_from`, optional `not_after`, optional
`revoked_at`, and optional `revocation_reason`. Use distinct `APPROVAL_MANIFEST` and `PROMOTION_RECEIPT` capabilities.

```powershell
.\.venv\Scripts\python.exe -m scripts.governance_bridge sign `
  --input <completed-unsigned-manifest.json> `
  --private-key <external-approval-private-key.txt> `
  --registry <trusted-key-registry.json> `
  --evidence data\governance\drafts\vmec-development-v2-governance-draft.evidence.json `
  --output <signed-manifest.json>
```

Private-key files contain strict Base64 for 32 raw Ed25519 private bytes. Keep them outside Git, database, logs,
container images and shared runtime volumes.

## 3. Verify without mutation

```powershell
.\.venv\Scripts\python.exe -m scripts.governance_bridge verify `
  --manifest <signed-manifest.json> `
  --registry <trusted-key-registry.json> `
  --evidence data\governance\drafts\vmec-development-v2-governance-draft.evidence.json
```

Verification rejects duplicate JSON keys, placeholders, unsupported fields, malformed timestamps, wrong capability,
expired/revoked keys, non-independent reviewers, modified scope/evidence and modified signatures.

## 4. Promote atomically

Run migrations and re-run the development persistent import first so `dataset_release_sources` and versioned GOLD
classification columns are populated. Use a dedicated promotion database role; do not expose the migration owner to
the API or worker.

```powershell
$env:VMEC_ALLOW_GOVERNANCE_PROMOTION = "true"
$env:VMEC_GOVERNANCE_MANIFEST_PATH = "<signed-manifest.json>"
$env:VMEC_GOVERNANCE_PUBLIC_KEY_PATH = "<trusted-key-registry.json>"
$env:VMEC_GOVERNANCE_EVIDENCE_PATH = "data\governance\drafts\vmec-development-v2-governance-draft.evidence.json"
$env:VMEC_GOVERNANCE_RECEIPT_SIGNING_KEY_PATH = "<external-receipt-private-key.txt>"

.\.venv\Scripts\python.exe -m scripts.governance_bridge promote `
  --database-url $env:GOVERNANCE_DATABASE_URL `
  --receipt-output data\governance\receipts\vmec-production-v1.json
```

The command takes a PostgreSQL advisory transaction lock, recomputes the full scope while source rows are locked,
creates a production overlay, records source-to-production audit rows, signs the receipt and commits once. An exact
rerun returns the stored receipt. Same-ID tampering and a different manifest for an already-bound scope are rejected.

Verify the exported receipt:

```powershell
.\.venv\Scripts\python.exe -m scripts.governance_bridge verify-receipt `
  --receipt data\governance\receipts\vmec-production-v1.json `
  --registry <trusted-key-registry.json>
```

## Rollback and recovery

Any error before commit rolls back the production release, statuses, audits and receipt together. Do not delete or
edit a committed promotion. Key revocation blocks new operations but does not silently rewrite released data.
Supersession requires a future signed supersession artifact; V6 schema v1 does not define one, so this build fails
closed instead of inventing a demotion path.
