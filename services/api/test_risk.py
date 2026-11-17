import json

import pytest

from services.api.privacy import encrypt_registration
from services.api.risk import risk_index


def test_risk_index_uses_documented_weighted_components():
    assert risk_index({"hazard_exposure": 100, "population_density": 0,
                       "vulnerable_households": 0, "access_difficulty": 0}) == 40
    assert risk_index({"hazard_exposure": 100, "population_density": 100,
                       "vulnerable_households": 100, "access_difficulty": 100}) == 100
    assert risk_index({"hazard_exposure": 500}) == 40


def test_household_payload_is_encrypted_and_non_deterministic(monkeypatch):
    monkeypatch.setenv("REGISTRY_ENCRYPTION_KEY", "synthetic-only-test-key")
    payload = json.dumps({"contact_name": "Synthetic Person", "contact_phone": "000-000-0000"}).encode()
    encrypted_a = encrypt_registration(payload)
    encrypted_b = encrypt_registration(payload)
    assert "Synthetic Person" not in encrypted_a
    assert encrypted_a != encrypted_b


def test_production_requires_explicit_encryption_key(monkeypatch):
    monkeypatch.delenv("REGISTRY_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("DEMO_MODE", "false")
    with pytest.raises(RuntimeError, match="REGISTRY_ENCRYPTION_KEY"):
        encrypt_registration(b"synthetic")
