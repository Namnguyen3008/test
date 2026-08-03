"""Human clinical review workflow and immutable decisions.

Revision ID: 20260803_0006_clinical_review
Revises: 20260803_0005_retrieval_runtime
"""

from alembic import op

revision = "20260803_0006_clinical_review"
down_revision = "20260803_0005_retrieval_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE clinical_review_items (
            id uuid PRIMARY KEY,
            release_id uuid NOT NULL,
            record_id uuid,
            origin_table text NOT NULL,
            origin_row_id text NOT NULL,
            content_hash char(64) NOT NULL,
            evidence_summary text NOT NULL,
            source_ids jsonb NOT NULL,
            safety_critical boolean NOT NULL DEFAULT false,
            required_reviews integer NOT NULL DEFAULT 1 CHECK(required_reviews IN (1,2)),
            status text NOT NULL DEFAULT 'PENDING' CHECK(status IN
              ('PENDING','CLAIMED','CHANGES_REQUESTED','ADJUDICATION_REQUIRED','APPROVED','REJECTED')),
            claimed_by uuid REFERENCES users(id),
            claim_expires_at timestamptz,
            version integer NOT NULL DEFAULT 1 CHECK(version > 0),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(release_id,origin_table,origin_row_id)
        )
    """)
    op.execute(
        "CREATE INDEX clinical_review_queue ON clinical_review_items(status,updated_at,id) "
        "WHERE status NOT IN ('APPROVED','REJECTED')"
    )
    op.execute("""
        CREATE TABLE clinical_review_decisions (
            id bigserial PRIMARY KEY,
            item_id uuid NOT NULL REFERENCES clinical_review_items(id),
            reviewer_id uuid NOT NULL REFERENCES users(id),
            decision text NOT NULL CHECK(decision IN ('APPROVE','REJECT','REQUEST_CHANGES')),
            rationale text NOT NULL,
            item_version integer NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(item_id,reviewer_id,item_version)
        )
    """)
    op.execute("CREATE INDEX clinical_review_decisions_item ON clinical_review_decisions(item_id,created_at,id)")
    op.execute("""
        CREATE FUNCTION vmec_prevent_clinical_review_decision_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'clinical_review_decisions is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER clinical_review_decisions_append_only
        BEFORE UPDATE OR DELETE ON clinical_review_decisions
        FOR EACH ROW EXECUTE FUNCTION vmec_prevent_clinical_review_decision_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS clinical_review_decisions_append_only ON clinical_review_decisions")
    op.execute("DROP FUNCTION IF EXISTS vmec_prevent_clinical_review_decision_mutation")
    op.execute("DROP TABLE IF EXISTS clinical_review_decisions")
    op.execute("DROP TABLE IF EXISTS clinical_review_items")
