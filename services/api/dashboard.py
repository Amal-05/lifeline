from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import os
import re
from datetime import UTC, datetime
from typing import Annotated, Any

import h3
import redis.asyncio as async_redis
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import String, and_, cast, func, or_, select, update
from sqlalchemy.orm import Session

from packages.protocol.python.lifeline_protocol import new_ulid
from services.api.dependencies import get_session
from services.api.event_writer import append_system_event
from services.api.models import (
    Assignment,
    AuditLog,
    Cluster,
    EventRecord,
    Incident,
    MergeCandidate,
    RequestProjection,
    RoadSegment,
    Team,
    User,
)
from services.api.payload_crypto import open_event_payload
from services.api.security import decode_token, require_roles
from services.triage.algorithms import (
    ResourceCluster,
    ResourceTeam,
    haversine_m,
    match_resources,
    road_confidence,
)
from services.triage.tasks import STREAM_KEY

router = APIRouter(prefix="/api/v1", tags=["dashboard"])
SessionDep = Annotated[Session, Depends(get_session)]
Coordinator = Annotated[User, Depends(require_roles("admin", "coordinator"))]
Volunteer = Annotated[User, Depends(require_roles("admin", "coordinator", "volunteer"))]
IncidentReader = Annotated[User, Depends(require_roles("admin", "coordinator", "volunteer", "viewer"))]
ReadRoles = {"admin", "coordinator", "volunteer", "viewer"}
REDIS_URL = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")


class IncidentPatch(BaseModel):
    status: str | None = None
    urgency_override: int | None = Field(default=None, ge=0, le=100)
    reason: str | None = Field(default=None, min_length=3, max_length=1000)

    @model_validator(mode="after")
    def validate_change(self):
        if self.status is None and self.urgency_override is None:
            raise ValueError("At least one incident field must change")
        if self.urgency_override is not None and not self.reason:
            raise ValueError("An urgency override requires a reason")
        if self.status is not None and self.status not in {"received", "assigned", "en_route", "on_site", "rescued", "unreachable", "safe", "closed"}:
            raise ValueError("Unsupported incident status")
        return self


class MergeBody(BaseModel):
    other_incident_id: str = Field(min_length=26, max_length=26)
    reason: str = Field(min_length=3, max_length=1000)


class SplitBody(BaseModel):
    request_ids: list[str] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=1000)


class MergeDecisionBody(BaseModel):
    decision: str
    reason: str = Field(min_length=3, max_length=1000)


class TeamCreate(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    team_type: str = Field(min_length=2, max_length=32)
    capacity: int = Field(ge=1, le=500)
    skills: list[str] = Field(default_factory=list, max_length=30)
    current_latitude: float = Field(ge=-90, le=90)
    current_longitude: float = Field(ge=-180, le=180)
    availability: str = "available"


class TeamPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=120)
    team_type: str | None = Field(default=None, min_length=2, max_length=32)
    capacity: int | None = Field(default=None, ge=1, le=500)
    skills: list[str] | None = Field(default=None, max_length=30)
    current_latitude: float | None = Field(default=None, ge=-90, le=90)
    current_longitude: float | None = Field(default=None, ge=-180, le=180)
    availability: str | None = None


class AssignmentCreate(BaseModel):
    incident_id: str | None = Field(default=None, min_length=26, max_length=26)
    cluster_id: str | None = Field(default=None, min_length=26, max_length=26)
    team_id: str | None = Field(default=None, min_length=26, max_length=26)
    confirm: bool = False

    @model_validator(mode="after")
    def require_target(self):
        if bool(self.incident_id) == bool(self.cluster_id):
            raise ValueError("Choose exactly one incident or cluster")
        return self


class AssignmentPatch(BaseModel):
    status: str


class RoadReportBody(BaseModel):
    geometry: dict[str, Any]
    status: str
    confidence: float = Field(default=0.8, ge=0, le=1)
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def validate_road(self):
        if self.status not in {"open", "flooded", "blocked"}:
            raise ValueError("Road status must be open, flooded or blocked")
        geometry = self.geometry
        if geometry.get("type") != "LineString" or len(geometry.get("coordinates", [])) < 2:
            raise ValueError("Road geometry must be a GeoJSON LineString")
        return self


def _effective_score(incident: Incident) -> int:
    return incident.override_score if incident.override_score is not None else incident.urgency_score


def _incident_data(incident: Incident) -> dict[str, Any]:
    return {
        "incident_id": incident.incident_id,
        "canonical_request_id": incident.canonical_request_id,
        "location": [incident.longitude, incident.latitude] if incident.latitude is not None and incident.longitude is not None else None,
        "h3_res9": incident.h3_res9,
        "merged_request_count": incident.merged_request_count,
        "people_count_max": incident.people_count_max,
        "urgency_score": incident.urgency_score,
        "effective_urgency": _effective_score(incident),
        "urgency_explain": incident.urgency_explain or [],
        "override_reason": incident.override_reason,
        "status": incident.status,
        "cluster_id": incident.cluster_id,
        "categories": incident.categories or [],
        "special_needs": incident.special_needs or [],
        "language": incident.language,
        "text_en": incident.text_en,
        "updated_at": incident.updated_at.isoformat() if incident.updated_at else None,
    }


def _audit(
    session: Session,
    actor: str,
    action: str,
    entity: str,
    entity_id: str,
    before: dict | None,
    after: dict | None,
    reason: str | None = None,
) -> None:
    session.add(
        AuditLog(
            log_id=new_ulid(), actor=actor, action=action, entity=entity, entity_id=entity_id,
            before_data=before, after_data=after, reason=reason,
        )
    )


def _write_request_events(session: Session, rows: list[RequestProjection], event_type: str, payload: dict) -> list[str]:
    return [append_system_event(session, row.request_id, event_type, payload).event_id for row in rows]


def _finish_change(session: Session, event_ids: list[str]) -> None:
    session.commit()
    if not event_ids:
        return
    if os.getenv("REDIS_URL"):
        from services.api.main import enqueue_triage

        enqueue_triage(event_ids)
    else:
        from services.triage.projection import process_event_record

        for event_id in event_ids:
            record = session.get(EventRecord, event_id)
            if record:
                process_event_record(session, record)
        session.commit()


def _decode_cursor(value: str) -> tuple[datetime, str]:
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode()
        stamp, incident_id = raw.split("|", 1)
        return datetime.fromisoformat(stamp), incident_id
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid pagination cursor") from exc


def _encode_cursor(incident: Incident) -> str:
    raw = f"{incident.updated_at.isoformat()}|{incident.incident_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


@router.get("/incidents")
def list_incidents(
    session: SessionDep,
    _user: IncidentReader,
    bbox: str | None = None,
    status: str | None = None,
    urgency_min: int = Query(ge=0, le=100, default=0),
    urgency_max: int = Query(ge=0, le=100, default=100),
    category: str | None = None,
    special_need: str | None = None,
    language: str | None = None,
    updated_since: datetime | None = None,
    q: str | None = Query(default=None, max_length=120),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
) -> dict[str, Any]:
    query = select(Incident).where(Incident.merged_into.is_(None))
    effective = func.coalesce(Incident.override_score, Incident.urgency_score)
    query = query.where(effective.between(urgency_min, urgency_max))
    if status:
        query = query.where(Incident.status == status)
    if language:
        query = query.where(Incident.language == language)
    if category:
        query = query.where(cast(Incident.categories, String).contains(category))
    if special_need:
        query = query.where(cast(Incident.special_needs, String).contains(special_need))
    if updated_since:
        query = query.where(Incident.updated_at >= updated_since)
    if q:
        query = query.where(func.lower(Incident.text_en).contains(q.casefold()))
    if bbox:
        try:
            west, south, east, north = (float(part) for part in bbox.split(","))
            if not (-180 <= west <= 180 and -180 <= east <= 180 and -90 <= south <= north <= 90):
                raise ValueError
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="bbox must be west,south,east,north") from exc
        query = query.where(Incident.longitude.between(west, east), Incident.latitude.between(south, north))
    if cursor:
        stamp, incident_id = _decode_cursor(cursor)
        query = query.where(or_(Incident.updated_at < stamp, and_(Incident.updated_at == stamp, Incident.incident_id < incident_id)))
    query = query.order_by(Incident.updated_at.desc(), Incident.incident_id.desc()).limit(limit + 1)
    rows = session.scalars(query).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    return {"items": [_incident_data(item) for item in page], "next_cursor": _encode_cursor(page[-1]) if has_more and page else None}


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str, session: SessionDep, _user: IncidentReader) -> dict[str, Any]:
    incident = session.get(Incident, incident_id)
    if incident is None or incident.merged_into:
        raise HTTPException(status_code=404, detail="Incident not found")
    requests = session.scalars(
        select(RequestProjection).where(RequestProjection.incident_id == incident_id).order_by(RequestProjection.created_hlc)
    ).all()
    request_ids = [row.request_id for row in requests]
    events = session.scalars(
        select(EventRecord).where(EventRecord.request_id.in_(request_ids)).order_by(EventRecord.hlc)
    ).all() if request_ids else []
    audit = session.scalars(
        select(AuditLog).where(AuditLog.entity == "incident", AuditLog.entity_id == incident_id).order_by(AuditLog.at)
    ).all()
    candidates = session.scalars(
        select(MergeCandidate).where(or_(MergeCandidate.request_a.in_(request_ids), MergeCandidate.request_b.in_(request_ids)))
    ).all() if request_ids else []
    return {
        **_incident_data(incident),
        "requests": [
            {
                "request_id": row.request_id, "device_id": row.device_id, "people_count": row.people_count,
                "categories": row.categories or [], "special_needs": row.special_needs or [],
                "text_original": row.text_original, "text_en": row.text_en, "language": row.language,
                "location": [row.longitude, row.latitude] if row.latitude is not None and row.longitude is not None else None,
                "accuracy_m": row.accuracy_m, "location_source": row.location_source, "status": row.status,
                "created_at": row.created_at.isoformat(),
            }
            for row in requests
        ],
        "timeline": [
            {"event_id": event.event_id, "type": event.event_type, "hlc": event.hlc,
             "payload": open_event_payload(json.loads(event.payload))}
            for event in events
        ],
        "merge_candidates": [
            {"pair_id": item.pair_id, "request_a": item.request_a, "request_b": item.request_b, "score": item.score,
             "features": item.features, "decision": item.decision, "reviewed_by": item.reviewed_by}
            for item in candidates
        ],
        "audit_log": [
            {"actor": item.actor, "action": item.action, "before": item.before_data, "after": item.after_data,
             "reason": item.reason, "at": item.at.isoformat()}
            for item in audit
        ],
    }


@router.patch("/incidents/{incident_id}")
def update_incident(incident_id: str, body: IncidentPatch, session: SessionDep, user: Coordinator) -> dict[str, Any]:
    incident = session.get(Incident, incident_id)
    if incident is None or incident.merged_into:
        raise HTTPException(status_code=404, detail="Incident not found")
    before = _incident_data(incident)
    event_payload: dict[str, Any] = {"actor": user.user_id}
    if body.status is not None:
        incident.status = body.status
        event_payload["status"] = body.status
    if body.urgency_override is not None:
        incident.override_score = body.urgency_override
        incident.override_reason = body.reason
        event_payload.update(urgency_override=body.urgency_override, reason=body.reason)
    incident.updated_at = datetime.now(UTC)
    after = _incident_data(incident)
    _audit(session, user.user_id, "incident.updated", "incident", incident_id, before, after, body.reason)
    rows = session.scalars(select(RequestProjection).where(RequestProjection.incident_id == incident_id)).all()
    if not rows and incident.canonical_request_id:
        row = session.get(RequestProjection, incident.canonical_request_id)
        rows = [row] if row else []
    event_ids = _write_request_events(session, rows, "status.changed", event_payload)
    _finish_change(session, event_ids)
    return _incident_data(incident)


def _merge_incident_rows(session: Session, target: Incident, source: Incident) -> None:
    session.execute(
        update(RequestProjection).where(RequestProjection.incident_id == source.incident_id)
        .values(incident_id=target.incident_id)
    )
    source.merged_into = target.incident_id
    source.status = "merged"
    target.merged_request_count += source.merged_request_count
    target.people_count_max = max(target.people_count_max, source.people_count_max)
    target.categories = sorted(set(target.categories or []) | set(source.categories or []))
    target.special_needs = sorted(set(target.special_needs or []) | set(source.special_needs or []))
    if source.urgency_score > target.urgency_score:
        target.urgency_score = source.urgency_score
        target.urgency_explain = source.urgency_explain
    target.updated_at = datetime.now(UTC)


@router.post("/incidents/{incident_id}/merge")
def merge_incidents(incident_id: str, body: MergeBody, session: SessionDep, user: Coordinator) -> dict[str, Any]:
    target = session.get(Incident, incident_id)
    source = session.get(Incident, body.other_incident_id)
    if target is None or source is None or target.incident_id == source.incident_id or source.merged_into:
        raise HTTPException(status_code=404, detail="Merge incident not found")
    before = {"target": _incident_data(target), "source": _incident_data(source)}
    if (source.canonical_request_id, source.incident_id) < (target.canonical_request_id, target.incident_id):
        target, source = source, target
    _merge_incident_rows(session, target, source)
    rows = session.scalars(select(RequestProjection).where(RequestProjection.incident_id == target.incident_id)).all()
    event_ids = _write_request_events(session, rows, "sos.updated", {"incident_id": target.incident_id, "actor": user.user_id, "reason": body.reason})
    _audit(session, user.user_id, "incident.merged", "incident", target.incident_id, before,
           {"target": _incident_data(target), "merged_incident_id": source.incident_id}, body.reason)
    _finish_change(session, event_ids)
    return _incident_data(target)


@router.post("/incidents/{incident_id}/split")
def split_incident(incident_id: str, body: SplitBody, session: SessionDep, user: Coordinator) -> dict[str, Any]:
    incident = session.get(Incident, incident_id)
    if incident is None or incident.merged_into:
        raise HTTPException(status_code=404, detail="Incident not found")
    rows = session.scalars(select(RequestProjection).where(RequestProjection.incident_id == incident_id)).all()
    selected = [row for row in rows if row.request_id in set(body.request_ids)]
    if len(selected) != len(set(body.request_ids)) or not selected or len(selected) >= len(rows):
        raise HTTPException(status_code=400, detail="Split requires a proper subset of this incident's requests")
    before = _incident_data(incident)
    split_incident = Incident(
        incident_id=new_ulid(), canonical_request_id=selected[0].request_id,
        latitude=selected[0].latitude, longitude=selected[0].longitude,
        h3_res9=h3.cell_to_parent(selected[0].h3_res10, 9) if selected[0].h3_res10 else None,
        merged_request_count=len(selected), people_count_max=max(row.people_count for row in selected),
        urgency_score=incident.urgency_score, urgency_explain=incident.urgency_explain,
        status=incident.status, categories=incident.categories, special_needs=incident.special_needs,
        language=selected[0].language, text_en=selected[0].text_en,
    )
    session.add(split_incident)
    session.flush()
    for row in selected:
        row.incident_id = split_incident.incident_id
    after = {"remaining": _incident_data(incident), "split": _incident_data(split_incident)}
    event_ids = _write_request_events(session, selected, "sos.updated", {"incident_id": split_incident.incident_id, "actor": user.user_id, "reason": body.reason})
    _audit(session, user.user_id, "incident.split", "incident", incident_id, before, after, body.reason)
    _finish_change(session, event_ids)
    return {"remaining": _incident_data(incident), "split": _incident_data(split_incident)}


@router.get("/clusters")
def list_clusters(session: SessionDep, _user: IncidentReader) -> list[dict[str, Any]]:
    return [
        {"cluster_id": item.cluster_id, "centroid": [item.centroid_longitude, item.centroid_latitude],
         "hull": item.hull_geojson, "incident_count": item.incident_count, "urgency_max": item.urgency_max,
         "updated_at": item.updated_at.isoformat()}
        for item in session.scalars(select(Cluster).order_by(Cluster.urgency_max.desc())).all()
    ]


@router.get("/merge-candidates")
def merge_candidates(
    session: SessionDep,
    _user: Coordinator,
    decision: str = "needs_review",
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict[str, Any]]:
    rows = session.scalars(
        select(MergeCandidate).where(MergeCandidate.decision == decision).order_by(MergeCandidate.score.desc()).limit(limit)
    ).all()
    return [{"pair_id": item.pair_id, "request_a": item.request_a, "request_b": item.request_b,
             "score": item.score, "features": item.features, "decision": item.decision}
            for item in rows]


@router.post("/merge-candidates/{pair_id}/decision")
def decide_merge_candidate(pair_id: str, body: MergeDecisionBody, session: SessionDep, user: Coordinator) -> dict[str, str]:
    if body.decision not in {"accepted", "rejected"}:
        raise HTTPException(status_code=400, detail="Decision must be accepted or rejected")
    candidate = session.get(MergeCandidate, pair_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Merge candidate not found")
    if candidate.decision != "needs_review":
        raise HTTPException(status_code=409, detail="Candidate is no longer awaiting review")
    before = {"decision": candidate.decision}
    candidate.decision = "manual_merged" if body.decision == "accepted" else "rejected"
    candidate.reviewed_by = user.user_id
    candidate.reviewed_at = datetime.now(UTC)
    if body.decision == "accepted":
        left = session.get(RequestProjection, candidate.request_a)
        right = session.get(RequestProjection, candidate.request_b)
        if left is None or right is None:
            raise HTTPException(status_code=409, detail="Candidate requests are no longer available")
        target = session.get(Incident, left.incident_id) if left.incident_id else None
        source = session.get(Incident, right.incident_id) if right.incident_id else None
        if target and source and target.incident_id != source.incident_id:
            _merge_incident_rows(session, target, source)
        elif target and not source:
            right.incident_id = target.incident_id
        elif source and not target:
            left.incident_id = source.incident_id
    _audit(session, user.user_id, "merge_candidate.decided", "merge_candidate", pair_id,
           before, {"decision": candidate.decision}, body.reason)
    affected = [session.get(RequestProjection, request_id) for request_id in (candidate.request_a, candidate.request_b)]
    event_ids = _write_request_events(session, [row for row in affected if row], "sos.updated", {
        "merge_decision": candidate.decision, "actor": user.user_id, "reason": body.reason,
    })
    _finish_change(session, event_ids)
    return {"pair_id": pair_id, "decision": candidate.decision}


@router.get("/teams")
def list_teams(session: SessionDep, _user: IncidentReader) -> list[dict[str, Any]]:
    return [_team_data(item) for item in session.scalars(select(Team).order_by(Team.name)).all()]


def _team_data(team: Team) -> dict[str, Any]:
    return {"team_id": team.team_id, "name": team.name, "team_type": team.team_type,
            "capacity": team.capacity, "skills": team.skills or [], "location": [team.current_longitude, team.current_latitude],
            "availability": team.availability, "updated_at": team.updated_at.isoformat() if team.updated_at else None}


@router.post("/teams", status_code=201)
def create_team(body: TeamCreate, session: SessionDep, user: Coordinator) -> dict[str, Any]:
    if body.availability not in {"available", "unavailable", "busy"}:
        raise HTTPException(status_code=400, detail="Unsupported availability")
    team = Team(team_id=new_ulid(), **body.model_dump())
    session.add(team)
    session.flush()
    _audit(session, user.user_id, "team.created", "team", team.team_id, None, _team_data(team))
    session.commit()
    return _team_data(team)


@router.patch("/teams/{team_id}")
def update_team(team_id: str, body: TeamPatch, session: SessionDep, user: Coordinator) -> dict[str, Any]:
    team = session.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    values = body.model_dump(exclude_unset=True)
    if values.get("availability") not in {None, "available", "unavailable", "busy"}:
        raise HTTPException(status_code=400, detail="Unsupported availability")
    before = _team_data(team)
    for key, value in values.items():
        if value is not None:
            setattr(team, key, value)
    after = _team_data(team)
    _audit(session, user.user_id, "team.updated", "team", team_id, before, after)
    session.commit()
    return after


@router.post("/assignments", status_code=201)
def create_assignment(body: AssignmentCreate, session: SessionDep, user: Coordinator) -> dict[str, Any]:
    if body.incident_id:
        incident = session.get(Incident, body.incident_id)
        if incident is None:
            raise HTTPException(status_code=404, detail="Incident not found")
        clusters = [ResourceCluster(incident.incident_id, incident.latitude or 0, incident.longitude or 0,
                                    _effective_score(incident), incident.people_count_max,
                                    medical="medical" in (incident.categories or []))]
    else:
        cluster = session.get(Cluster, body.cluster_id)
        if cluster is None:
            raise HTTPException(status_code=404, detail="Cluster not found")
        incident_rows = session.scalars(select(Incident).where(Incident.cluster_id == cluster.cluster_id)).all()
        clusters = [ResourceCluster(cluster.cluster_id, cluster.centroid_latitude, cluster.centroid_longitude,
                                    cluster.urgency_max, max((row.people_count_max for row in incident_rows), default=1),
                                    medical=any("medical" in (row.categories or []) for row in incident_rows))]
    teams = session.scalars(select(Team).where(Team.availability == "available")).all()
    team_signals = [ResourceTeam(item.team_id, item.current_latitude, item.current_longitude, item.capacity,
                                 frozenset(item.skills or []), True) for item in teams]
    suggestions = match_resources(clusters, team_signals)
    suggested = next((team_id for _, team_id, _ in suggestions), None)
    team_id = body.team_id or suggested
    if not team_id:
        raise HTTPException(status_code=409, detail="No available team can be suggested")
    team = session.get(Team, team_id)
    if team is None or team.availability != "available":
        raise HTTPException(status_code=409, detail="Selected team is not available")
    cluster_signal = clusters[0]
    distance = haversine_m(cluster_signal.latitude, cluster_signal.longitude, team.current_latitude, team.current_longitude)
    eta = int(distance / 8.0)
    suggestion = {"team_id": team_id, "eta_s": eta, "warning": "Routing service unavailable; straight-line estimate may cross blocked roads."}
    if not body.confirm:
        return {"suggestion": suggestion, "requires_confirmation": True}
    assignment = Assignment(
        assignment_id=new_ulid(), cluster_id=body.cluster_id, incident_id=body.incident_id,
        team_id=team_id, status="assigned", eta_s=eta, route_geojson={"type": "LineString", "coordinates": [
            [team.current_longitude, team.current_latitude], [cluster_signal.longitude, cluster_signal.latitude]
        ]}, created_by=user.user_id,
    )
    session.add(assignment)
    team.availability = "busy"
    if body.incident_id:
        incident.status = "assigned"
    else:
        for item in incident_rows:
            item.status = "assigned"
    _audit(session, user.user_id, "assignment.created", "assignment", assignment.assignment_id, None,
           {"team_id": team_id, "cluster_id": body.cluster_id, "incident_id": body.incident_id, "eta_s": eta})
    event_ids = []
    targets = [incident] if body.incident_id else incident_rows
    for target in targets:
        rows = session.scalars(select(RequestProjection).where(RequestProjection.incident_id == target.incident_id)).all()
        event_ids.extend(_write_request_events(session, rows, "status.changed", {"status": "assigned", "actor": user.user_id}))
    _finish_change(session, event_ids)
    return {"assignment_id": assignment.assignment_id, "team_id": team_id, "status": assignment.status,
            "eta_s": eta, "route": assignment.route_geojson, "warning": suggestion["warning"]}


@router.patch("/assignments/{assignment_id}")
def update_assignment(assignment_id: str, body: AssignmentPatch, session: SessionDep, user: Volunteer) -> dict[str, Any]:
    assignment = session.get(Assignment, assignment_id)
    if assignment is None:
        raise HTTPException(status_code=404, detail="Assignment not found")
    sequence = ["assigned", "en_route", "on_site", "rescued", "unreachable"]
    if body.status not in sequence:
        raise HTTPException(status_code=400, detail="Unsupported assignment status")
    if user.role == "volunteer" and user.team_id != assignment.team_id:
        raise HTTPException(status_code=403, detail="Volunteer is not assigned to this team")
    if body.status != "unreachable" and sequence.index(body.status) < sequence.index(assignment.status):
        raise HTTPException(status_code=409, detail="Assignment status cannot move backwards")
    before = {"status": assignment.status}
    assignment.status = body.status
    after = {"status": assignment.status}
    _audit(session, user.user_id, "assignment.status_changed", "assignment", assignment_id, before, after)
    rows = []
    if assignment.incident_id:
        incident = session.get(Incident, assignment.incident_id)
        if incident:
            incident.status = body.status
            rows = session.scalars(select(RequestProjection).where(RequestProjection.incident_id == incident.incident_id)).all()
    elif assignment.cluster_id:
        for incident in session.scalars(select(Incident).where(Incident.cluster_id == assignment.cluster_id)).all():
            incident.status = body.status
            rows.extend(session.scalars(select(RequestProjection).where(RequestProjection.incident_id == incident.incident_id)).all())
    event_ids = _write_request_events(session, rows, "status.changed", {"status": body.status, "actor": user.user_id})
    _finish_change(session, event_ids)
    return {"assignment_id": assignment.assignment_id, "status": assignment.status}


@router.get("/assignments/mine")
def my_assignments(session: SessionDep, user: Volunteer) -> list[dict[str, Any]]:
    if user.role == "volunteer" and not user.team_id:
        raise HTTPException(status_code=403, detail="Volunteer account has no assigned team")
    query = select(Assignment).order_by(Assignment.created_at.desc())
    if user.role == "volunteer":
        query = query.where(Assignment.team_id == user.team_id)
    result = []
    for assignment in session.scalars(query).all():
        incident = session.get(Incident, assignment.incident_id) if assignment.incident_id else None
        cluster = session.get(Cluster, assignment.cluster_id) if assignment.cluster_id else None
        result.append({
            "assignment_id": assignment.assignment_id,
            "team_id": assignment.team_id,
            "incident_id": assignment.incident_id,
            "cluster_id": assignment.cluster_id,
            "status": assignment.status,
            "eta_s": assignment.eta_s,
            "route": assignment.route_geojson,
            "location": ([incident.longitude, incident.latitude] if incident and incident.latitude is not None and incident.longitude is not None
                         else [cluster.centroid_longitude, cluster.centroid_latitude] if cluster else None),
            "urgency": _effective_score(incident) if incident else cluster.urgency_max if cluster else 0,
            "people_count": incident.people_count_max if incident else None,
            "categories": incident.categories if incident else [],
            "special_needs": incident.special_needs if incident else [],
        })
    return result


@router.get("/routes")
def route_preview(
    _user: IncidentReader,
    session: SessionDep,
    from_point: str = Query(alias="from"),
    to_point: str = Query(alias="to"),
    avoid_flooded: bool = True,
) -> dict[str, Any]:
    try:
        from_lat, from_lon = (float(value) for value in from_point.split(","))
        to_lat, to_lon = (float(value) for value in to_point.split(","))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Coordinates must be latitude,longitude") from exc
    if not (-90 <= from_lat <= 90 and -90 <= to_lat <= 90 and -180 <= from_lon <= 180 and -180 <= to_lon <= 180):
        raise HTTPException(status_code=400, detail="Coordinates are out of range")
    roads = session.scalars(select(RoadSegment)).all() if session else []
    warnings = ["Routing service unavailable; straight-line estimate may cross blocked roads."]
    if avoid_flooded and any(item.status in {"flooded", "blocked"} for item in roads):
        warnings.append("Road reports exist, but no routing engine is configured to avoid them.")
    distance = haversine_m(from_lat, from_lon, to_lat, to_lon)
    return {"route": {"type": "LineString", "coordinates": [[from_lon, from_lat], [to_lon, to_lat]]},
            "distance_m": round(distance), "eta_s": round(distance / 8), "warning": warnings}


@router.post("/roads/report", status_code=201)
def report_road(body: RoadReportBody, session: SessionDep, user: Volunteer) -> dict[str, Any]:
    now = datetime.now(UTC)
    segment = RoadSegment(segment_id=new_ulid(), geometry_geojson=body.geometry, status=body.status,
                          confidence=body.confidence, reported_by=user.user_id, reported_at=now, expires_at=body.expires_at)
    session.add(segment)
    _audit(session, user.user_id, "road.reported", "road_segment", segment.segment_id, None,
           {"status": segment.status, "confidence": segment.confidence})
    session.commit()
    return {"segment_id": segment.segment_id, "status": segment.status,
            "confidence": segment.confidence, "effective_confidence": _current_road_confidence(segment, now)}


@router.get("/roads")
def list_roads(session: SessionDep, _user: IncidentReader) -> list[dict[str, Any]]:
    now = datetime.now(UTC)
    roads = session.scalars(select(RoadSegment).order_by(RoadSegment.reported_at.desc())).all()
    return [{"segment_id": road.segment_id, "geometry": road.geometry_geojson, "status": road.status,
             "confidence": road.confidence, "effective_confidence": _current_road_confidence(road, now),
             "reported_at": road.reported_at.isoformat(),
             "expired": bool(road.expires_at and road.expires_at <= now)} for road in roads]


def _current_road_confidence(road: RoadSegment, now: datetime) -> float:
    reported_at = road.reported_at
    if reported_at.tzinfo is None:
        reported_at = reported_at.replace(tzinfo=UTC)
    return road_confidence(road.confidence, reported_at, now)


@router.get("/export/incidents.csv")
def export_incidents_csv(session: SessionDep, _user: Coordinator) -> Any:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(["incident_id", "latitude", "longitude", "urgency", "status", "people_count_max", "categories", "special_needs", "text_en"])
    for incident in session.scalars(select(Incident).where(Incident.merged_into.is_(None)).order_by(Incident.urgency_score.desc())).all():
        values = [_incident_data(incident)["incident_id"], incident.latitude, incident.longitude, _effective_score(incident),
                  incident.status, incident.people_count_max, ",".join(incident.categories or []),
                  ",".join(incident.special_needs or []), incident.text_en]
        writer.writerow([f"'{value}" if isinstance(value, str) and value[:1] in "=+-@" else value for value in values])
    from fastapi.responses import StreamingResponse

    return StreamingResponse(iter([output.getvalue()]), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=lifeline-incidents.csv"})


@router.get("/export/incidents.geojson")
def export_incidents_geojson(session: SessionDep, _user: Coordinator) -> dict[str, Any]:
    features = []
    for incident in session.scalars(select(Incident).where(Incident.merged_into.is_(None))).all():
        if incident.latitude is None or incident.longitude is None:
            continue
        features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [incident.longitude, incident.latitude]},
                         "properties": _incident_data(incident)})
    return {"type": "FeatureCollection", "features": features}


@router.get("/audit")
def get_audit_log(
    session: SessionDep,
    _user: Annotated[User, Depends(require_roles("admin"))],
    limit: int = Query(default=100, ge=1, le=500),
) -> list[dict[str, Any]]:
    rows = session.scalars(select(AuditLog).order_by(AuditLog.at.desc()).limit(limit)).all()
    return [{"log_id": row.log_id, "actor": row.actor, "action": row.action, "entity": row.entity,
             "entity_id": row.entity_id, "before": row.before_data, "after": row.after_data,
             "reason": row.reason, "at": row.at.isoformat()} for row in rows]


@router.websocket("/ws/dashboard")
async def dashboard_stream(websocket: WebSocket, token: str, after_seq: str = "0-0", bbox: str | None = None):
    if not re.fullmatch(r"\d+-\d+", after_seq):
        await websocket.close(code=4400)
        return
    try:
        claims = decode_token(token, "access")
        if claims["role"] not in ReadRoles:
            await websocket.close(code=4403)
            return
        from services.api.db import SessionLocal

        with SessionLocal() as session:
            user = session.get(User, claims["sub"])
            if user is None or not user.active:
                await websocket.close(code=4401)
                return
    except HTTPException:
        await websocket.close(code=4401)
        return
    bounds = None
    if bbox:
        try:
            bounds = tuple(float(value) for value in bbox.split(","))
            if len(bounds) != 4:
                raise ValueError
        except ValueError:
            await websocket.close(code=4400)
            return
    await websocket.accept()
    client = async_redis.Redis.from_url(REDIS_URL, decode_responses=True)
    cursor = after_seq
    try:
        while True:
            streams = await client.xread({STREAM_KEY: cursor}, block=1000, count=100)
            for _, events in streams:
                for stream_id, fields in events:
                    cursor = stream_id
                    payload = json.loads(fields["data"])
                    longitude, latitude = payload.get("longitude"), payload.get("latitude")
                    if bounds and longitude is not None and latitude is not None:
                        west, south, east, north = bounds
                        if not (west <= longitude <= east and south <= latitude <= north):
                            continue
                    await websocket.send_json({**payload, "seq": stream_id})
            await asyncio.sleep(0)
    except WebSocketDisconnect:
        pass
    finally:
        await client.aclose()
