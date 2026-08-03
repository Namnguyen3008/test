"""Persistent authentication, consent and administrative identity endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config import get_settings
from src.persistence.database import get_db_session
from src.persistence.identity_models import AuditEventRecord, UserRecord
from src.security.auth import CsrfService, Principal, Role, SessionStore, require_role
from src.security.identity import (
    AuthenticationError,
    DuplicateIdentityError,
    IdentityService,
)


def prevent_sensitive_caching(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(tags=["identity"], dependencies=[Depends(prevent_sensitive_caching)])


class RedisSessionAdapter:
    def __init__(self, url: str) -> None:
        self._client = Redis.from_url(url, decode_responses=True)

    async def get(self, key: str) -> str | bytes | None:
        return await self._client.get(key)

    async def set(self, key: str, value: str, *, ex: int | None = None) -> object:
        return await self._client.set(key, value, ex=ex)

    async def delete(self, key: str) -> object:
        return await self._client.delete(key)

    async def aclose(self) -> None:
        await self._client.aclose()


@lru_cache
def get_session_store() -> SessionStore:
    settings = get_settings()
    return SessionStore(RedisSessionAdapter(settings.session_redis_url), ttl_seconds=settings.session_ttl_seconds)


@lru_cache
def get_csrf_service() -> CsrfService:
    settings = get_settings()
    return CsrfService(settings.csrf_secret.get_secret_value(), max_age_seconds=settings.session_ttl_seconds)


def get_identity_service(
    db: Annotated[Session, Depends(get_db_session)],
    sessions: Annotated[SessionStore, Depends(get_session_store)],
) -> IdentityService:
    return IdentityService(db, sessions, session_ttl_seconds=get_settings().session_ttl_seconds)


@dataclass(frozen=True)
class AuthContext:
    principal: Principal
    token: str


async def authenticated_context(
    request: Request,
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> AuthContext:
    session_token = request.cookies.get(get_settings().session_cookie_name)
    if not session_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    principal = await service.resolve(session_token)
    if principal is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return AuthContext(principal, session_token)


def csrf_protected(
    context: Annotated[AuthContext, Depends(authenticated_context)],
    csrf: Annotated[CsrfService, Depends(get_csrf_service)],
    csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> AuthContext:
    if csrf_token is None or not csrf.verify(context.token, csrf_token):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed")
    return context


class Credentials(BaseModel):
    email: EmailStr
    password: str = Field(min_length=12, max_length=256)


class UserView(BaseModel):
    id: str
    email: str
    role: Role
    active: bool


class SessionView(BaseModel):
    user: UserView
    csrf_token: str
    expires_at: datetime


class ProvisionUserRequest(Credentials):
    role: Literal[Role.STAFF, Role.CLINICAL_REVIEWER, Role.ADMIN]


class ConsentView(BaseModel):
    purpose: str
    granted: bool
    granted_at: datetime
    revoked_at: datetime | None


def _user_view(user: UserRecord) -> UserView:
    return UserView(id=user.id, email=user.email, role=Role(user.role), active=user.active)


def _set_session_cookies(response: Response, token: str, csrf_token: str) -> None:
    settings = get_settings()
    secure = settings.app_env == "production"
    response.set_cookie(
        settings.session_cookie_name,
        token,
        max_age=settings.session_ttl_seconds,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        "vmec_csrf",
        csrf_token,
        max_age=settings.session_ttl_seconds,
        httponly=False,
        secure=secure,
        samesite="lax",
        path="/",
    )


@router.post("/auth/register", response_model=UserView, status_code=status.HTTP_201_CREATED)
def register(payload: Credentials, service: Annotated[IdentityService, Depends(get_identity_service)]) -> UserView:
    try:
        return _user_view(service.create_user(str(payload.email), payload.password))
    except DuplicateIdentityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Identity already exists") from exc


@router.post("/auth/login", response_model=SessionView)
async def login(
    payload: Credentials,
    request: Request,
    response: Response,
    service: Annotated[IdentityService, Depends(get_identity_service)],
    csrf: Annotated[CsrfService, Depends(get_csrf_service)],
) -> SessionView:
    previous_token = request.cookies.get(get_settings().session_cookie_name)
    try:
        auth = await service.login(str(payload.email), payload.password, previous_token=previous_token)
    except AuthenticationError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials") from exc
    user = service.get_user(auth.principal.user_id)
    if user is None:  # pragma: no cover - guarded by login transaction
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    csrf_token = csrf.issue(auth.token)
    _set_session_cookies(response, auth.token, csrf_token)
    return SessionView(user=_user_view(user), csrf_token=csrf_token, expires_at=auth.expires_at)


@router.get("/auth/me", response_model=UserView)
def me(
    context: Annotated[AuthContext, Depends(authenticated_context)],
    db: Annotated[Session, Depends(get_db_session)],
) -> UserView:
    user = db.get(UserRecord, context.principal.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    return _user_view(user)


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    context: Annotated[AuthContext, Depends(csrf_protected)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> None:
    await service.revoke(context.token)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("vmec_csrf", path="/")


@router.post("/auth/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    response: Response,
    context: Annotated[AuthContext, Depends(csrf_protected)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> None:
    await service.revoke_all(context.principal.user_id)
    settings = get_settings()
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie("vmec_csrf", path="/")


@router.post("/auth/session/rotate", response_model=SessionView)
async def rotate_session(
    response: Response,
    context: Annotated[AuthContext, Depends(csrf_protected)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
    csrf: Annotated[CsrfService, Depends(get_csrf_service)],
) -> SessionView:
    auth = await service.rotate(context.token)
    user = service.get_user(auth.principal.user_id)
    if user is None:  # pragma: no cover
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    csrf_token = csrf.issue(auth.token)
    _set_session_cookies(response, auth.token, csrf_token)
    return SessionView(user=_user_view(user), csrf_token=csrf_token, expires_at=auth.expires_at)


@router.get("/consents", response_model=list[ConsentView])
def list_consents(
    context: Annotated[AuthContext, Depends(authenticated_context)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> list[ConsentView]:
    try:
        require_role(context.principal, Role.PATIENT)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    return [
        ConsentView(
            purpose=row.purpose,
            granted=row.revoked_at is None,
            granted_at=row.granted_at,
            revoked_at=row.revoked_at,
        )
        for row in service.list_consents(context.principal.user_id)
    ]


@router.put("/consents/{purpose}", response_model=ConsentView)
def update_consent(
    purpose: str,
    granted: bool,
    context: Annotated[AuthContext, Depends(csrf_protected)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> ConsentView:
    try:
        require_role(context.principal, Role.PATIENT)
        row = service.set_consent(context.principal.user_id, purpose, granted=granted)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return ConsentView(
        purpose=row.purpose,
        granted=row.revoked_at is None,
        granted_at=row.granted_at,
        revoked_at=row.revoked_at,
    )


@router.post("/admin/users", response_model=UserView, status_code=status.HTTP_201_CREATED)
def provision_user(
    payload: ProvisionUserRequest,
    context: Annotated[AuthContext, Depends(csrf_protected)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> UserView:
    try:
        require_role(context.principal, Role.ADMIN)
        return _user_view(
            service.create_user(
                str(payload.email),
                payload.password,
                role=Role(payload.role),
                actor_id=context.principal.user_id,
            )
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    except DuplicateIdentityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Identity already exists") from exc


@router.get("/admin/audit")
def audit_events(
    context: Annotated[AuthContext, Depends(authenticated_context)],
    db: Annotated[Session, Depends(get_db_session)],
    limit: int = 100,
) -> list[dict[str, object]]:
    try:
        require_role(context.principal, Role.ADMIN)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    safe_limit = max(1, min(limit, 500))
    rows = db.scalars(select(AuditEventRecord).order_by(AuditEventRecord.id.desc()).limit(safe_limit))
    return [
        {
            "id": row.id,
            "actor_id": row.actor_id,
            "action": row.action,
            "target_type": row.target_type,
            "target_id": row.target_id,
            "outcome": row.outcome,
            "trace_id": row.trace_id,
            "occurred_at": row.occurred_at,
            "safe_metadata": row.safe_metadata,
        }
        for row in rows
    ]


@router.delete("/admin/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: str,
    context: Annotated[AuthContext, Depends(csrf_protected)],
    service: Annotated[IdentityService, Depends(get_identity_service)],
) -> None:
    try:
        service.deactivate_user(context.principal, user_id)
        await service.revoke_all(
            user_id,
            reason="account_deactivated",
            actor_id=context.principal.user_id,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found") from exc
