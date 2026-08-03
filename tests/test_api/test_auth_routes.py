from __future__ import annotations

from collections.abc import AsyncGenerator, Generator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.api.auth_routes import get_auth_rate_limiter, get_csrf_service, get_session_store
from src.main import app
from src.persistence.database import Base, get_db_session
from src.security.auth import CsrfService, Role, SessionStore
from src.security.identity import IdentityService
from src.security.rate_limit import DistributedRateLimiter, InMemoryWindowBackend
from src.services.llm import InMemoryRedisState


@pytest.fixture
def identity_dependencies() -> Generator[tuple[sessionmaker[Session], SessionStore], None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    store = SessionStore(InMemoryRedisState())

    def db_override() -> Generator[Session, None, None]:
        with factory() as db:
            yield db

    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[get_session_store] = lambda: store
    app.dependency_overrides[get_csrf_service] = lambda: CsrfService("t" * 32)
    app.dependency_overrides[get_auth_rate_limiter] = lambda: DistributedRateLimiter(InMemoryWindowBackend())
    try:
        yield factory, store
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest_asyncio.fixture
async def auth_client(
    identity_dependencies: tuple[sessionmaker[Session], SessionStore],
) -> AsyncGenerator[AsyncClient, None]:
    del identity_dependencies
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _register_and_login(client: AsyncClient) -> dict[str, object]:
    payload = {"email": "patient@example.com", "password": "correct-horse-battery"}
    assert (await client.post("/api/v1/auth/register", json=payload)).status_code == 201
    response = await client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()


@pytest.mark.asyncio
async def test_authentication_cookie_csrf_rotation_and_logout(auth_client: AsyncClient) -> None:
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 401
    login = await _register_and_login(auth_client)
    csrf = str(login["csrf_token"])
    old_token = auth_client.cookies["vmec_session"]
    assert old_token not in str(login["user"])
    assert (
        "HttpOnly"
        in (
            await auth_client.post(
                "/api/v1/auth/login",
                json={"email": "patient@example.com", "password": "correct-horse-battery"},
            )
        ).headers["set-cookie"]
    )

    # Re-read the current CSRF because a second login rotates the session.
    current_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "patient@example.com", "password": "correct-horse-battery"},
    )
    csrf = current_login.json()["csrf_token"]
    assert (await auth_client.put("/api/v1/consents/CONVERSATION_MEMORY", params={"granted": True})).status_code == 403
    consent = await auth_client.put(
        "/api/v1/consents/CONVERSATION_MEMORY",
        params={"granted": True},
        headers={"X-CSRF-Token": csrf},
    )
    assert consent.status_code == 200
    assert consent.json()["granted"] is True

    rotated = await auth_client.post("/api/v1/auth/session/rotate", headers={"X-CSRF-Token": csrf})
    assert rotated.status_code == 200
    assert auth_client.cookies["vmec_session"] != old_token
    new_csrf = rotated.json()["csrf_token"]
    assert (await auth_client.post("/api/v1/auth/logout")).status_code == 403
    assert (await auth_client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": new_csrf})).status_code == 204
    assert (await auth_client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_rbac_negative_matrix_and_admin_provisioning(
    auth_client: AsyncClient,
    identity_dependencies: tuple[sessionmaker[Session], SessionStore],
) -> None:
    patient_login = await _register_and_login(auth_client)
    forbidden = await auth_client.post(
        "/api/v1/admin/users",
        json={
            "email": "staff@example.com",
            "password": "correct-horse-battery",
            "role": "STAFF",
        },
        headers={"X-CSRF-Token": patient_login["csrf_token"]},
    )
    assert forbidden.status_code == 403
    assert (await auth_client.get("/api/v1/admin/audit")).status_code == 403

    factory, store = identity_dependencies
    with factory() as db:
        IdentityService(db, store).create_user("admin@example.com", "correct-horse-battery", role=Role.ADMIN)
    admin_login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "correct-horse-battery"},
    )
    assert admin_login.status_code == 200
    created = await auth_client.post(
        "/api/v1/admin/users",
        json={
            "email": "reviewer@example.com",
            "password": "correct-horse-battery",
            "role": "CLINICAL_REVIEWER",
        },
        headers={"X-CSRF-Token": admin_login.json()["csrf_token"]},
    )
    assert created.status_code == 201
    assert created.json()["role"] == "CLINICAL_REVIEWER"
    audit = await auth_client.get("/api/v1/admin/audit")
    assert audit.status_code == 200
    serialized = audit.text
    assert "correct-horse-battery" not in serialized
    assert "patient@example.com" not in serialized


@pytest.mark.asyncio
async def test_login_failure_and_duplicate_registration_are_controlled(
    auth_client: AsyncClient,
) -> None:
    payload = {"email": "patient@example.com", "password": "correct-horse-battery"}
    assert (await auth_client.post("/api/v1/auth/register", json=payload)).status_code == 201
    assert (await auth_client.post("/api/v1/auth/register", json=payload)).status_code == 409
    failed = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": "patient@example.com", "password": "incorrect-password"},
    )
    assert failed.status_code == 401
    assert failed.json() == {"detail": "Invalid credentials"}


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [Role.PATIENT, Role.STAFF, Role.CLINICAL_REVIEWER])
async def test_every_non_admin_role_is_denied_admin_access(
    auth_client: AsyncClient,
    identity_dependencies: tuple[sessionmaker[Session], SessionStore],
    role: Role,
) -> None:
    factory, store = identity_dependencies
    email = f"{role.value.lower()}@example.com"
    with factory() as db:
        IdentityService(db, store).create_user(email, "correct-horse-battery", role=role)
    login = await auth_client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "correct-horse-battery"},
    )
    assert login.status_code == 200
    assert (await auth_client.get("/api/v1/admin/audit")).status_code == 403
    if role is not Role.PATIENT:
        assert (await auth_client.get("/api/v1/consents")).status_code == 403
