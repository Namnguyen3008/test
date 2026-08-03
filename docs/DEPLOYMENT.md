# Deployment guide

Local Compose is the supported integration environment. Production deployments use `infra/helm/vmec`, external managed PostgreSQL/pgvector and Redis, pre-created Kubernetes Secrets, TLS ingress, encrypted backups and an approved corpus manifest.

Before rollout, render the chart, apply migrations from a dedicated job, import the approved release, build both embedding indexes, validate model capabilities and run smoke/E2E/security gates. Use immutable image digests in production values. Never put source artifacts or runtime secrets in an image or ConfigMap.

Roll out API and worker before web, verify liveness/readiness and aggregate PHI-safe metrics, then gradually increase traffic. A failed migration, missing approved corpus, forbidden model configuration, missing index or authorization regression is a release stop. Rollback uses the previous images and embedding index metadata; database rollback requires an explicitly tested migration/restore plan.
