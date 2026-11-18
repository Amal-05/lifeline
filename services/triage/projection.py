import json
import re
from datetime import UTC, datetime, timedelta

import h3
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from packages.protocol.python.lifeline_protocol import new_ulid
from services.api.models import EventRecord, Incident, MergeCandidate, RequestProjection
from services.api.payload_crypto import open_event_payload
from services.triage.algorithms import (
    MergeDecision,
    RequestSignal,
    replay_request_events,
    score_pair,
    score_urgency,
)
from services.triage.config import DEFAULT_CONFIG


def parse_hlc(hlc: str) -> datetime:
    prefix = hlc.split("Z-", 1)[0] + "Z"
    return datetime.fromisoformat(prefix).astimezone(UTC)


def detect_language(text: str) -> str:
    scripts = {"ml": 0, "hi": 0, "ta": 0}
    for char in text:
        code = ord(char)
        if 0x0D00 <= code <= 0x0D7F:
            scripts["ml"] += 1
        elif 0x0900 <= code <= 0x097F:
            scripts["hi"] += 1
        elif 0x0B80 <= code <= 0x0BFF:
            scripts["ta"] += 1
    language, count = max(scripts.items(), key=lambda item: item[1])
    return language if count else ("en" if re.search(r"[A-Za-z]", text) else "und")


def request_signal(row: RequestProjection) -> RequestSignal:
    created_at = row.created_at
    last_contact_at = row.last_contact_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if last_contact_at.tzinfo is None:
        last_contact_at = last_contact_at.replace(tzinfo=UTC)
    return RequestSignal(
        request_id=row.request_id,
        device_id=row.device_id,
        created_at=created_at,
        latitude=row.latitude,
        longitude=row.longitude,
        accuracy_m=row.accuracy_m or 0,
        people_count=row.people_count,
        text_en=row.text_en,
        categories=tuple(row.categories or ()),
        special_needs=tuple(row.special_needs or ()),
        contact_hash=row.contact_hash,
        perceptual_hash=row.media_perceptual_hash,
        water_level=row.water_level,
        last_contact_at=last_contact_at,
        pre_registered=row.pre_registered,
        battery_pct=row.battery_pct,
        status=row.status,
    )


def _new_incident(row: RequestProjection) -> Incident:
    return Incident(
        incident_id=new_ulid(),
        canonical_request_id=row.request_id,
        latitude=row.latitude,
        longitude=row.longitude,
        h3_res9=h3.latlng_to_cell(row.latitude, row.longitude, 9) if row.latitude is not None and row.longitude is not None else None,
        merged_request_count=1,
        people_count_max=row.people_count,
        urgency_score=0,
        urgency_explain=[],
        status=row.status,
        categories=row.categories or [],
        special_needs=row.special_needs or [],
        language=row.language,
        text_en=row.text_en,
    )


def _recalculate_incident(session: Session, incident: Incident) -> None:
    requests = session.scalars(
        select(RequestProjection).where(RequestProjection.incident_id == incident.incident_id)
    ).all()
    if not requests:
        return
    requests.sort(key=lambda row: (row.created_hlc, row.request_id))
    incident.canonical_request_id = requests[0].request_id
    canonical = requests[0]
    incident.latitude, incident.longitude = canonical.latitude, canonical.longitude
    incident.h3_res9 = (
        h3.latlng_to_cell(canonical.latitude, canonical.longitude, 9)
        if canonical.latitude is not None and canonical.longitude is not None
        else None
    )
    incident.merged_request_count = len(requests)
    incident.people_count_max = max(row.people_count for row in requests)
    incident.categories = sorted({value for row in requests for value in row.categories or []})
    incident.special_needs = sorted({value for row in requests for value in row.special_needs or []})
    devices = len({row.device_id for row in requests})
    now = datetime.now(UTC)
    urgent = [score_urgency(request_signal(row), now, devices) for row in requests]
    selected = max(urgent, key=lambda item: item.score)
    overrides = [row for row in requests if row.urgency_override is not None]
    if overrides:
        override = max(overrides, key=lambda row: (row.last_event_hlc, row.device_id))
        incident.override_score = override.urgency_override
        incident.override_reason = override.urgency_override_reason
    else:
        incident.override_score = None
        incident.override_reason = None
    if incident.override_score is None:
        incident.urgency_score = selected.score
        incident.urgency_explain = list(selected.explanation)
    incident.status = canonical.status
    incident.language = canonical.language
    incident.text_en = canonical.text_en


def _attach_request_to_incident(session: Session, row: RequestProjection, incident: Incident) -> None:
    if row.incident_id and row.incident_id != incident.incident_id:
        previous = session.get(Incident, row.incident_id)
        if previous is not None:
            previous.merged_into = incident.incident_id
            previous.status = "merged"
            session.execute(
                update(RequestProjection)
                .where(RequestProjection.incident_id == previous.incident_id)
                .values(incident_id=incident.incident_id)
            )
    row.incident_id = incident.incident_id
    _recalculate_incident(session, incident)


def project_request_events(session: Session, request_id: str) -> RequestProjection | None:
    records = session.scalars(
        select(EventRecord).where(EventRecord.request_id == request_id).order_by(EventRecord.hlc, EventRecord.device_id, EventRecord.event_id)
    ).all()
    if not records:
        return None
    events = [
        {"hlc": row.hlc, "device_id": row.device_id, "type": row.event_type, "request_id": row.request_id,
         "payload": open_event_payload(json.loads(row.payload))}
        for row in records
    ]
    data = replay_request_events(events)
    created_hlc = str(data.get("created_hlc") or records[0].hlc)
    created_at = parse_hlc(created_hlc)
    payload = open_event_payload(json.loads(next(row.payload for row in records if row.event_type == "sos.created")))
    loc = payload.get("location") or {}
    original = str(data.get("text_original") or "")
    language = str(data.get("language") or detect_language(original))
    # The translation provider is intentionally pluggable. Without configured model data,
    # retain the original and label the language rather than inventing a translation.
    text_en = str(data.get("text_en") or (original if language == "en" else ""))
    row = session.get(RequestProjection, request_id)
    fields = {
        "request_id": request_id,
        "device_id": str(data.get("device_id") or records[0].device_id),
        "created_hlc": created_hlc,
        "last_event_hlc": records[-1].hlc,
        "latitude": loc.get("latitude", data.get("latitude")),
        "longitude": loc.get("longitude", data.get("longitude")),
        "h3_res10": None,
        "accuracy_m": loc.get("accuracy_m", data.get("accuracy_m")),
        "location_source": str(data.get("location_source", loc.get("source", "unavailable"))),
        "people_count": int(data.get("people_count", 1)),
        "categories": list(data.get("categories", [])),
        "special_needs": list(data.get("special_needs", [])),
        "text_original": original,
        "text_en": text_en,
        "language": language,
        "contact_hash": payload.get("contact_hash"),
        "media_perceptual_hash": (payload.get("media_ids") or {}).get("photo"),
        "water_level": payload.get("water_level"),
        "pre_registered": bool(payload.get("pre_registered", False)),
        "battery_pct": payload.get("battery_pct"),
        "status": str(data.get("status", "received")),
        "incident_id": data.get("incident_id"),
        "urgency_override": data.get("urgency_override"),
        "urgency_override_reason": data.get("urgency_override_reason"),
        "last_contact_at": parse_hlc(str(data.get("last_contact_hlc", created_hlc))),
        "created_at": created_at,
    }
    if fields["latitude"] is not None and fields["longitude"] is not None:
        fields["h3_res10"] = h3.latlng_to_cell(float(fields["latitude"]), float(fields["longitude"]), 10)
    if "incident_id" not in data:
        fields.pop("incident_id")
    if row is None:
        row = RequestProjection(**fields)
        session.add(row)
    else:
        for key, value in fields.items():
            if key not in {"request_id", "created_at"}:
                setattr(row, key, value)
    session.flush()
    return row


def triage_request(session: Session, row: RequestProjection) -> Incident:
    candidate_rows = []
    if row.h3_res10 is not None:
        cells = list(h3.grid_disk(row.h3_res10, 1))
        window = timedelta(hours=DEFAULT_CONFIG.candidate_window_hours)
        start = row.created_at - window
        candidate_rows = session.scalars(
            select(RequestProjection).where(
                RequestProjection.request_id != row.request_id,
                RequestProjection.h3_res10.in_(cells),
                RequestProjection.created_at >= start,
                RequestProjection.created_at <= row.created_at + window,
            )
        ).all()
    signal = request_signal(row)
    matches: list[tuple[Incident, RequestProjection]] = []
    for other in candidate_rows:
        left, right = sorted((row.request_id, other.request_id))
        pair_id = f"{left}:{right}"
        if session.get(MergeCandidate, pair_id) is not None:
            continue
        result = score_pair(signal, request_signal(other))
        candidate = MergeCandidate(
            pair_id=pair_id,
            request_a=left,
            request_b=right,
            score=result.score,
            features={**result.features, "distance_m": result.distance_m, "reason": result.reason},
            decision=result.decision.value,
        )
        session.add(candidate)
        if result.decision == MergeDecision.AUTO_MERGED:
            incident = session.get(Incident, other.incident_id) if other.incident_id else None
            if incident is None:
                incident = _new_incident(other)
                session.add(incident)
                session.flush()
                other.incident_id = incident.incident_id
            matches.append((incident, other))
    if matches:
        matches.sort(key=lambda item: (item[0].canonical_request_id, item[0].incident_id))
        selected = matches[0][0]
        for extra, other in matches[1:]:
            if extra.incident_id != selected.incident_id:
                session.execute(
                    update(RequestProjection)
                    .where(RequestProjection.incident_id == extra.incident_id)
                    .values(incident_id=selected.incident_id)
                )
                extra.merged_into = selected.incident_id
                extra.status = "merged"
                _recalculate_incident(session, selected)
        for _, other in matches:
            _attach_request_to_incident(session, other, selected)
        _attach_request_to_incident(session, row, selected)
        return selected
    incident = _new_incident(row)
    session.add(incident)
    session.flush()
    row.incident_id = incident.incident_id
    _recalculate_incident(session, incident)
    return incident


def process_event_record(session: Session, record: EventRecord) -> Incident | None:
    if record.event_type not in {"sos.created", "sos.updated", "sos.ping", "status.changed"}:
        return None
    existed = session.get(RequestProjection, record.request_id)
    old_incident_id = existed.incident_id if existed else None
    row = project_request_events(session, record.request_id)
    if row is None:
        return None
    if existed is None:
        return triage_request(session, row)
    if record.event_type == "sos.ping":
        row.last_contact_at = datetime.now(UTC)
        state = open_event_payload(json.loads(record.payload)).get("state")
        if state == "safe":
            row.status = "safe"
    if record.event_type == "status.changed":
        row.status = open_event_payload(json.loads(record.payload)).get("status", row.status)
    incident = session.get(Incident, row.incident_id) if row.incident_id else None
    if incident is None and row.incident_id:
        incident = _new_incident(row)
        incident.incident_id = row.incident_id
        session.add(incident)
        session.flush()
    if incident:
        _recalculate_incident(session, incident)
    if old_incident_id and old_incident_id != row.incident_id:
        old_incident = session.get(Incident, old_incident_id)
        if old_incident is not None:
            _recalculate_incident(session, old_incident)
    return incident
