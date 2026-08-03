from datetime import UTC, datetime

from src.domain.notifications import Reminder, ReminderLedger, render_template


def test_reminders_are_scheduled_and_sent_once():
    reminder = Reminder("a1", "sms", "visit-24h", datetime(2026, 8, 4, tzinfo=UTC))
    ledger = ReminderLedger()
    assert ledger.schedule(reminder)
    assert not ledger.schedule(reminder)
    assert ledger.mark_sent(reminder)
    assert not ledger.mark_sent(reminder)


def test_template_rejects_unapproved_variables():
    assert render_template("Lịch hẹn {code}", {"code": "A1"}, allowed_fields={"code"}) == "Lịch hẹn A1"
