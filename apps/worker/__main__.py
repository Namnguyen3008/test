"""Celery worker with PHI-safe scheduled task registration."""

from celery import Celery

from src.config import get_settings

settings = get_settings()
app = Celery("vmec", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Ho_Chi_Minh",
    enable_utc=True,
)


@app.task(name="vmec.health_probe")
def health_probe() -> dict[str, str]:
    return {"status": "ok"}


if __name__ == "__main__":
    app.worker_main(["worker", "--loglevel=INFO", "--without-gossip", "--without-mingle"])
