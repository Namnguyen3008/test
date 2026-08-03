"""Persist identities, Redis session metadata, consent and audit hardening.

Revision ID: 20260803_0002_identity
Revises: 20260803_0001
"""

from alembic import op

revision = "20260803_0002_identity"
down_revision = "20260803_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN email text")
    op.execute("UPDATE users SET email = 'legacy-' || id::text || '@invalid.local' WHERE email IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN email SET NOT NULL")
    op.execute("UPDATE users SET active = false, password_hash = '!legacy-disabled!' WHERE password_hash IS NULL")
    op.execute("ALTER TABLE users ALTER COLUMN password_hash SET NOT NULL")
    op.execute("ALTER TABLE users ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("CREATE UNIQUE INDEX uq_users_email ON users (lower(email))")
    op.execute("""
        CREATE TABLE auth_sessions (
            id uuid PRIMARY KEY,
            user_id uuid NOT NULL REFERENCES users(id),
            token_digest char(64) NOT NULL UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            revoked_at timestamptz,
            revoke_reason text
        )
    """)
    op.execute("CREATE INDEX ix_auth_sessions_user_id ON auth_sessions(user_id)")
    op.execute("CREATE INDEX ix_auth_sessions_active ON auth_sessions(user_id, expires_at, revoked_at)")
    op.execute("ALTER TABLE consent_grants ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("CREATE UNIQUE INDEX uq_consent_patient_purpose ON consent_grants(patient_id, purpose)")
    op.execute("CREATE INDEX ix_consent_grants_patient_id ON consent_grants(patient_id)")
    op.execute("CREATE INDEX ix_audit_events_actor_id ON audit_events(actor_id)")
    op.execute("""
        CREATE FUNCTION vmec_prevent_audit_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION vmec_prevent_audit_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS audit_events_append_only ON audit_events")
    op.execute("DROP FUNCTION IF EXISTS vmec_prevent_audit_mutation")
    op.execute("DROP INDEX IF EXISTS ix_audit_events_actor_id")
    op.execute("DROP INDEX IF EXISTS ix_consent_grants_patient_id")
    op.execute("DROP INDEX IF EXISTS uq_consent_patient_purpose")
    op.execute("ALTER TABLE consent_grants DROP COLUMN IF EXISTS updated_at")
    op.execute("DROP TABLE IF EXISTS auth_sessions")
    op.execute("DROP INDEX IF EXISTS uq_users_email")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE users ALTER COLUMN password_hash DROP NOT NULL")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
