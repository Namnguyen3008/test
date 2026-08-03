"""Signed governance manifest, atomic promotion, and immutable receipts.

Revision ID: 20260803_0009_governance_bridge
Revises: 20260803_0008_persistent_import
"""

from alembic import op

revision = "20260803_0009_governance_bridge"
down_revision = "20260803_0008_persistent_import"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE knowledge_records ADD COLUMN safety_critical boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE knowledge_records ADD COLUMN gold_candidate boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE knowledge_records ADD COLUMN gold_reason text NOT NULL DEFAULT ''")
    op.execute("""
        CREATE TABLE dataset_release_sources (
            release_id uuid NOT NULL REFERENCES dataset_releases(id),
            source_id text NOT NULL REFERENCES global_sources(id),
            PRIMARY KEY(release_id,source_id)
        )
    """)
    op.execute("""
        CREATE TABLE governance_manifests (
            manifest_id text PRIMARY KEY,
            manifest_digest char(64) NOT NULL UNIQUE,
            scope_digest char(64) NOT NULL UNIQUE,
            key_id char(64) NOT NULL,
            release_scope jsonb NOT NULL,
            evidence_digest char(64) NOT NULL,
            status text NOT NULL CHECK(status IN ('VERIFIED','PROMOTED','REVOKED','SUPERSEDED')),
            verified_at timestamptz NOT NULL,
            promoted_at timestamptz
        )
    """)
    op.execute("""
        CREATE TABLE governance_promotions (
            id uuid PRIMARY KEY,
            manifest_id text NOT NULL UNIQUE REFERENCES governance_manifests(manifest_id),
            receipt jsonb NOT NULL,
            receipt_digest char(64) NOT NULL UNIQUE,
            receipt_key_id char(64) NOT NULL,
            created_at timestamptz NOT NULL
        )
    """)
    op.execute("""
        CREATE TABLE governance_row_promotions (
            id bigserial PRIMARY KEY,
            promotion_id uuid NOT NULL REFERENCES governance_promotions(id) DEFERRABLE INITIALLY DEFERRED,
            manifest_id text NOT NULL REFERENCES governance_manifests(manifest_id),
            source_record_id uuid NOT NULL REFERENCES knowledge_records(id),
            record_id uuid NOT NULL REFERENCES knowledge_records(id),
            content_hash char(64) NOT NULL,
            source_digest char(64) NOT NULL,
            before_canonical_status text NOT NULL,
            before_review_status text NOT NULL,
            after_canonical_status text NOT NULL CHECK(after_canonical_status IN ('ACCEPTED','GOLD')),
            after_review_status text NOT NULL CHECK(after_review_status='CLINICALLY_APPROVED'),
            created_at timestamptz NOT NULL,
            UNIQUE(promotion_id,record_id)
        )
    """)
    op.execute("""
        CREATE FUNCTION vmec_prevent_governance_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'governance audit tables are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE FUNCTION vmec_guard_governance_manifest_transition() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'governance manifests cannot be deleted';
            END IF;
            IF OLD.status = 'VERIFIED' AND NEW.status = 'PROMOTED'
               AND OLD.manifest_id = NEW.manifest_id
               AND OLD.manifest_digest = NEW.manifest_digest
               AND OLD.scope_digest = NEW.scope_digest
               AND OLD.key_id = NEW.key_id
               AND OLD.release_scope = NEW.release_scope
               AND OLD.evidence_digest = NEW.evidence_digest
               AND OLD.verified_at = NEW.verified_at
               AND OLD.promoted_at IS NULL AND NEW.promoted_at IS NOT NULL THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'governance manifest is immutable outside VERIFIED to PROMOTED';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute(
        "CREATE TRIGGER governance_manifests_guard BEFORE UPDATE OR DELETE ON governance_manifests "
        "FOR EACH ROW EXECUTE FUNCTION vmec_guard_governance_manifest_transition()"
    )
    for table in ("governance_promotions", "governance_row_promotions"):
        op.execute(
            f"CREATE TRIGGER {table}_append_only BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION vmec_prevent_governance_audit_mutation()"
        )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS governance_manifests_guard ON governance_manifests")
    op.execute("DROP FUNCTION IF EXISTS vmec_guard_governance_manifest_transition")
    for table in ("governance_row_promotions", "governance_promotions"):
        op.execute(f"DROP TRIGGER IF EXISTS {table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS vmec_prevent_governance_audit_mutation")
    op.execute("DROP TABLE IF EXISTS governance_row_promotions")
    op.execute("DROP TABLE IF EXISTS governance_promotions")
    op.execute("DROP TABLE IF EXISTS governance_manifests")
    op.execute("DROP TABLE IF EXISTS dataset_release_sources")
    op.execute("ALTER TABLE knowledge_records DROP COLUMN IF EXISTS gold_reason")
    op.execute("ALTER TABLE knowledge_records DROP COLUMN IF EXISTS gold_candidate")
    op.execute("ALTER TABLE knowledge_records DROP COLUMN IF EXISTS safety_critical")
