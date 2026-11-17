import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.api import auth
from services.api.db import Base
from services.api.models import User
from services.api.security import decode_token, hash_password, verify_password


def test_password_hash_is_salted_and_verifies():
    first = hash_password("synthetic-password")
    second = hash_password("synthetic-password")
    assert first != second
    assert verify_password("synthetic-password", first)
    assert not verify_password("wrong-password", first)


def test_dashboard_login_and_refresh_rotation(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add(
            User(
                user_id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
                email="coordinator@example.com",
                password_hash=hash_password("synthetic-password"),
                role="coordinator",
            )
        )
        session.commit()
        tokens = auth.login(auth.LoginBody(email="coordinator@example.com", password="synthetic-password"), session)
        access_claims = decode_token(tokens.access_token, "access")
        assert access_claims["role"] == "coordinator"
        refreshed = auth.refresh(auth.RefreshBody(refresh_token=tokens.refresh_token), session)
        assert decode_token(refreshed.access_token, "access")["sub"] == access_claims["sub"]
        with pytest.raises(HTTPException) as error:
            auth.refresh(auth.RefreshBody(refresh_token=tokens.refresh_token), session)
        assert error.value.status_code == 401
    engine.dispose()
