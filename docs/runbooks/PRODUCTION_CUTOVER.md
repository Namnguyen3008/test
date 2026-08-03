# Staging and production cutover

Status: prepared, not executed in the V7 workstation environment.

Cutover is forbidden until the final signed manifest/evidence/trust registry/receipt, active DB binding,
PostgreSQL/Redis health, role tests, both production vector spaces, full regression, security/load/recovery evidence,
restore drill, pinned image digests, TLS/DNS, observability, change window, and named operators all pass.

Deploy exact staging image digests. Apply migrations as migrator, import as importer, promote as governance, and run
API/worker using their own identities. `/ready` must bind the signed manifest digest to the active DB manifest; a
revoked route must return 503.

Canary in bounded steps while monitoring emergency handoff, 5xx/latency, DB pool, Redis, booking conflict, outbox,
model failover, retrieval degradation, citation rejection, and PHI-safe logs. Stop on any safety, authorization,
integrity, secret, or rollback-threshold breach.

Application rollback uses the last verified image digest. Never point governed data back manually. Data rollback
requires signed supersession; emergency withdrawal requires signed revocation. Preserve all receipts and transitions.
