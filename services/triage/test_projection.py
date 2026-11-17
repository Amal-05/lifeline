import json

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from packages.protocol.python.lifeline_protocol import new_ulid
from services.api.db import Base
from services.api.models import EventRecord, Incident, MergeCandidate, RequestProjection
from services.triage.projection import process_event_record


def make_event(session, request_id, device_id, event_type, payload, suffix):
    event = EventRecord(
        event_id=new_ulid(),
        device_id=device_id,
        hlc=f"2026-11-17T12:00:{suffix:02d}.000Z-0000-{device_id[:8]}",
        event_type=event_type,
        request_id=request_id,
        payload=json.dumps(payload),
        hops=0,
        signature="synthetic-signature",
    )
    session.add(event)
    session.flush()
    return event


def db_session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'projection.db'}")
    Base.metadata.create_all(engine)
    return engine, Session(engine, expire_on_commit=False)


def test_event_replay_projects_sos_and_status_idempotently(tmp_path):
    engine, session = db_session(tmp_path)
    try:
        request_id = new_ulid()
        created = make_event(session, request_id, "device-a", "sos.created", {
            "people_count": 2, "categories": ["medical"], "special_needs": ["infant"],
            "text_original": "urgent medical help", "location": {"latitude": 10.0, "longitude": 76.0, "accuracy_m": 5, "source": "gps"},
        }, 1)
        incident = process_event_record(session, created)
        session.commit()
        assert incident is not None
        row = session.get(RequestProjection, request_id)
        assert row is not None and row.incident_id == incident.incident_id
        assert incident.urgency_score >= 35
        assert row.h3_res10
        assert process_event_record(session, created).incident_id == incident.incident_id
        assert len(session.scalars(select(Incident)).all()) == 1
        status = make_event(session, request_id, "device-a", "status.changed", {"status": "rescued"}, 2)
        process_event_record(session, status)
        session.commit()
        assert row.status == "rescued"
        assert incident.urgency_score == 0
    finally:
        session.close()
        engine.dispose()


def test_candidate_merge_is_saved_and_people_count_uses_maximum(tmp_path):
    engine, session = db_session(tmp_path)
    try:
        requests = [new_ulid(), new_ulid()]
        first = make_event(session, requests[0], "device-a", "sos.created", {
            "people_count": 5, "categories": ["trapped"], "text_original": "people trapped near school",
            "contact_hash": "synthetic-contact", "location": {"latitude": 10.0, "longitude": 76.0, "accuracy_m": 3, "source": "gps"},
        }, 1)
        process_event_record(session, first)
        second = make_event(session, requests[1], "device-b", "sos.created", {
            "people_count": 7, "categories": ["trapped"], "text_original": "people trapped near school",
            "contact_hash": "synthetic-contact", "location": {"latitude": 10.00001, "longitude": 76.0, "accuracy_m": 3, "source": "gps"},
        }, 2)
        incident = process_event_record(session, second)
        session.commit()
        rows = session.scalars(select(RequestProjection).order_by(RequestProjection.request_id)).all()
        assert rows[0].incident_id == rows[1].incident_id == incident.incident_id
        assert incident.merged_request_count == 2
        assert incident.people_count_max == 7
        candidate = session.scalar(select(MergeCandidate))
        assert candidate is not None and candidate.decision == "auto_merged"
    finally:
        session.close()
        engine.dispose()
