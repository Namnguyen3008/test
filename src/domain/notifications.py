"""Idempotent reminder scheduling and safe template rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from string import Formatter


@dataclass(frozen=True)
class Reminder:
    appointment_id: str
    channel: str
    template_id: str
    scheduled_for: datetime

    @property
    def idempotency_key(self) -> tuple[str, str, str, str]:
        return (
            self.appointment_id,
            self.channel,
            self.template_id,
            self.scheduled_for.astimezone(UTC).isoformat(),
        )


class ReminderLedger:
    def __init__(self) -> None:
        self._scheduled: dict[tuple[str, str, str, str], Reminder] = {}
        self._sent: set[tuple[str, str, str, str]] = set()

    def schedule(self, reminder: Reminder) -> bool:
        if reminder.idempotency_key in self._scheduled:
            return False
        self._scheduled[reminder.idempotency_key] = reminder
        return True

    def mark_sent(self, reminder: Reminder) -> bool:
        key = reminder.idempotency_key
        if key in self._sent:
            return False
        if key not in self._scheduled:
            raise KeyError("Reminder was not scheduled")
        self._sent.add(key)
        return True


def render_template(template: str, values: dict[str, str], *, allowed_fields: set[str]) -> str:
    referenced = {name for _, name, _, _ in Formatter().parse(template) if name}
    if not referenced.issubset(allowed_fields) or not referenced.issubset(values):
        raise ValueError("Template contains missing or forbidden variables")
    return template.format_map(values)
