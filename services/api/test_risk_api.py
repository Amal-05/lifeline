import h3
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from services.api.models import AuditLog, Base, HouseholdRegistration, User
from services.api.risk import (
    HouseholdRegistrationBody,
    RiskCsvImport,
    RiskLayerImport,
    delete_household,
    export_household,
    get_risk_cells,
    household_map,
    import_risk_csv,
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
    assert stored.registrar_id == "U" * 26
    assert stored.consent_at is not None
    mapped = household_map(risk_session, User(user_id="U" * 26, role="coordinator"))
    assert mapped["features"][0]["properties"]["registration_count"] == 1
    assert mapped["features"][0]["properties"]["precision"] == "H3 resolution 8"
    assert "contact_name" not in str(mapped)
    exported = export_household(result["registration_id"], risk_session, User(user_id="U" * 26, role="coordinator"))
    assert exported["data"]["contact_name"] == "Synthetic Person"
    assert risk_session.scalar(select(AuditLog).where(AuditLog.action == "household.exported")) is not None


def test_household_delete_removes_ciphertext_and_audits_without_pii(risk_session):
    body = HouseholdRegistrationBody(latitude=10, longitude=76, household_size=2,
        contact_name="Synthetic Person", contact_phone="000-000-0000", consent=True)
    result = register_household(body, risk_session, User(user_id="U" * 26, role="coordinator"))
    delete_household(result["registration_id"], risk_session, User(user_id="U" * 26, role="coordinator"))
    assert risk_session.get(HouseholdRegistration, result["registration_id"]) is None
    audit = risk_session.scalar(select(AuditLog).where(AuditLog.action == "household.deleted"))
    assert audit is not None
    assert "Synthetic Person" not in str(audit.before_data)
    assert "000-000-0000" not in str(audit.before_data)


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


def test_csv_risk_fallback_derives_transparent_hazard_and_context_factors(risk_session):
    cell = h3.latlng_to_cell(10, 76, 8)
    body = RiskCsvImport(source="DEM/rainfall/river fallback", license="synthetic", csv_text=(
        "cell_id,elevation_m,slope_deg,distance_to_water_m,rainfall_mm_24h,flood_history_count,"
        "population_density_per_km2,vulnerable_households_per_1000,road_access_score\n"
        f"{cell},10,20,100,120,5,1500,25,30\n"
    ))
    result = import_risk_csv(body, risk_session, User(user_id="A" * 26, role="admin"))
    from services.api.models import RiskCell

    stored = risk_session.get(RiskCell, cell)
    assert result == {"imported": 1}
    assert stored.source == "DEM/rainfall/river fallback (synthetic)"
    assert stored.factors["rainfall_mm_24h"] == 120
    assert stored.factors["hazard_exposure"] > 70
    assert stored.factors["access_difficulty"] == 70


def test_csv_risk_fallback_rejects_bad_cell_and_negative_measurements(risk_session):
    from services.api.risk import HTTPException

    header = "cell_id,elevation_m,slope_deg,distance_to_water_m,rainfall_mm_24h,flood_history_count,population_density_per_km2,vulnerable_households_per_1000,road_access_score\n"
    bad_cell = RiskCsvImport(source="synthetic test", csv_text=header + "not-h3,1,1,1,1,1,1,1,1\n")
    with pytest.raises(HTTPException) as invalid_cell:
        import_risk_csv(bad_cell, risk_session, User(user_id="A" * 26, role="admin"))
    assert invalid_cell.value.status_code == 422
    cell = h3.latlng_to_cell(10, 76, 8)
    negative = RiskCsvImport(source="synthetic test", csv_text=header + f"{cell},-1,1,1,1,1,1,1,1\n")
    with pytest.raises(HTTPException) as invalid_value:
        import_risk_csv(negative, risk_session, User(user_id="A" * 26, role="admin"))
    assert invalid_value.value.status_code == 422


def test_csv_risk_import_requires_synthetic_or_open_license():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RiskCsvImport(source="unlicensed dataset", license="proprietary", csv_text="x")
