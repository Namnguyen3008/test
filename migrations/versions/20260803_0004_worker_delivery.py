"""Retryable outbox, reminder delivery and no-show state.

Revision ID: 20260803_0004_worker_delivery
Revises: 20260803_0003_booking
"""

from alembic import op

revision = "20260803_0004_worker_delivery"
down_revision = "20260803_0003_booking"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE booking_outbox ADD COLUMN available_at timestamptz NOT NULL DEFAULT now()")
    op.execute("ALTER TABLE booking_outbox ADD COLUMN attempt_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE booking_outbox ADD COLUMN locked_at timestamptz")
    op.execute("ALTER TABLE booking_outbox ADD COLUMN last_error_code varchar(100)")
    op.execute("ALTER TABLE booking_outbox ADD COLUMN dead_lettered_at timestamptz")
    op.execute("DROP INDEX IF EXISTS ix_booking_outbox_pending")
    op.execute(
        "CREATE INDEX ix_booking_outbox_pending ON booking_outbox(available_at,id) "
        "WHERE delivered_at IS NULL AND dead_lettered_at IS NULL"
    )
    op.execute("""
        CREATE TABLE appointment_reminders (
            id bigserial PRIMARY KEY,
            appointment_id uuid NOT NULL REFERENCES appointments(id),
            channel varchar(20) NOT NULL,
            template_id varchar(80) NOT NULL,
            scheduled_for timestamptz NOT NULL,
            status varchar(20) NOT NULL DEFAULT 'PENDING',
            available_at timestamptz NOT NULL DEFAULT now(),
            attempt_count integer NOT NULL DEFAULT 0,
            locked_at timestamptz,
            last_error_code varchar(100),
            delivered_at timestamptz,
            dead_lettered_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT uq_appointment_reminder_delivery
              UNIQUE (appointment_id,channel,template_id,scheduled_for)
        )
    """)
    op.execute("CREATE INDEX ix_appointment_reminders_appointment_id ON appointment_reminders(appointment_id)")
    op.execute("CREATE INDEX ix_appointment_reminders_due ON appointment_reminders(status,available_at,scheduled_for)")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT ck_appointments_status")
    op.execute("""
        ALTER TABLE appointments ADD CONSTRAINT ck_appointments_status CHECK (
            status IN ('HELD','PATIENT_CONFIRMED','PENDING_STAFF_APPROVAL','CONFIRMED','RESCHEDULE_PROPOSED',
                       'CANCELLED','REJECTED','EXPIRED','NO_SHOW')
        )
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT ck_appointments_status")
    op.execute("""
        ALTER TABLE appointments ADD CONSTRAINT ck_appointments_status CHECK (
            status IN ('HELD','PATIENT_CONFIRMED','PENDING_STAFF_APPROVAL','CONFIRMED','RESCHEDULE_PROPOSED',
                       'CANCELLED','REJECTED','EXPIRED')
        )
    """)
    op.execute("DROP TABLE IF EXISTS appointment_reminders")
    op.execute("DROP INDEX IF EXISTS ix_booking_outbox_pending")
    op.execute("ALTER TABLE booking_outbox DROP COLUMN IF EXISTS dead_lettered_at")
    op.execute("ALTER TABLE booking_outbox DROP COLUMN IF EXISTS last_error_code")
    op.execute("ALTER TABLE booking_outbox DROP COLUMN IF EXISTS locked_at")
    op.execute("ALTER TABLE booking_outbox DROP COLUMN IF EXISTS attempt_count")
    op.execute("ALTER TABLE booking_outbox DROP COLUMN IF EXISTS available_at")
    op.execute("CREATE INDEX ix_booking_outbox_pending ON booking_outbox(id) WHERE delivered_at IS NULL")
