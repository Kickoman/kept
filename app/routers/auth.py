from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import auth as authlib
from ..config import get_settings
from ..db import get_db
from ..logging_setup import get_logger
from ..models import User, UserSession
from ..schemas import ChangePasswordIn, LoginIn, ProfilePatch, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger()


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterIn, response: Response, request: Request, db: Session = Depends(get_db)) -> User:
    exists = db.scalar(select(User.id).where(User.username == payload.username))
    if exists is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="username_taken")
    user = User(
        username=payload.username,
        password_hash=authlib.hash_password(payload.password),
        display_name=payload.display_name,
        is_admin=payload.username in get_settings().admin_set,
    )
    db.add(user)
    db.flush()
    token = authlib.create_session(db, user)
    db.commit()
    authlib.set_session_cookie(response, token, request)
    log.info("user_registered", user_id=user.id, is_admin=user.is_admin)
    return user


@router.post("/login", response_model=UserOut)
def login(payload: LoginIn, response: Response, request: Request, db: Session = Depends(get_db)) -> User:
    user = db.scalar(select(User).where(User.username == payload.username))
    if user is None or not authlib.verify_password(payload.password, user.password_hash):
        log.info("login_failed", known_user=user is not None)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_credentials")
    token = authlib.create_session(db, user)
    db.commit()
    authlib.set_session_cookie(response, token, request)
    log.info("user_logged_in", user_id=user.id)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> Response:
    token = request.cookies.get(authlib.COOKIE_NAME)
    if token:
        authlib.delete_session(db, token)
        db.commit()
    resp = Response(status_code=status.HTTP_204_NO_CONTENT)
    authlib.clear_session_cookie(resp)
    return resp


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(authlib.require_user)) -> User:
    return user


@router.patch("/me", response_model=UserOut)
def update_profile(payload: ProfilePatch, user: User = Depends(authlib.require_user), db: Session = Depends(get_db)) -> User:
    user = db.merge(user)
    user.display_name = payload.display_name
    db.commit()
    log.info("profile_updated", user_id=user.id)
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordIn,
    request: Request,
    user: User = Depends(authlib.require_user),
    db: Session = Depends(get_db),
) -> Response:
    if not authlib.verify_password(payload.current_password, user.password_hash):
        log.info("password_change_rejected", user_id=user.id)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="wrong_password")
    user = db.merge(user)
    user.password_hash = authlib.hash_password(payload.new_password)
    # Close every other session; the one making this request stays valid.
    current = authlib.token_hash(request.cookies.get(authlib.COOKIE_NAME) or "")
    db.execute(delete(UserSession).where(UserSession.user_id == user.id, UserSession.token_hash != current))
    db.commit()
    log.info("password_changed", user_id=user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
