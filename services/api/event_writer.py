"""Create authenticated server-originated events for coordinator actions."""

import base64
import json
import os
from threading import Lock
from typing import Any

from nacl.signing import SigningKey
from sqlalchemy.orm import Session

from packages.protocol.python.lifeline_protocol import (
    EventEnvelope,
    HybridLogicalClock,
    new_ulid,
    sign_event,
)
from services.api.models import EventRecord


def _signing_key() -> SigningKey:
    configured = os.getenv("SYSTEM_SIGNING_PRIVATE_KEY")
    if configured:
        decoded = base64.urlsafe_b64decode(configured + "=" * (-len(configured) % 4))
        return SigningKey(decoded)
    if os.getenv("ENVIRONMENT", "development").casefold() == "production":
        raise RuntimeError("SYSTEM_SIGNING_PRIVATE_KEY is required in production")
    return SigningKey.generate()


_key = _signing_key()
_clock = HybridLogicalClock(bytes(_key.verify_key).hex()[:8])
_lock = Lock()


def append_system_event(
    session: Session,
    request_id: str,
    event_type: str,
    payload: dict[str, Any],
) -> EventEnvelope:
    with _lock:
        hlc = _clock.tick()
    event = sign_event(
        {
            "event_id": new_ulid(),
            "hlc": hlc,
            "type": event_type,
            "request_id": request_id,
            "payload": payload,
            "hops": 0,
        },
        _key,
    )
    session.add(
        EventRecord(
            event_id=event.event_id,
            device_id=event.device_id,
            hlc=event.hlc,
            event_type=event.type,
            request_id=event.request_id,
            payload=json.dumps(payload, sort_keys=True, separators=(",", ":")),
            hops=event.hops,
            signature=event.signature,
            source="https",
        )
    )
    return event
