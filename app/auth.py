from __future__ import annotations

import hashlib
import secrets
from datetime import timedelta

import bcrypt
from fastapi import Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from .config import get_settings
from .db import get_db
from .models import User, UserSession, utcnow

COOKIE_NAME = "kept_session"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create_session(db: Session, user: User) -> str:
    settings = get_settings()
    token = secrets.token_urlsafe(32)
    db.add(
        UserSession(
            token_hash=token_hash(token),
            user_id=user.id,
            expires_at=utcnow() + timedelta(days=settings.session_ttl_days),
        )
    )
    return token


def set_session_cookie(response: Response, token: str, request: Request) -> None:
    settings = get_settings()
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=settings.session_ttl_days * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure(request),
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def delete_session(db: Session, token: str) -> None:
    row = db.get(UserSession, token_hash(token))
    if row is not None:
        db.delete(row)


def user_from_token(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.get(UserSession, token_hash(token))
    if row is None:
        return None
    expires = row.expires_at
    if expires.tzinfo is None:  # sqlite drops tzinfo
        from datetime import timezone

        expires = expires.replace(tzinfo=timezone.utc)
    if expires < utcnow():
        db.delete(row)
        db.commit()
        return None
    return row.user


def current_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    return user_from_token(db, request.cookies.get(COOKIE_NAME))


def require_user(user: User | None = Depends(current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="auth_required")
    return user


def require_admin(user: User = Depends(require_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="admin_required")
    return user
