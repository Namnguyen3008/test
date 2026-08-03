# Clinical review operations

Status: workflow code is available; no real reviewer approval has been performed in this environment.

## Identity and separation of duties

- Provision `CLINICAL_REVIEWER` accounts only through an authenticated admin session after the operator has verified the reviewer's clinical authorization and organization identity outside VMEC.
- Require MFA at the identity-provider boundary and record the authorization ticket outside patient-facing data. VMEC's local password endpoint is not evidence of clinical qualification.
- Do not share reviewer accounts. Deactivate access immediately when authorization expires.
- A safety-critical item requires two distinct reviewer user IDs. Neither Gemini nor an admin service account may stand in for a reviewer.
- A promotion report is evidence for a later governance decision; it never changes `DATA_APPROVED` and always reports `production_approved=false`.

## Queue operation

The workflow queue orders second-review/adjudication items first, then other safety-critical items, then the remaining queue. A reviewer must claim an item before deciding it. Claims expire; optimistic versions prevent a stale browser from overwriting another reviewer's work.

For every decision, compare the content hash, canonical source identifiers and displayed evidence with the source ledger. Use `REQUEST_CHANGES` when the evidence is incomplete. Supply a substantive rationale without patient identifiers, prompts, credentials or copied private notes.

Package import is admin-only, CSRF-protected and atomic. Replaying an origin with a different record ID, content hash, evidence, source list or safety classification fails the whole package. This prevents a partially imported governance batch from looking complete.

## Evidence export

The release export contains no evidence text and replaces each rationale with a SHA-256 hash. It includes `schema_version=vmec.review-evidence.v1` and a deterministic `package_digest`. Recompute the digest after removing `package_digest`, using sorted JSON keys and separators `(',', ':')`; reject the artifact if it differs.

The export is an integrity/audit artifact, not an approval manifest. Store it in an access-controlled governance system with reviewer identity evidence and retention controls. Do not commit exports from real reviews to Git.

## Promotion gate

Before a human governance owner can prepare an approval artifact, verify all of the following outside synthetic tests:

1. The complete expected release scope was imported, not merely a subset.
2. Every item maps to the immutable release, content hash and canonical source ledger.
3. Safety-critical items have two independent approvals.
4. Rejections and requested changes have been resolved through a new immutable source release.
5. The evidence export digest and reviewer authorization records reconcile.
6. The authorized promotion mechanism verifies its own signature and policy.

The current application deliberately has no endpoint that converts review decisions into `ACCEPTED`, `GOLD` or production approval. Until the signed governance bridge and a real review are complete, keep `DATA_APPROVED=false` and production import fail-closed.
