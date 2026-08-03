"""Persistent transactional booking, reschedule holds and outbox.

Revision ID: 20260803_0003_booking
Revises: 20260803_0002_identity
"""

from alembic import op

revision = "20260803_0003_booking"
down_revision = "20260803_0002_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE slots ADD COLUMN specialty_id text")
    op.execute("ALTER TABLE slots ADD COLUMN facility_id text")
    op.execute("ALTER TABLE slots ADD COLUMN enabled boolean NOT NULL DEFAULT true")
    op.execute("ALTER TABLE slots ADD COLUMN created_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE slots ADD CONSTRAINT ck_slots_time_range CHECK (ends_at > starts_at)")
    op.execute("ALTER TABLE slots ADD CONSTRAINT ck_slots_capacity CHECK (capacity > 0)")
    op.execute("CREATE INDEX ix_slots_search ON slots (specialty_id, facility_id, starts_at) WHERE enabled")

    op.execute("ALTER TABLE appointments ADD COLUMN proposed_slot_id uuid REFERENCES slots(id)")
    op.execute("ALTER TABLE appointments ADD COLUMN patient_reconfirmed_at timestamptz")
    op.execute("ALTER TABLE appointments ADD COLUMN cancelled_at timestamptz")
    op.execute("ALTER TABLE appointments ADD COLUMN created_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE appointments ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE appointments ALTER COLUMN slot_id SET NOT NULL")
    op.execute("ALTER TABLE appointments ALTER COLUMN patient_id SET NOT NULL")
    op.execute("ALTER TABLE appointments ADD CONSTRAINT ck_appointments_version CHECK (version > 0)")
    op.execute("""
        ALTER TABLE appointments ADD CONSTRAINT ck_appointments_status CHECK (
            status IN ('HELD','PATIENT_CONFIRMED','PENDING_STAFF_APPROVAL','CONFIRMED','RESCHEDULE_PROPOSED',
                       'CANCELLED','REJECTED','EXPIRED')
        )
    """)
    op.execute("CREATE INDEX ix_appointments_patient_history ON appointments (patient_id, created_at DESC)")
    op.execute(
        "CREATE INDEX ix_appointments_pending ON appointments (updated_at) WHERE status='PENDING_STAFF_APPROVAL'"
    )

    op.execute("""
        CREATE TABLE slot_holds (
            id uuid PRIMARY KEY,
            slot_id uuid NOT NULL REFERENCES slots(id),
            appointment_id uuid NOT NULL REFERENCES appointments(id),
            patient_id uuid NOT NULL REFERENCES users(id),
            kind text NOT NULL CHECK (kind IN ('INITIAL', 'RESCHEDULE')),
            expires_at timestamptz,
            released_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE UNIQUE INDEX uq_slot_holds_active_slot ON slot_holds(slot_id) WHERE released_at IS NULL")
    op.execute("CREATE INDEX ix_slot_holds_expiry ON slot_holds(expires_at) WHERE released_at IS NULL")
    op.execute("CREATE INDEX ix_slot_holds_appointment_id ON slot_holds(appointment_id)")

    op.execute("ALTER TABLE idempotency_keys ADD COLUMN request_hash char(64)")
    op.execute("ALTER TABLE idempotency_keys ADD COLUMN response_json jsonb")
    op.execute("""
        CREATE TABLE booking_outbox (
            id bigserial PRIMARY KEY,
            aggregate_id uuid NOT NULL REFERENCES appointments(id),
            event_type text NOT NULL,
            payload jsonb NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            delivered_at timestamptz
        )
    """)
    op.execute("CREATE INDEX ix_booking_outbox_pending ON booking_outbox(id) WHERE delivered_at IS NULL")
    op.execute("""
        CREATE FUNCTION vmec_prevent_appointment_event_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'appointment_events is append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER appointment_events_append_only
        BEFORE UPDATE OR DELETE ON appointment_events
        FOR EACH ROW EXECUTE FUNCTION vmec_prevent_appointment_event_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS appointment_events_append_only ON appointment_events")
    op.execute("DROP FUNCTION IF EXISTS vmec_prevent_appointment_event_mutation")
    op.execute("DROP TABLE IF EXISTS booking_outbox")
    op.execute("ALTER TABLE idempotency_keys DROP COLUMN IF EXISTS response_json")
    op.execute("ALTER TABLE idempotency_keys DROP COLUMN IF EXISTS request_hash")
    op.execute("DROP TABLE IF EXISTS slot_holds")
    op.execute("DROP INDEX IF EXISTS ix_appointments_pending")
    op.execute("DROP INDEX IF EXISTS ix_appointments_patient_history")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ck_appointments_status")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ck_appointments_version")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS updated_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS created_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS cancelled_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS patient_reconfirmed_at")
    op.execute("ALTER TABLE appointments DROP COLUMN IF EXISTS proposed_slot_id")
    op.execute("DROP INDEX IF EXISTS ix_slots_search")
    op.execute("ALTER TABLE slots DROP CONSTRAINT IF EXISTS ck_slots_capacity")
    op.execute("ALTER TABLE slots DROP CONSTRAINT IF EXISTS ck_slots_time_range")
    op.execute("ALTER TABLE slots DROP COLUMN IF EXISTS created_at")
    op.execute("ALTER TABLE slots DROP COLUMN IF EXISTS enabled")
    op.execute("ALTER TABLE slots DROP COLUMN IF EXISTS facility_id")
    op.execute("ALTER TABLE slots DROP COLUMN IF EXISTS specialty_id")
