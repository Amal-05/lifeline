import os
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from packages.protocol.python.lifeline_protocol import new_ulid
from services.api.dependencies import get_session
from services.api.models import RefreshToken, User
from services.api.security import create_token_pair, decode_token, hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])


class LoginBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)


class RefreshBody(BaseModel):
    refresh_token: str = Field(min_length=20)


class UserTokens(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


def seed_demo_user(session: Session) -> None:
    if os.getenv("DEMO_MODE", "false").casefold() != "true":
        return
    email = os.getenv("DEMO_ADMIN_EMAIL", "coordinator@example.com").casefold()
    if session.scalar(select(User).where(User.email == email)) is None:
        session.add(
            User(
                user_id=new_ulid(),
                email=email,
                password_hash=hash_password(os.getenv("DEMO_ADMIN_PASSWORD", "demo-only-change-me")),
                role="admin",
            )
        )
        session.commit()


@router.post("/login", response_model=UserTokens)
def login(body: LoginBody, session: Annotated[Session, Depends(get_session)]) -> UserTokens:
    seed_demo_user(session)
    user = session.scalar(select(User).where(User.email == str(body.email).casefold()))
    if user is None or not user.active or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    tokens = create_token_pair(session, user)
    session.commit()
    return UserTokens(**tokens)


@router.post("/refresh", response_model=UserTokens)
def refresh(body: RefreshBody, session: Annotated[Session, Depends(get_session)]) -> UserTokens:
    claims = decode_token(body.refresh_token, "refresh")
    record = session.get(RefreshToken, claims["jti"])
    expires_at = record.expires_at if record is not None else None
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if record is None or record.revoked or expires_at < datetime.now(UTC):
        raise HTTPException(status_code=401, detail="Refresh token is revoked or expired")
    user = session.get(User, record.user_id)
    if user is None or not user.active:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    record.revoked = True
    tokens = create_token_pair(session, user)
    session.commit()
    return UserTokens(**tokens)


@router.post("/logout", status_code=204)
def logout(body: RefreshBody, session: Annotated[Session, Depends(get_session)]) -> None:
    claims = decode_token(body.refresh_token, "refresh")
    record = session.get(RefreshToken, claims["jti"])
    if record and not record.revoked:
        record.revoked = True
        session.commit()
