import os

from celery import Celery

broker_url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
celery_app = Celery("lifeline", broker=broker_url, include=["services.triage.tasks"])
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
)
