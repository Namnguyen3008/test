# Signed production release lifecycle

This runbook applies only to real, externally authorized artifacts. Never create reviewer identities,
authorization references, signing keys, or signatures on behalf of an approver.

## Verify before mutation

The trust registry must give a dedicated Ed25519 key exactly one of `GOVERNANCE_SUPERSESSION` or
`GOVERNANCE_REVOCATION`. Approval-manifest and receipt keys cannot authorize a lifecycle change. Keep registry,
artifact, and private key material outside the repository.

```powershell
python -m scripts.governance_bridge verify-lifecycle `
  --artifact "<signed-lifecycle-artifact.json>" `
  --registry "<trust-registry.json>"
```

Verification binds the route, expected generation, old release/manifest/receipt digests, times, owner authorization,
and, for a clinical-scope change, two independent clinical attestations.

## Apply atomically

Use a login that is only a member of `vmec_governance`; never use the database owner or API credential.

```powershell
$env:GOVERNANCE_DATABASE_URL = "<loaded-by-secret-manager>"
python -m scripts.governance_bridge apply-lifecycle `
  --artifact "<signed-lifecycle-artifact.json>" `
  --registry "<trust-registry.json>"
```

The transaction locks the route generation, rebinds stored promotion digests, writes immutable artifact/transition
rows, and switches the route. Exact replay is idempotent; tamper, duplicate bytes under another ID, stale generation,
incomplete replacement, and mismatched bindings fail closed.

Supersession routes to a separately promoted immutable candidate. Revocation clears the active pointer and makes
production retrieval/readiness fail closed while preserving history. Restoration requires a new approved release
and signed supersession; never update the pointer by hand.

Record only identifiers, digests, state, generation, counts, operator, UTC time, and change ticket. Never record
private keys, PHI, prompts, or connection URLs.
