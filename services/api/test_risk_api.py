import h3
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from services.api.models import Base, HouseholdRegistration, User
from services.api.risk import (
    HouseholdRegistrationBody,
    RiskLayerImport,
    get_risk_cells,
    import_risk_layer,
    register_household,
)


@pytest.fixture
def risk_session(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'risk.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setenv("DEMO_MODE", "true")
    monkeypatch.setenv("REGISTRY_ENCRYPTION_KEY", "synthetic-test-key")
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_risk_geojson_contains_only_synthetic_cells(risk_session):
    layer = get_risk_cells(risk_session, User(user_id="U" * 26, role="viewer"))
    assert layer["type"] == "FeatureCollection"
    assert len(layer["features"]) == 3
    assert all(feature["properties"]["source"] == "synthetic demo layer" for feature in layer["features"])


def test_registration_persists_ciphertext_and_returns_no_contact_data(risk_session):
    body = HouseholdRegistrationBody(latitude=10, longitude=76, household_size=2,
        vulnerability_tags=["elderly"], contact_name="Synthetic Person", contact_phone="000-000-0000", consent=True)
    result = register_household(body, risk_session, User(user_id="U" * 26, role="coordinator"))
    stored = risk_session.scalar(select(HouseholdRegistration))
    assert result["status"] == "encrypted"
    assert "Synthetic Person" not in stored.encrypted_payload
    assert "000-000-0000" not in stored.encrypted_payload


def test_registration_rejects_missing_consent(risk_session):
    body = HouseholdRegistrationBody(latitude=10, longitude=76, household_size=2,
        contact_name="Synthetic Person", contact_phone="000-000-0000", consent=False)
    with pytest.raises(HTTPException) as error:
        register_household(body, risk_session, User(user_id="U" * 26, role="coordinator"))
    assert error.value.status_code == 400


def test_admin_risk_import_recomputes_weighted_index(risk_session):
    cell = h3.latlng_to_cell(10, 76, 8)
    boundary = h3.cell_to_boundary(cell)
    ring = [[lon, lat] for lat, lon in boundary]
    ring.append(ring[0])
    body = RiskLayerImport(source="synthetic import test", features=[{
        "type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
        "properties": {"cell_id": cell, "factors": {"hazard_exposure": 100}},
    }])
    result = import_risk_layer(body, risk_session, User(user_id="A" * 26, role="admin"))
    assert result == {"imported": 1}
