from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from services.api.db import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class EventRecord(Base):
    __tablename__ = "events"
    event_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    hlc: Mapped[str] = mapped_column(String(80), index=True)
    event_type: Mapped[str] = mapped_column("type", String(64))
    request_id: Mapped[str] = mapped_column(String(26), index=True)
    payload: Mapped[str] = mapped_column(Text)
    hops: Mapped[int] = mapped_column(Integer, default=0)
    signature: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    source: Mapped[str] = mapped_column(String(16), default="https")


class RequestProjection(Base):
    __tablename__ = "requests"
    request_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(128), index=True)
    created_hlc: Mapped[str] = mapped_column(String(80), index=True)
    last_event_hlc: Mapped[str] = mapped_column(String(80), index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    h3_res10: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    location_source: Mapped[str] = mapped_column(String(16), default="unavailable")
    people_count: Mapped[int] = mapped_column(Integer, default=1)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    special_needs: Mapped[list[str]] = mapped_column(JSON, default=list)
    text_original: Mapped[str] = mapped_column(Text, default="")
    text_en: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(8), default="und")
    contact_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    media_perceptual_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    water_level: Mapped[str | None] = mapped_column(String(16), nullable=True)
    pre_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    battery_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    incident_id: Mapped[str | None] = mapped_column(String(26), index=True, nullable=True)
    urgency_override: Mapped[int | None] = mapped_column(Integer, nullable=True)
    urgency_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_contact_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


Index(
    "idx_requests_live_status",
    RequestProjection.status,
    postgresql_where=RequestProjection.status.not_in(["rescued", "closed"]),
)


class Incident(Base):
    __tablename__ = "incidents"
    incident_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    canonical_request_id: Mapped[str] = mapped_column(String(26), index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    h3_res9: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)
    merged_request_count: Mapped[int] = mapped_column(Integer, default=1)
    people_count_max: Mapped[int] = mapped_column(Integer, default=1)
    urgency_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    urgency_explain: Mapped[list[dict]] = mapped_column(JSON, default=list)
    override_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(24), default="received", index=True)
    cluster_id: Mapped[str | None] = mapped_column(String(26), index=True, nullable=True)
    merged_into: Mapped[str | None] = mapped_column(String(26), nullable=True)
    categories: Mapped[list[str]] = mapped_column(JSON, default=list)
    special_needs: Mapped[list[str]] = mapped_column(JSON, default=list)
    language: Mapped[str] = mapped_column(String(8), default="und")
    text_en: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now, index=True)


Index("idx_incidents_priority", Incident.urgency_score.desc(), Incident.updated_at.desc())


class Cluster(Base):
    __tablename__ = "clusters"
    cluster_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    centroid_latitude: Mapped[float] = mapped_column(Float)
    centroid_longitude: Mapped[float] = mapped_column(Float)
    hull_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    incident_count: Mapped[int] = mapped_column(Integer, default=0)
    urgency_max: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class MergeCandidate(Base):
    __tablename__ = "merge_candidates"
    pair_id: Mapped[str] = mapped_column(String(53), primary_key=True)
    request_a: Mapped[str] = mapped_column(String(26), index=True)
    request_b: Mapped[str] = mapped_column(String(26), index=True)
    score: Mapped[float] = mapped_column(Float)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    decision: Mapped[str] = mapped_column(String(24), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("request_a", "request_b", name="uq_merge_pair"),)


class Team(Base):
    __tablename__ = "teams"
    team_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    team_type: Mapped[str] = mapped_column(String(32))
    capacity: Mapped[int] = mapped_column(Integer, default=1)
    skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    current_latitude: Mapped[float] = mapped_column(Float)
    current_longitude: Mapped[float] = mapped_column(Float)
    availability: Mapped[str] = mapped_column(String(24), default="available", index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class Assignment(Base):
    __tablename__ = "assignments"
    assignment_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    cluster_id: Mapped[str | None] = mapped_column(String(26), index=True, nullable=True)
    incident_id: Mapped[str | None] = mapped_column(String(26), index=True, nullable=True)
    team_id: Mapped[str] = mapped_column(String(26), index=True)
    status: Mapped[str] = mapped_column(String(24), default="assigned", index=True)
    eta_s: Mapped[int | None] = mapped_column(Integer, nullable=True)
    route_geojson: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RoadSegment(Base):
    __tablename__ = "road_segments"
    segment_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    geometry_geojson: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24), index=True)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    reported_by: Mapped[str] = mapped_column(String(64))
    reported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class User(Base):
    __tablename__ = "users"
    user_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    role: Mapped[str] = mapped_column(String(24), index=True)
    team_id: Mapped[str | None] = mapped_column(String(26), nullable=True, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(26), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuditLog(Base):
    __tablename__ = "audit_log"
    log_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    actor: Mapped[str] = mapped_column(String(64), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(64), index=True)
    entity_id: Mapped[str] = mapped_column(String(64), index=True)
    before_data: Mapped[dict | None] = mapped_column("before", JSON, nullable=True)
    after_data: Mapped[dict | None] = mapped_column("after", JSON, nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, index=True)


class RiskCell(Base):
    __tablename__ = "risk_cells"
    cell_id: Mapped[str] = mapped_column(String(20), primary_key=True)
    risk_index: Mapped[int] = mapped_column(Integer, index=True)
    factors: Mapped[dict] = mapped_column(JSON, default=dict)
    geometry_geojson: Mapped[dict] = mapped_column(JSON)
    source: Mapped[str] = mapped_column(String(120), default="synthetic")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class HouseholdRegistration(Base):
    __tablename__ = "household_registrations"
    registration_id: Mapped[str] = mapped_column(String(26), primary_key=True)
    h3_cell: Mapped[str] = mapped_column(String(20), index=True)
    encrypted_payload: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
