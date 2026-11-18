import json
import os
from datetime import UTC, datetime, timedelta
from typing import Annotated

import h3
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from packages.protocol.python.lifeline_protocol import new_ulid
from services.api.dependencies import get_session
from services.api.models import AuditLog, HouseholdRegistration, RiskCell, User
from services.api.privacy import decrypt_registration, encrypt_registration
from services.api.security import require_roles

router = APIRouter(prefix="/api/v1", tags=["risk and preparedness"])
SessionDep = Annotated[Session, Depends(get_session)]
Coordinator = Annotated[User, Depends(require_roles("admin", "coordinator"))]
IncidentReader = Annotated[User, Depends(require_roles("admin", "coordinator", "volunteer", "viewer"))]


class HouseholdRegistrationBody(BaseModel):
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    household_size: int = Field(ge=1, le=30)
    vulnerability_tags: list[str] = Field(default_factory=list, max_length=12)
    contact_name: str = Field(min_length=1, max_length=120)
    contact_phone: str = Field(min_length=5, max_length=32)
    consent: bool


class RiskLayerImport(BaseModel):
    source: str = Field(min_length=3, max_length=120)
    features: list[dict] = Field(min_length=1, max_length=10000)


def risk_index(factors: dict[str, float]) -> int:
    """Risk score weights exposure 40%, density 20%, vulnerability 25%, access 15%."""
    weights = {"hazard_exposure": 0.40, "population_density": 0.20,
               "vulnerable_households": 0.25, "access_difficulty": 0.15}
    return round(sum(weights[key] * max(0, min(100, float(factors.get(key, 0)))) for key in weights))


def purge_expired_households(session: Session) -> int:
    result = session.execute(delete(HouseholdRegistration).where(
        HouseholdRegistration.expires_at <= datetime.now(UTC)
    ), execution_options={"synchronize_session": False})
    session.commit()
    return result.rowcount or 0


def seed_demo_risk_cells(session: Session) -> None:
    if os.getenv("DEMO_MODE", "false").casefold() != "true":
        return
    if session.scalar(select(func.count()).select_from(RiskCell)):
        return
    samples = [(10.0, 76.0, 82, 70, 85, 75), (10.02, 76.02, 65, 55, 45, 60), (9.98, 76.03, 40, 80, 55, 35)]
    for latitude, longitude, exposure, density, vulnerable, access in samples:
        cell = h3.latlng_to_cell(latitude, longitude, 8)
        factors = {"hazard_exposure": exposure, "population_density": density,
                   "vulnerable_households": vulnerable, "access_difficulty": access}
        boundary = h3.cell_to_boundary(cell)
        ring = [[lon, lat] for lat, lon in boundary]
        ring.append(ring[0])
        session.add(RiskCell(cell_id=cell, risk_index=risk_index(factors), factors=factors,
                             geometry_geojson={"type": "Polygon", "coordinates": [ring]}, source="synthetic demo layer"))
    session.commit()


@router.get("/risk/cells")
def get_risk_cells(session: SessionDep, _user: IncidentReader) -> dict:
    seed_demo_risk_cells(session)
    cells = session.scalars(select(RiskCell).order_by(RiskCell.risk_index.desc())).all()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": row.geometry_geojson,
         "properties": {"cell_id": row.cell_id, "risk_index": row.risk_index,
                        "factors": row.factors, "source": row.source,
                        "updated_at": row.updated_at.isoformat()}}
        for row in cells
    ]}


@router.put("/risk/cells/import")
def import_risk_layer(body: RiskLayerImport, session: SessionDep,
                      _user: Annotated[User, Depends(require_roles("admin"))]) -> dict[str, int]:
    imported = 0
    for feature in body.features:
        properties = feature.get("properties") or {}
        cell_id = str(properties.get("cell_id", ""))
        geometry = feature.get("geometry")
        if not h3.is_valid_cell(cell_id) or h3.get_resolution(cell_id) != 8:
            raise HTTPException(status_code=422, detail="Each risk cell must use a valid H3 resolution 8 ID")
        if not geometry or geometry.get("type") != "Polygon" or not geometry.get("coordinates"):
            raise HTTPException(status_code=422, detail="Each risk cell requires polygon geometry")
        factors = properties.get("factors") or {}
        row = RiskCell(cell_id=cell_id, risk_index=risk_index(factors), factors=factors,
                       geometry_geojson=geometry, source=body.source)
        session.merge(row)
        imported += 1
    session.commit()
    return {"imported": imported}


@router.post("/households/register", status_code=201)
def register_household(body: HouseholdRegistrationBody, session: SessionDep, user: Coordinator) -> dict[str, str]:
    if not body.consent:
        raise HTTPException(status_code=400, detail="Explicit consent is required")
    purge_expired_households(session)
    cell = h3.latlng_to_cell(body.latitude, body.longitude, 8)
    payload = body.model_dump(exclude={"latitude", "longitude", "consent"})
    encrypted = encrypt_registration(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode())
    registration = HouseholdRegistration(registration_id=new_ulid(), h3_cell=cell,
                                         encrypted_payload=encrypted,
                                         registrar_id=user.user_id, consent_at=datetime.now(UTC),
                                         expires_at=datetime.now(UTC) + timedelta(days=365))
    session.add(registration)
    session.commit()
    return {"registration_id": registration.registration_id, "cell_id": cell,
            "status": "encrypted", "expires_at": registration.expires_at.isoformat()}


@router.get("/households/{registration_id}/export")
def export_household(registration_id: str, session: SessionDep, user: Coordinator) -> dict:
    registration = session.get(HouseholdRegistration, registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="Household registration not found")
    try:
        payload = json.loads(decrypt_registration(registration.encrypted_payload))
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    session.add(AuditLog(log_id=new_ulid(), actor=user.user_id, action="household.exported",
                         entity="household_registration", entity_id=registration_id,
                         after_data={"fields": sorted(payload.keys())}))
    session.commit()
    return {"registration_id": registration.registration_id, "cell_id": registration.h3_cell,
            "created_at": registration.created_at.isoformat(), "consent_at": registration.consent_at.isoformat(),
            "expires_at": registration.expires_at.isoformat(), "data": payload}


@router.delete("/households/{registration_id}", status_code=204)
def delete_household(registration_id: str, session: SessionDep, user: Coordinator) -> None:
    registration = session.get(HouseholdRegistration, registration_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="Household registration not found")
    cell = registration.h3_cell
    session.delete(registration)
    session.add(AuditLog(log_id=new_ulid(), actor=user.user_id, action="household.deleted",
                         entity="household_registration", entity_id=registration_id,
                         before_data={"cell_id": cell}))
    session.commit()


@router.get("/households/summary")
def household_summary(session: SessionDep, _user: Coordinator) -> list[dict[str, int | str]]:
    purge_expired_households(session)
    rows = session.execute(select(HouseholdRegistration.h3_cell, func.count())
                            .where(HouseholdRegistration.expires_at > datetime.now(UTC))
                            .group_by(HouseholdRegistration.h3_cell)).all()
    return [{"cell_id": cell, "registration_count": count} for cell, count in rows]


@router.get("/households/map")
def household_map(session: SessionDep, _user: Coordinator) -> dict:
    """Return coarse cell centroids and counts; never expose registry coordinates or PII."""
    purge_expired_households(session)
    rows = session.execute(select(HouseholdRegistration.h3_cell, func.count())
                           .where(HouseholdRegistration.expires_at > datetime.now(UTC))
                           .group_by(HouseholdRegistration.h3_cell)).all()
    return {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [h3.cell_to_latlng(cell)[1], h3.cell_to_latlng(cell)[0]]},
         "properties": {"cell_id": cell, "registration_count": count, "precision": "H3 resolution 8"}}
        for cell, count in rows
    ]}
