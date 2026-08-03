"""Persistent catalog import checkpoints and logical release identity.

Revision ID: 20260803_0008_persistent_import
Revises: 20260803_0007_embedding_backfill
"""

from alembic import op

revision = "20260803_0008_persistent_import"
down_revision = "20260803_0007_embedding_backfill"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE dataset_releases ADD COLUMN logical_release_id text")
    op.execute("UPDATE dataset_releases SET logical_release_id=id::text WHERE logical_release_id IS NULL")
    op.execute("ALTER TABLE dataset_releases ALTER COLUMN logical_release_id SET NOT NULL")
    op.execute("ALTER TABLE dataset_releases ADD CONSTRAINT dataset_releases_logical_id UNIQUE(logical_release_id)")
    op.execute(
        "ALTER TABLE dataset_releases ADD COLUMN status text NOT NULL DEFAULT 'importing' "
        "CHECK(status IN ('importing','completed','failed'))"
    )
    op.execute("ALTER TABLE dataset_releases ADD COLUMN registry_digest char(64)")
    op.execute("ALTER TABLE dataset_releases ADD COLUMN imported_records integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE dataset_releases ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE dataset_import_jobs ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE dataset_import_jobs ADD COLUMN completed_at timestamptz")
    op.execute("ALTER TABLE dataset_import_jobs ADD COLUMN error_code varchar(100)")


def downgrade() -> None:
    op.execute("ALTER TABLE dataset_import_jobs DROP COLUMN IF EXISTS error_code")
    op.execute("ALTER TABLE dataset_import_jobs DROP COLUMN IF EXISTS completed_at")
    op.execute("ALTER TABLE dataset_import_jobs DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE dataset_releases DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE dataset_releases DROP COLUMN IF EXISTS imported_records")
    op.execute("ALTER TABLE dataset_releases DROP COLUMN IF EXISTS registry_digest")
    op.execute("ALTER TABLE dataset_releases DROP COLUMN IF EXISTS status")
    op.execute("ALTER TABLE dataset_releases DROP CONSTRAINT IF EXISTS dataset_releases_logical_id")
    op.execute("ALTER TABLE dataset_releases DROP COLUMN IF EXISTS logical_release_id")
