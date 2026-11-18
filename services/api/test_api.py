import pytest
from nacl.signing import SigningKey
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.protocol.python.lifeline_protocol import (
    HybridLogicalClock,
    SyncBundle,
    new_ulid,
    sign_event,
)
from services.api import main
from services.api.db import Base


@pytest.fixture
def api_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'api.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    yield
    engine.dispose()


def signed_event():
    return sign_event({"event_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV", "hlc": "2026-01-01T00:00:00.000Z-0000-device", "type": "sos.created", "request_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV", "payload": {"people_count": 2}}, SigningKey.generate())


def test_sync_accepts_signed_event_once_and_returns_status(api_db):
    event = signed_event()
    bundle = SyncBundle.model_validate({"protocol_version": 1, "events": [event.model_dump()], "known_event_ids": [], "highest_hlc_by_device": {}})
    first = main.sync(bundle)
    second = main.sync(bundle)
    assert first.accepted_ids == second.accepted_ids == [event.event_id]
    assert first.missing_events == []
    assert main.request_status(event.request_id)["status"] == "received"


def test_sync_rejects_unsigned_event(api_db):
    payload = {"protocol_version": 1, "event_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV", "device_id": "fake", "hlc": "x", "type": "sos.created", "request_id": "01ARZ3NDEKTSV4RRFFQ69G5FAV", "payload": {}, "hops": 0, "signature": ""}
    result = main.sync(SyncBundle.model_validate({"events": [payload], "protocol_version": 1, "known_event_ids": [], "highest_hlc_by_device": {}}))
    assert result.rejected[0]["reason"] == "invalid event signature"


def test_sync_returns_remote_events_not_already_known(api_db):
    event = signed_event()
    main.sync(SyncBundle(events=[event]))
    empty = SyncBundle(events=[], known_event_ids=[])
    assert main.sync(empty).missing_events[0]["event_id"] == event.event_id
    known = SyncBundle(events=[], known_event_ids=[event.event_id])
    assert main.sync(known).missing_events == []


def test_sync_uses_per_origin_highest_hlc_to_avoid_retransmitting_known_prefix(api_db):
    key = SigningKey.generate()
    clock = HybridLogicalClock("device", wall_ms=1767225600000)
    first = sign_event({"event_id": new_ulid(), "hlc": clock.tick(1767225600000), "type": "sos.created",
                        "request_id": new_ulid(), "payload": {}, "hops": 0}, key)
    second = sign_event({"event_id": new_ulid(), "hlc": clock.tick(1767225601000), "type": "sos.created",
                         "request_id": new_ulid(), "payload": {}, "hops": 0}, key)
    main.sync(SyncBundle(events=[first, second]))
    inventory = SyncBundle(events=[], highest_hlc_by_device={first.device_id: first.hlc})
    response = main.sync(inventory)
    assert [event["event_id"] for event in response.missing_events] == [second.event_id]
    complete = SyncBundle(events=[], highest_hlc_by_device={first.device_id: second.hlc})
    assert main.sync(complete).missing_events == []


def test_media_id_is_content_derived():
    assert main.media_id_from_bytes(b"synthetic media") == main.media_id_from_bytes(b"synthetic media")
    assert main.media_id_from_bytes(b"synthetic media") != main.media_id_from_bytes(b"different media")
