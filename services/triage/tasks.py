import json
import os
from typing import Any

import redis

from services.api.db import SessionLocal
from services.api.models import EventRecord
from services.triage.celery_app import celery_app
from services.triage.projection import process_event_record

REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
STREAM_KEY = "lifeline:dashboard:events"


def publish_dashboard_event(event: dict[str, Any]) -> str:
    client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        stream_id = client.xadd(STREAM_KEY, {"data": json.dumps(event, separators=(",", ":"))}, maxlen=10_000, approximate=True)
        return stream_id
    finally:
        client.close()


@celery_app.task(
    name="lifeline.process_event",
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 5},
)
def process_event(event_id: str) -> dict[str, Any]:
    with SessionLocal() as session:
        record = session.get(EventRecord, event_id)
        if record is None:
            return {"event_id": event_id, "status": "missing"}
        incident = process_event_record(session, record)
        session.commit()
        if incident is None:
            return {"event_id": event_id, "status": "stored"}
        message = {
            "type": "incident.updated" if incident.merged_request_count > 1 else "incident.created",
            "incident_id": incident.incident_id,
            "request_id": record.request_id,
            "urgency": incident.override_score if incident.override_score is not None else incident.urgency_score,
            "status": incident.status,
            "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
        }
    stream_id = publish_dashboard_event(message)
    return {"event_id": event_id, "status": "projected", "incident_id": incident.incident_id, "seq": stream_id}
