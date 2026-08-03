"""Persistent identity services with Redis-backed opaque sessions."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.persistence.identity_models import (
    AuditEventRecord,
    AuthSessionRecord,
    ConsentGrantRecord,
    UserRecord,
)
from src.security.auth import PasswordService, Principal, Role, SessionStore

ALLOWED_CONSENT_PURPOSES = frozenset({"PERSONALIZATION", "CONVERSATION_MEMORY"})
SAFE_AUDIT_METADATA_KEYS = frozenset({"reason_code", "purpose", "session_event"})


class AuthenticationError(Exception):
    pass


class DuplicateIdentityError(Exception):
    pass


@dataclass(frozen=True)
class AuthenticatedSession:
    principal: Principal
    token: str
    expires_at: datetime


class AuditWriter:
    def __init__(self, db: Session) -> None:
        self._db = db

    def append(
        self,
        *,
        actor_id: str | None,
        action: str,
        target_type: str,
        target_id: str,
        outcome: str,
        trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe = {
            key: value
            for key, value in (metadata or {}).items()
            if key in SAFE_AUDIT_METADATA_KEYS and isinstance(value, (str, int, bool))
        }
        self._db.add(
            AuditEventRecord(
                actor_id=actor_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                outcome=outcome,
                trace_id=trace_id or uuid.uuid4().hex,
                safe_metadata=safe,
            )
        )


class IdentityService:
    def __init__(
        self,
        db: Session,
        sessions: SessionStore,
        *,
        password_service: PasswordService | None = None,
        session_ttl_seconds: int = 3600,
    ) -> None:
        self._db = db
        self._sessions = sessions
        self._passwords = password_service or PasswordService()
        self._ttl = session_ttl_seconds
        self._audit = AuditWriter(db)

    @staticmethod
    def normalize_email(email: str) -> str:
        normalized = email.strip().casefold()
        if not normalized or "@" not in normalized or len(normalized) > 320:
            raise ValueError("Invalid email address")
        return normalized

    @staticmethod
    def opaque_email_reference(email: str) -> str:
        return "email:" + hashlib.sha256(email.encode()).hexdigest()[:24]

    def create_user(
        self,
        email: str,
        password: str,
        *,
        role: Role = Role.PATIENT,
        actor_id: str | None = None,
    ) -> UserRecord:
        normalized = self.normalize_email(email)
        user = UserRecord(email=normalized, password_hash=self._passwords.hash(password), role=role.value)
        self._db.add(user)
        try:
            self._db.flush()
            self._audit.append(
                actor_id=actor_id,
                action="identity.user_created",
                target_type="user",
                target_id=user.id,
                outcome="success",
            )
            self._db.commit()
        except IntegrityError as exc:
            self._db.rollback()
            raise DuplicateIdentityError("Identity already exists") from exc
        return user

    async def login(self, email: str, password: str, *, previous_token: str | None = None) -> AuthenticatedSession:
        normalized = self.normalize_email(email)
        user = self._db.scalar(select(UserRecord).where(UserRecord.email == normalized))
        if user is None or not user.active or not self._passwords.verify(user.password_hash, password):
            self._audit.append(
                actor_id=None,
                action="identity.login",
                target_type="identity",
                target_id=self.opaque_email_reference(normalized),
                outcome="denied",
                metadata={"reason_code": "invalid_credentials"},
            )
            self._db.commit()
            raise AuthenticationError("Invalid credentials")
        if previous_token:
            await self.revoke(previous_token, reason="login_rotation")
        return await self._create_session(user, session_event="login")

    async def _create_session(self, user: UserRecord, *, session_event: str) -> AuthenticatedSession:
        principal = Principal(user.id, Role(user.role))
        token = await self._sessions.create(principal)
        expires_at = datetime.now(UTC) + timedelta(seconds=self._ttl)
        record = AuthSessionRecord(
            user_id=user.id,
            token_digest=SessionStore.digest(token),
            expires_at=expires_at,
        )
        self._db.add(record)
        self._db.flush()
        self._audit.append(
            actor_id=user.id,
            action="identity.session_created",
            target_type="auth_session",
            target_id=record.id,
            outcome="success",
            metadata={"session_event": session_event},
        )
        try:
            self._db.commit()
        except Exception:
            self._db.rollback()
            await self._sessions.revoke(token)
            raise
        return AuthenticatedSession(principal, token, expires_at)

    async def resolve(self, token: str) -> Principal | None:
        cached = await self._sessions.resolve(token)
        if cached is None:
            return None
        now = datetime.now(UTC)
        row = self._db.scalar(
            select(AuthSessionRecord)
            .join(UserRecord)
            .where(
                AuthSessionRecord.token_digest == SessionStore.digest(token),
                AuthSessionRecord.revoked_at.is_(None),
                AuthSessionRecord.expires_at > now,
                UserRecord.active.is_(True),
            )
        )
        if row is None:
            await self._sessions.revoke(token)
            return None
        user = row.user
        row.last_seen_at = now
        self._db.commit()
        return Principal(user.id, Role(user.role))

    async def rotate(self, token: str) -> AuthenticatedSession:
        principal = await self.resolve(token)
        if principal is None:
            raise AuthenticationError("Invalid session")
        user = self._db.get(UserRecord, principal.user_id)
        if user is None:
            raise AuthenticationError("Invalid session")
        replacement = await self._create_session(user, session_event="rotation")
        await self.revoke(token, reason="rotated")
        return replacement

    async def revoke(self, token: str, *, reason: str = "logout") -> None:
        digest = SessionStore.digest(token)
        row = self._db.scalar(select(AuthSessionRecord).where(AuthSessionRecord.token_digest == digest))
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            row.revoke_reason = reason
            self._audit.append(
                actor_id=row.user_id,
                action="identity.session_revoked",
                target_type="auth_session",
                target_id=row.id,
                outcome="success",
                metadata={"reason_code": reason},
            )
            self._db.commit()
        await self._sessions.revoke(token)

    async def revoke_all(
        self,
        user_id: str,
        *,
        reason: str = "logout_all",
        actor_id: str | None = None,
    ) -> None:
        rows = self._db.scalars(
            select(AuthSessionRecord).where(
                AuthSessionRecord.user_id == user_id, AuthSessionRecord.revoked_at.is_(None)
            )
        ).all()
        for row in rows:
            row.revoked_at = datetime.now(UTC)
            row.revoke_reason = reason
        self._audit.append(
            actor_id=actor_id or user_id,
            action="identity.sessions_revoked",
            target_type="user",
            target_id=user_id,
            outcome="success",
            metadata={"reason_code": reason},
        )
        self._db.commit()
        for row in rows:
            await self._sessions.revoke_digest(row.token_digest)

    def set_consent(self, patient_id: str, purpose: str, *, granted: bool) -> ConsentGrantRecord:
        if purpose not in ALLOWED_CONSENT_PURPOSES:
            raise ValueError("Unsupported consent purpose")
        user = self._db.get(UserRecord, patient_id)
        if user is None or user.role != Role.PATIENT.value:
            raise PermissionError("Consent belongs to a patient identity")
        grant = self._db.scalar(
            select(ConsentGrantRecord).where(
                ConsentGrantRecord.patient_id == patient_id, ConsentGrantRecord.purpose == purpose
            )
        )
        now = datetime.now(UTC)
        if grant is None:
            grant = ConsentGrantRecord(patient_id=patient_id, purpose=purpose)
            self._db.add(grant)
            self._db.flush()
        if granted:
            grant.granted_at = now
            grant.revoked_at = None
        else:
            grant.revoked_at = now
        grant.updated_at = now
        self._audit.append(
            actor_id=patient_id,
            action="consent.granted" if granted else "consent.revoked",
            target_type="consent",
            target_id=grant.id,
            outcome="success",
            metadata={"purpose": purpose},
        )
        self._db.commit()
        return grant

    def list_consents(self, patient_id: str) -> list[ConsentGrantRecord]:
        return list(
            self._db.scalars(
                select(ConsentGrantRecord)
                .where(ConsentGrantRecord.patient_id == patient_id)
                .order_by(ConsentGrantRecord.purpose)
            )
        )

    def has_active_consent(self, patient_id: str, purpose: str) -> bool:
        if purpose not in ALLOWED_CONSENT_PURPOSES:
            return False
        return (
            self._db.scalar(
                select(ConsentGrantRecord.id).where(
                    ConsentGrantRecord.patient_id == patient_id,
                    ConsentGrantRecord.purpose == purpose,
                    ConsentGrantRecord.revoked_at.is_(None),
                )
            )
            is not None
        )

    def get_user(self, user_id: str) -> UserRecord | None:
        return self._db.get(UserRecord, user_id)

    def deactivate_user(self, actor: Principal, user_id: str) -> None:
        if actor.role is not Role.ADMIN:
            raise PermissionError("Role is not authorized for this action")
        user = self._db.get(UserRecord, user_id)
        if user is None:
            raise LookupError("User not found")
        user.active = False
        self._audit.append(
            actor_id=actor.user_id,
            action="identity.user_deactivated",
            target_type="user",
            target_id=user_id,
            outcome="success",
        )
        self._db.commit()
