from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.config import Settings
from src.persistence.database import Base
from src.persistence.identity_models import AuditEventRecord, AuthSessionRecord, UserRecord
from src.security.auth import PasswordService, Principal, Role, SessionStore
from src.security.identity import AuditWriter, AuthenticationError, IdentityService
from src.services.llm import InMemoryRedisState


@pytest.fixture
def db() -> Session:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session


@pytest.fixture
def identity(db: Session) -> IdentityService:
    return IdentityService(db, SessionStore(InMemoryRedisState()), session_ttl_seconds=3600)


@pytest.mark.asyncio
async def test_login_is_persistent_opaque_and_revocable(db: Session, identity: IdentityService) -> None:
    user = identity.create_user("Patient@Example.com", "correct-horse-battery")
    auth = await identity.login("patient@example.com", "correct-horse-battery")

    assert user.password_hash.startswith("$argon2id$")
    assert user.id not in auth.token
    assert "patient@example.com" not in auth.token
    record = db.scalar(select(AuthSessionRecord))
    assert record is not None
    assert record.token_digest == SessionStore.digest(auth.token)
    assert auth.token not in record.token_digest
    assert await identity.resolve(auth.token) == Principal(user.id, Role.PATIENT)

    await identity.revoke(auth.token)
    assert await identity.resolve(auth.token) is None
    db.refresh(record)
    assert record.revoked_at is not None


@pytest.mark.asyncio
async def test_invalid_password_is_generic_and_audit_does_not_store_email(
    db: Session, identity: IdentityService
) -> None:
    identity.create_user("private.patient@example.com", "correct-horse-battery")
    with pytest.raises(AuthenticationError, match="Invalid credentials"):
        await identity.login("private.patient@example.com", "wrong-password-value")

    event = db.scalar(select(AuditEventRecord).where(AuditEventRecord.action == "identity.login"))
    assert event is not None
    assert event.outcome == "denied"
    assert event.target_id.startswith("email:")
    assert "private.patient" not in event.target_id


@pytest.mark.asyncio
async def test_expired_or_deactivated_session_fails_closed(db: Session, identity: IdentityService) -> None:
    user = identity.create_user("patient@example.com", "correct-horse-battery")
    expired = await identity.login(user.email, "correct-horse-battery")
    record = db.scalar(
        select(AuthSessionRecord).where(AuthSessionRecord.token_digest == SessionStore.digest(expired.token))
    )
    assert record is not None
    record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    assert await identity.resolve(expired.token) is None

    active = await identity.login(user.email, "correct-horse-battery")
    user.active = False
    db.commit()
    assert await identity.resolve(active.token) is None


@pytest.mark.asyncio
async def test_rotation_and_revoke_all_invalidate_every_old_token(
    identity: IdentityService,
) -> None:
    user = identity.create_user("patient@example.com", "correct-horse-battery")
    first = await identity.login(user.email, "correct-horse-battery")
    second = await identity.rotate(first.token)
    third = await identity.login(user.email, "correct-horse-battery")

    assert await identity.resolve(first.token) is None
    assert await identity.resolve(second.token) is not None
    assert await identity.resolve(third.token) is not None
    await identity.revoke_all(user.id)
    assert await identity.resolve(second.token) is None
    assert await identity.resolve(third.token) is None


def test_consent_is_patient_owned_revocable_and_allowlisted(
    identity: IdentityService,
) -> None:
    patient = identity.create_user("patient@example.com", "correct-horse-battery")
    staff = identity.create_user("staff@example.com", "correct-horse-battery", role=Role.STAFF)

    granted = identity.set_consent(patient.id, "CONVERSATION_MEMORY", granted=True)
    assert granted.revoked_at is None
    assert identity.has_active_consent(patient.id, "CONVERSATION_MEMORY")
    revoked = identity.set_consent(patient.id, "CONVERSATION_MEMORY", granted=False)
    assert revoked.id == granted.id
    assert revoked.revoked_at is not None
    assert not identity.has_active_consent(patient.id, "CONVERSATION_MEMORY")
    assert not identity.has_active_consent(patient.id, "ADVERTISING")
    with pytest.raises(ValueError, match="Unsupported"):
        identity.set_consent(patient.id, "ADVERTISING", granted=True)
    with pytest.raises(PermissionError):
        identity.set_consent(staff.id, "PERSONALIZATION", granted=True)


def test_rbac_deactivation_and_audit_metadata_are_deny_by_default(db: Session, identity: IdentityService) -> None:
    patient = identity.create_user("patient@example.com", "correct-horse-battery")
    admin = identity.create_user("admin@example.com", "correct-horse-battery", role=Role.ADMIN)
    with pytest.raises(PermissionError):
        identity.deactivate_user(Principal(patient.id, Role.PATIENT), admin.id)
    identity.deactivate_user(Principal(admin.id, Role.ADMIN), patient.id)
    assert db.get(UserRecord, patient.id).active is False  # type: ignore[union-attr]

    AuditWriter(db).append(
        actor_id=admin.id,
        action="security.test",
        target_type="user",
        target_id=patient.id,
        outcome="success",
        metadata={"reason_code": "policy", "raw_prompt": "sensitive symptom"},
    )
    db.commit()
    event = db.scalar(select(AuditEventRecord).where(AuditEventRecord.action == "security.test"))
    assert event is not None
    assert event.safe_metadata == {"reason_code": "policy"}
    assert "sensitive symptom" not in str(event.safe_metadata)


def test_password_service_rejects_malformed_hash_and_oversized_password() -> None:
    passwords = PasswordService()
    assert not passwords.verify("not-an-argon-hash", "correct-horse-battery")
    assert not passwords.verify("not-an-argon-hash", "x" * 257)
    with pytest.raises(ValueError, match="exceed"):
        passwords.hash("x" * 257)


@pytest.mark.asyncio
async def test_corrupt_redis_session_payload_fails_closed() -> None:
    redis = InMemoryRedisState()
    store = SessionStore(redis)
    token = "x" * 40
    await redis.set("vmec:session:" + SessionStore.digest(token), "not-json")
    assert await store.resolve(token) is None
    assert await redis.get("vmec:session:" + SessionStore.digest(token)) is None


def test_production_identity_configuration_fails_closed() -> None:
    with pytest.raises(ValidationError, match="external CSRF secret"):
        Settings(app_env="production", database_url="postgresql+psycopg://db/vmec")
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(app_env="production", csrf_secret="s" * 32, database_url="sqlite:///unsafe.db")
    with pytest.raises(ValidationError, match="32 characters"):
        Settings(csrf_secret="short")
