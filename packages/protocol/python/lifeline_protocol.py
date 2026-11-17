"""Version 1 signed event contract shared by Lifeline clients and server."""
import base64
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Any

from nacl.exceptions import BadSignatureError
from nacl.signing import SigningKey, VerifyKey
from pydantic import BaseModel, ConfigDict, Field

PROTOCOL_VERSION = 1
_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def new_ulid() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        chars.append(_CROCKFORD[value & 31])
        value >>= 5
    return "".join(reversed(chars))


def canonical_json(value: dict[str, Any]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


class HybridLogicalClock:
    def __init__(self, device_short_id: str, wall_ms: int | None = None):
        self.device_short_id = device_short_id
        self.wall_ms = wall_ms if wall_ms is not None else int(time.time() * 1000)
        self.counter = 0

    @staticmethod
    def _parse(hlc: str) -> tuple[int, int]:
        timestamp, rest = hlc.split("Z-", 1)
        millis = int(datetime.fromisoformat(timestamp + "Z").timestamp() * 1000)
        return millis, int(rest.split("-", 1)[0])

    def _format(self) -> str:
        stamp = datetime.fromtimestamp(self.wall_ms / 1000, tz=UTC)
        return f"{stamp:%Y-%m-%dT%H:%M:%S}.{self.wall_ms % 1000:03d}Z-{self.counter:04d}-{self.device_short_id}"

    def tick(self, now_ms: int | None = None) -> str:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        if now > self.wall_ms:
            self.wall_ms, self.counter = now, 0
        else:
            self.counter += 1
        return self._format()

    def receive(self, remote_hlc: str, now_ms: int | None = None) -> str:
        remote_ms, remote_counter = self._parse(remote_hlc)
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        previous_ms, previous_counter = self.wall_ms, self.counter
        maximum = max(now, previous_ms, remote_ms)
        if maximum == previous_ms == remote_ms:
            counter = max(previous_counter, remote_counter) + 1
        elif maximum == previous_ms:
            counter = previous_counter + 1
        elif maximum == remote_ms:
            counter = remote_counter + 1
        else:
            counter = 0
        self.wall_ms, self.counter = maximum, counter
        return self._format()


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: int = PROTOCOL_VERSION
    event_id: str = Field(default_factory=new_ulid)
    device_id: str
    hlc: str
    type: str
    request_id: str
    payload: dict[str, Any]
    hops: int = Field(default=0, ge=0, le=12)
    signature: str

    def signed_fields(self) -> dict[str, Any]:
        return self.model_dump(exclude={"signature"})


class SyncBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    protocol_version: int = PROTOCOL_VERSION
    events: list[EventEnvelope]
    known_event_ids: list[str] = Field(default_factory=list)
    highest_hlc_by_device: dict[str, str] = Field(default_factory=dict)


def sign_event(fields: dict[str, Any], signing_key: SigningKey) -> EventEnvelope:
    public = base64.urlsafe_b64encode(bytes(signing_key.verify_key)).decode().rstrip("=")
    body = {"protocol_version": PROTOCOL_VERSION, **fields, "device_id": public}
    body.setdefault("hops", 0)
    signature = base64.urlsafe_b64encode(signing_key.sign(canonical_json(body)).signature).decode().rstrip("=")
    return EventEnvelope(**body, signature=signature)


def verify_event(event: EventEnvelope) -> None:
    if event.protocol_version != PROTOCOL_VERSION:
        raise ValueError("unsupported protocol version")
    try:
        key = base64.urlsafe_b64decode(event.device_id + "=" * (-len(event.device_id) % 4))
        signature = base64.urlsafe_b64decode(event.signature + "=" * (-len(event.signature) % 4))
        VerifyKey(key).verify(canonical_json(event.signed_fields()), signature)
    except (ValueError, BadSignatureError) as exc:
        raise ValueError("invalid event signature") from exc


def merge_event_sets(*event_sets: list[EventEnvelope]) -> list[EventEnvelope]:
    merged: dict[str, EventEnvelope] = {}
    for events in event_sets:
        for event in events:
            previous = merged.get(event.event_id)
            if previous is not None and previous != event:
                raise ValueError(f"conflicting event ID: {event.event_id}")
            merged[event.event_id] = event
    return [merged[key] for key in sorted(merged)]


def lww_winner(current: tuple[str, str, Any] | None, incoming: tuple[str, str, Any]) -> tuple[str, str, Any]:
    return incoming if current is None or incoming[:2] > current[:2] else current
