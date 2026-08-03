"""Celery worker with PHI-safe scheduled task registration."""

from celery import Celery  # type: ignore[import-untyped]

from src.config import get_settings
from src.persistence.database import get_session_factory
from src.workers.booking import BookingMaintenance, UnavailableDeliverySink

settings = get_settings()
app = Celery("vmec", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
    beat_schedule={
        "expire-slot-holds": {"task": "vmec.booking.expire_holds", "schedule": 30.0},
        "schedule-reminders": {"task": "vmec.booking.schedule_reminders", "schedule": 300.0},
        "dispatch-booking-outbox": {"task": "vmec.booking.dispatch_outbox", "schedule": 10.0},
        "dispatch-reminders": {"task": "vmec.booking.dispatch_reminders", "schedule": 30.0},
    },
)


def maintenance() -> BookingMaintenance:
    return BookingMaintenance(get_session_factory())


@app.task(name="vmec.health_probe")
def health_probe() -> dict[str, str]:
    return {"status": "ok"}


@app.task(name="vmec.booking.expire_holds")
def expire_holds() -> dict[str, int]:
    return {"expired": maintenance().expire_holds()}


@app.task(name="vmec.booking.schedule_reminders")
def schedule_reminders() -> dict[str, int]:
    return {"scheduled": maintenance().schedule_reminders()}


@app.task(name="vmec.booking.dispatch_outbox")
def dispatch_outbox() -> dict[str, int]:
    return maintenance().dispatch_outbox(UnavailableDeliverySink())


@app.task(name="vmec.booking.dispatch_reminders")
def dispatch_reminders() -> dict[str, int]:
    return maintenance().dispatch_reminders(UnavailableDeliverySink())


@app.task(name="vmec.booking.analytics_snapshot")
def analytics_snapshot() -> dict[str, dict[str, int]]:
    return maintenance().analytics_snapshot()


if __name__ == "__main__":
    app.worker_main(["worker", "--loglevel=INFO", "--without-gossip", "--without-mingle"])
