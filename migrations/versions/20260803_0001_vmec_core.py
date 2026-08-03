"""VMEC core, governance, booking and independent embedding spaces."""

from alembic import op

revision = "20260803_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute("""
      CREATE TABLE dataset_releases (id uuid PRIMARY KEY, mode text NOT NULL CHECK (mode IN ('development','review','production')), source_hashes jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now());
      CREATE TABLE dataset_files (id bigserial PRIMARY KEY, release_id uuid REFERENCES dataset_releases(id), filename text NOT NULL, sha256 char(64) NOT NULL, size_bytes bigint NOT NULL, UNIQUE(release_id,filename));
      CREATE TABLE dataset_import_jobs (id uuid PRIMARY KEY, release_id uuid REFERENCES dataset_releases(id), status text NOT NULL, checkpoint jsonb NOT NULL DEFAULT '{}', started_at timestamptz NOT NULL DEFAULT now());
      CREATE TABLE dataset_quarantine (id bigserial PRIMARY KEY, job_id uuid REFERENCES dataset_import_jobs(id), origin_table text, row_ref text, reason_code text NOT NULL, safe_metadata jsonb NOT NULL DEFAULT '{}');
      CREATE TABLE global_sources (id text PRIMARY KEY, canonical_url text, title text, grade text, review_status text, metadata jsonb NOT NULL DEFAULT '{}');
      CREATE TABLE knowledge_records (id uuid PRIMARY KEY, release_id uuid REFERENCES dataset_releases(id), origin_table text NOT NULL, origin_row_id text NOT NULL, mode text NOT NULL, review_status text, conflict_status text, normalized_text text, content_hash char(64) NOT NULL, metadata jsonb NOT NULL DEFAULT '{}', UNIQUE(release_id,origin_table,origin_row_id));
      CREATE TABLE knowledge_record_sources (record_id uuid REFERENCES knowledge_records(id), source_id text REFERENCES global_sources(id), evidence_locator text, PRIMARY KEY(record_id,source_id));
      CREATE TABLE knowledge_chunks (id uuid PRIMARY KEY, record_id uuid REFERENCES knowledge_records(id), ordinal integer NOT NULL, normalized_text text NOT NULL, content_hash char(64) NOT NULL, token_count integer NOT NULL, UNIQUE(record_id,ordinal));
      CREATE TABLE knowledge_embeddings (chunk_id uuid REFERENCES knowledge_chunks(id), model_id text NOT NULL CHECK(model_id IN ('gemini-embedding-2','gemini-embedding-001')), dimensions integer NOT NULL CHECK(dimensions=768), embedding vector(768) NOT NULL, content_hash char(64) NOT NULL, status text NOT NULL DEFAULT 'ready', embedded_at timestamptz, PRIMARY KEY(chunk_id,model_id), UNIQUE(model_id,dimensions,content_hash));
      CREATE INDEX knowledge_embedding_2_hnsw ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops) WHERE model_id='gemini-embedding-2';
      CREATE INDEX knowledge_embedding_1_hnsw ON knowledge_embeddings USING hnsw (embedding vector_cosine_ops) WHERE model_id='gemini-embedding-001';
      CREATE INDEX knowledge_records_fts ON knowledge_records USING gin (to_tsvector('simple', coalesce(normalized_text,'')));
      CREATE INDEX knowledge_records_trgm ON knowledge_records USING gin (normalized_text gin_trgm_ops);
      CREATE TABLE embedding_jobs (id uuid PRIMARY KEY, model_id text NOT NULL, dimensions integer NOT NULL CHECK(dimensions=768), status text NOT NULL, checkpoint jsonb NOT NULL DEFAULT '{}');
      CREATE TABLE embedding_job_items (job_id uuid REFERENCES embedding_jobs(id), content_hash char(64) NOT NULL, status text NOT NULL, attempts integer NOT NULL DEFAULT 0, PRIMARY KEY(job_id,content_hash));
      CREATE TABLE users (id uuid PRIMARY KEY, role text NOT NULL CHECK(role IN ('PATIENT','STAFF','CLINICAL_REVIEWER','ADMIN')), password_hash text, active boolean NOT NULL DEFAULT true, created_at timestamptz NOT NULL DEFAULT now());
      CREATE TABLE consent_grants (id uuid PRIMARY KEY, patient_id uuid REFERENCES users(id), purpose text NOT NULL, granted_at timestamptz NOT NULL, revoked_at timestamptz);
      CREATE TABLE slots (id uuid PRIMARY KEY, practitioner_id uuid, starts_at timestamptz NOT NULL, ends_at timestamptz NOT NULL, capacity integer NOT NULL DEFAULT 1);
      CREATE TABLE appointments (id uuid PRIMARY KEY, slot_id uuid REFERENCES slots(id), patient_id uuid REFERENCES users(id), status text NOT NULL, patient_confirmed_at timestamptz, staff_approved_at timestamptz, hold_expires_at timestamptz, version integer NOT NULL DEFAULT 1);
      CREATE UNIQUE INDEX one_active_appointment_per_slot ON appointments(slot_id) WHERE status IN ('HELD','PATIENT_CONFIRMED','PENDING_STAFF_APPROVAL','CONFIRMED','RESCHEDULE_PROPOSED');
      CREATE TABLE appointment_events (id bigserial PRIMARY KEY, appointment_id uuid REFERENCES appointments(id), actor_id uuid, action text NOT NULL, from_status text, to_status text NOT NULL, occurred_at timestamptz NOT NULL DEFAULT now(), safe_metadata jsonb NOT NULL DEFAULT '{}');
      CREATE TABLE idempotency_keys (actor_id uuid, operation text, key text, response_hash char(64), created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY(actor_id,operation,key));
      CREATE TABLE audit_events (id bigserial PRIMARY KEY, actor_id uuid, action text NOT NULL, target_type text NOT NULL, target_id text NOT NULL, outcome text NOT NULL, trace_id text, occurred_at timestamptz NOT NULL DEFAULT now(), safe_metadata jsonb NOT NULL DEFAULT '{}');
    """)


def downgrade() -> None:
    for table in (
        "audit_events",
        "idempotency_keys",
        "appointment_events",
        "appointments",
        "slots",
        "consent_grants",
        "users",
        "embedding_job_items",
        "embedding_jobs",
        "knowledge_embeddings",
        "knowledge_chunks",
        "knowledge_record_sources",
        "knowledge_records",
        "global_sources",
        "dataset_quarantine",
        "dataset_import_jobs",
        "dataset_files",
        "dataset_releases",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
