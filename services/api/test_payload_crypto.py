import base64
import json

import pytest
from nacl.public import PrivateKey, SealedBox
from nacl.signing import SigningKey
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from packages.protocol.python.lifeline_protocol import SyncBundle, new_ulid, sign_event
from services.api import main
from services.api.db import Base
from services.api.models import EventRecord, RequestProjection
from services.api.payload_crypto import ALGORITHM, coordinator_public_key, open_event_payload
from services.triage.projection import process_event_record


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


@pytest.fixture
def encrypted_api_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'sealed-api.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", factory)
    yield factory
    engine.dispose()


def test_coordinator_sealed_payload_is_decrypted_only_for_projection(encrypted_api_db, monkeypatch):
    coordinator = PrivateKey.generate()
    monkeypatch.setenv("COORDINATOR_SECRET_KEY", _b64(bytes(coordinator)))
    content = {"people_count": 3, "categories": ["medical"], "special_needs": ["elderly"],
               "text_original": "synthetic test", "language": "en",
               "location": {"latitude": 10.5, "longitude": 76.2, "accuracy_m": 8, "source": "manual"}}
    ciphertext = SealedBox(coordinator.public_key).encrypt(json.dumps(content, separators=(",", ":")).encode())
    sealed = {"_sealed_payload": {"version": 1, "algorithm": ALGORITHM, "ciphertext": _b64(ciphertext)}}
    key = SigningKey.generate()
    request_id = new_ulid()
    event = sign_event({"event_id": new_ulid(), "hlc": "2026-11-18T00:00:00.000Z-0000-test",
                        "type": "sos.created", "request_id": request_id, "payload": sealed, "hops": 0}, key)

    response = main.sync(SyncBundle(events=[event]))
    assert response.accepted_ids == [event.event_id]
    assert response.rejected == []
    assert coordinator_public_key() == _b64(bytes(coordinator.public_key))
    with encrypted_api_db() as session:
        record = session.get(EventRecord, event.event_id)
        assert "synthetic test" not in record.payload
        assert process_event_record(session, record) is not None
        projection = session.get(RequestProjection, request_id)
        assert projection.text_original == "synthetic test"
        assert projection.latitude == 10.5


def test_sealed_event_is_rejected_without_coordinator_key(encrypted_api_db, monkeypatch):
    monkeypatch.delenv("COORDINATOR_SECRET_KEY", raising=False)
    event = sign_event({"event_id": new_ulid(), "hlc": "2026-11-18T00:00:00.000Z-0000-test",
                        "type": "sos.created", "request_id": new_ulid(),
                        "payload": {"_sealed_payload": {"version": 1, "algorithm": ALGORITHM, "ciphertext": "AA"}},
                        "hops": 0}, SigningKey.generate())
    response = main.sync(SyncBundle(events=[event]))
    assert response.accepted_ids == []
    assert response.rejected[0]["reason"] == "coordinator decryption key is not configured"


def test_plaintext_legacy_payload_remains_compatible():
    payload = {"people_count": 2, "text_original": "synthetic legacy"}
    assert open_event_payload(payload) is payload
