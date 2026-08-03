"""PostgreSQL lexical and dual-pgvector retrieval runtime support.

Revision ID: 20260803_0005_retrieval_runtime
Revises: 20260803_0004_worker_delivery
"""

from alembic import op

revision = "20260803_0005_retrieval_runtime"
down_revision = "20260803_0004_worker_delivery"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE knowledge_chunks ADD COLUMN search_vector tsvector "
        "GENERATED ALWAYS AS (to_tsvector('simple', coalesce(normalized_text,''))) STORED"
    )
    op.execute("CREATE INDEX knowledge_chunks_fts ON knowledge_chunks USING gin(search_vector)")
    op.execute("CREATE INDEX knowledge_chunks_trgm ON knowledge_chunks USING gin(normalized_text gin_trgm_ops)")
    op.execute(
        "CREATE INDEX knowledge_records_runtime_filter ON knowledge_records "
        "(release_id,mode,origin_table,review_status,conflict_status)"
    )
    op.execute("CREATE INDEX knowledge_record_sources_source_id ON knowledge_record_sources(source_id,record_id)")
    op.execute("ALTER TABLE embedding_jobs ADD COLUMN created_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE embedding_jobs ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE embedding_job_items ADD COLUMN available_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE embedding_job_items ADD COLUMN last_attempt_at timestamptz")
    op.execute("ALTER TABLE embedding_job_items ADD COLUMN error_code varchar(100)")
    op.execute(
        "CREATE INDEX embedding_job_items_pending ON embedding_job_items(job_id,available_at,content_hash) "
        "WHERE status IN ('pending','failed')"
    )
    op.execute("""
        CREATE TABLE embedding_quarantine (
            id bigserial PRIMARY KEY,
            job_id uuid NOT NULL REFERENCES embedding_jobs(id),
            model_id text NOT NULL CHECK(model_id IN ('gemini-embedding-2','gemini-embedding-001')),
            content_hash char(64) NOT NULL,
            reason_code varchar(100) NOT NULL,
            safe_metadata jsonb NOT NULL DEFAULT '{}',
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(job_id,model_id,content_hash)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embedding_quarantine")
    op.execute("DROP INDEX IF EXISTS embedding_job_items_pending")
    op.execute("ALTER TABLE embedding_job_items DROP COLUMN IF EXISTS error_code")
    op.execute("ALTER TABLE embedding_job_items DROP COLUMN IF EXISTS last_attempt_at")
    op.execute("ALTER TABLE embedding_job_items DROP COLUMN IF EXISTS available_at")
    op.execute("ALTER TABLE embedding_jobs DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE embedding_jobs DROP COLUMN IF EXISTS created_at")
    op.execute("DROP INDEX IF EXISTS knowledge_record_sources_source_id")
    op.execute("DROP INDEX IF EXISTS knowledge_records_runtime_filter")
    op.execute("DROP INDEX IF EXISTS knowledge_chunks_trgm")
    op.execute("DROP INDEX IF EXISTS knowledge_chunks_fts")
    op.execute("ALTER TABLE knowledge_chunks DROP COLUMN IF EXISTS search_vector")
