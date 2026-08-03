"""Persistent dual-embedding backfill integrity constraints.

Revision ID: 20260803_0007_embedding_backfill
Revises: 20260803_0006_clinical_review
"""

from alembic import op

revision = "20260803_0007_embedding_backfill"
down_revision = "20260803_0006_clinical_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_records ADD COLUMN canonical_status text NOT NULL DEFAULT 'REVIEW_REQUIRED'")
    op.execute(
        "CREATE INDEX knowledge_records_approval_filter "
        "ON knowledge_records(release_id,mode,canonical_status,review_status,conflict_status)"
    )
    # Identical text may belong to several grounded records. Provider calls are
    # deduplicated by job/content hash, while every chunk still receives a row.
    op.execute(
        "ALTER TABLE knowledge_embeddings "
        "DROP CONSTRAINT IF EXISTS knowledge_embeddings_model_id_dimensions_content_hash_key"
    )
    op.execute(
        "CREATE INDEX knowledge_embeddings_content_cache ON knowledge_embeddings(model_id,dimensions,content_hash)"
    )
    op.execute(
        "ALTER TABLE embedding_jobs ADD CONSTRAINT embedding_jobs_exact_model "
        "CHECK(model_id IN ('gemini-embedding-2','gemini-embedding-001'))"
    )
    op.execute(
        "ALTER TABLE embedding_job_items ADD CONSTRAINT embedding_job_items_status "
        "CHECK(status IN ('pending','processing','failed','complete','quarantined'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE embedding_job_items DROP CONSTRAINT IF EXISTS embedding_job_items_status")
    op.execute("ALTER TABLE embedding_jobs DROP CONSTRAINT IF EXISTS embedding_jobs_exact_model")
    op.execute("DROP INDEX IF EXISTS knowledge_embeddings_content_cache")
    op.execute("DROP INDEX IF EXISTS knowledge_records_approval_filter")
    op.execute("ALTER TABLE knowledge_records DROP COLUMN IF EXISTS canonical_status")
    op.execute(
        "ALTER TABLE knowledge_embeddings ADD CONSTRAINT "
        "knowledge_embeddings_model_id_dimensions_content_hash_key "
        "UNIQUE(model_id,dimensions,content_hash)"
    )
