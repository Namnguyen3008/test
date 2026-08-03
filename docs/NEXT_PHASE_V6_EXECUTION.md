# V6 execution ledger

## 2026-08-03 15:42 Asia/Saigon

### Pack and repository

- Repository: `D:\ALL ABOUT PROJECT\PROJECT\P-208`, branch `codex/vmec-production-implementation`.
- Source pack: `SOURCE_DATASET\VMEC_Codex_Next_Phase_Pack_v6(2).zip`.
- Safe extraction: 10 entries validated against rooted paths, traversal, ADS, symlink/reparse entries, unsupported
  Unix types, duplicate case-insensitive destinations, file/directory collisions and repository containment.
- ZIP SHA-256 remained `6A57C5629021A8CB01EB3CFFCCC1B404E0693773519F5EA3100E5D0F1267C413` before/after.
- All pack files and required repository documents were read in README order.

### Implemented

- Milestone commit: `945ba1b` (`feat(governance): add signed promotion bridge`).
- Strict final-manifest models with unknown-field, placeholder, timestamp, reviewer-independence and GOLD reviewer
  checks.
- Narrow VMEC canonical JSON profile, duplicate-key rejection, Unicode NFC normalization, domain-separated Ed25519
  approval/receipt signatures and key fingerprints.
- External public trust registry with capabilities, validity windows, rotation entries and fail-closed revocation.
- Read-only deterministic draft/evidence generation from the immutable development release.
- Evidence binding for source archive hash, full Global Source Ledger digest, normalized-text hashes, source IDs,
  classification flags, included table/row scope and aggregate counts.
- Versioned GOLD classifier persisted into PostgreSQL: safety-critical and explicit source gold-candidate metadata;
  ordinary rows remain ACCEPTED.
- Migration `20260803_0009_governance_bridge`: ledger-to-release mapping, typed policy fields, immutable manifest
  transition, append-only promotion receipt/per-row audit tables.
- CLI-only `draft`, `sign`, `verify`, `promote` and `verify-receipt`; no HTTP promotion/bypass endpoint.
- Promotion uses a PostgreSQL advisory transaction lock and creates a separate `vmec-production-v1` overlay,
  preserving the source release. It signs a receipt inside the transaction and returns the stored receipt on exact
  replay. Same-ID tampering and a second manifest for the same scope fail closed.
- PostgreSQL hybrid retrieval/backfill resolves logical release IDs, allowing the governed overlay to be selected.
- Optional, explicit Compose profile and Helm Job contract for promotion; governance private material is not injected
  into API/web/worker pods.

### Machine draft

Ignored artifacts:

- `data/governance/drafts/vmec-development-v2-governance-draft.json`
- `data/governance/drafts/vmec-development-v2-governance-draft.evidence.json`

Aggregate facts: 447,525 source rows; 48,217 retrieval candidates; 15,511 eligible; 12,345 GOLD candidates;
3,166 ordinary ACCEPTED candidates; 528 safety-critical; 32,706 missing-source/ineligible; 947 canonical sources.
Two consecutive generations produced identical draft SHA-256
`B25234B91461441179C22BEC6712DA8EA6EF533888E4695CED3246FAF9A1BBE0`; scope/evidence digests are deterministic.
No source row was modified.

### External gates

The user's statement that experts approved data is recorded as context, not cryptographic evidence. The following
remain absent: final manifest ID; real reviewer IDs/organizations/authorization references/review times; owner ID,
authorization reference/time; issued/expiry time; approval key ID/signature; trusted registry; receipt signing key;
PostgreSQL/Redis runtime. Consequently no row was promoted and no clinical approval was invented.

The V6 v1 schema does not define a signed revocation/supersession artifact. The implementation supports trust-key
revocation and rejects a second production scope, but does not invent an unsigned demotion or bypass.

```text
CODE_COMPLETE=false
INFRA_VERIFIED=false
PERSISTENT_IMPORT_COMPLETE=false
GOVERNANCE_BRIDGE_COMPLETE=true
GOVERNANCE_MANIFEST_VERIFIED=false
DATA_PROMOTION_COMPLETE=false
EMBEDDING_SMOKE_COMPLETE=false
EMBEDDING_BACKFILL_COMPLETE=false
REAL_STACK_E2E_COMPLETE=false
BACKUP_RESTORE_VERIFIED=false
DATA_APPROVED=false
STAGING_VERIFIED=false
PRODUCTION_READY=false
```
