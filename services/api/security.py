import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from services.api.dependencies import get_session
from services.api.models import RefreshToken, User

JWT_SECRET = os.getenv("JWT_SECRET_KEY", "local-dev-secret-change-before-deploy")
JWT_ALGORITHM = "HS256"
ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=7)
bearer = HTTPBearer(auto_error=False)


def hash_password(password: str, salt: bytes | None = None) -> str:
    actual_salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=actual_salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${actual_salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt_hex, digest_hex = stored.split("$", 2)
        if algorithm != "scrypt":
            return False
        return hmac.compare_digest(hash_password(password, bytes.fromhex(salt_hex)).split("$", 2)[2], digest_hex)
    except (ValueError, TypeError):
        return False


def _encode(user: User, token_type: str, ttl: timedelta, jti: str | None = None) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user.user_id,
            "role": user.role,
            "team_id": user.team_id,
            "type": token_type,
            "jti": jti or secrets.token_urlsafe(24),
            "iat": now,
            "exp": now + ttl,
            "aud": "lifeline-dashboard",
        },
        JWT_SECRET,
        algorithm=JWT_ALGORITHM,
    )


def create_token_pair(session: Session, user: User) -> dict[str, str | int]:
    jti = secrets.token_urlsafe(24)
    expires_at = datetime.now(UTC) + REFRESH_TTL
    session.add(RefreshToken(jti=jti, user_id=user.user_id, expires_at=expires_at))
    session.flush()
    return {
        "access_token": _encode(user, "access", ACCESS_TTL),
        "refresh_token": _encode(user, "refresh", REFRESH_TTL, jti),
        "token_type": "bearer",
        "expires_in": int(ACCESS_TTL.total_seconds()),
    }


def decode_token(token: str, expected_type: str) -> dict:
    try:
        claims = jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM],
            audience="lifeline-dashboard",
            options={"require": ["sub", "role", "type", "jti", "exp", "iat", "aud"]},
        )
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}) from exc
    if claims.get("type") != expected_type:
        raise HTTPException(status_code=401, detail="Wrong token type", headers={"WWW-Authenticate": "Bearer"})
    return claims


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_session)],
) -> User:
    if credentials is None:
        raise HTTPException(status_code=401, detail="Authentication required", headers={"WWW-Authenticate": "Bearer"})
    claims = decode_token(credentials.credentials, "access")
    user = session.get(User, claims["sub"])
    if user is None or not user.active or user.role != claims["role"]:
        raise HTTPException(status_code=401, detail="Account is unavailable")
    return user


def require_roles(*roles: str):
    def check(user: Annotated[User, Depends(current_user)]) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Role is not allowed for this action")
        return user

    return check
