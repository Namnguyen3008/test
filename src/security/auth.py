"""Authentication primitives: Argon2id, opaque sessions, RBAC and CSRF."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Protocol

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken


class Role(StrEnum):
    PATIENT = "PATIENT"
    STAFF = "STAFF"
    CLINICAL_REVIEWER = "CLINICAL_REVIEWER"
    ADMIN = "ADMIN"


@dataclass(frozen=True)
class Principal:
    user_id: str
    role: Role


class SessionRedis(Protocol):
    async def get(self, key: str) -> str | bytes | None: ...
    async def set(self, key: str, value: str, *, ex: int | None = None) -> object: ...
    async def delete(self, key: str) -> object: ...


class PasswordService:
    def __init__(self) -> None:
        self._hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4)

    def hash(self, password: str) -> str:
        if len(password) < 12:
            raise ValueError("Password must be at least 12 characters")
        return self._hasher.hash(password)

    def verify(self, encoded: str, password: str) -> bool:
        try:
            return self._hasher.verify(encoded, password)
        except VerifyMismatchError:
            return False


class SessionStore:
    def __init__(self, redis: SessionRedis, *, ttl_seconds: int = 3600) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @staticmethod
    def _key(token: str) -> str:
        return "vmec:session:" + hashlib.sha256(token.encode()).hexdigest()

    async def create(self, principal: Principal) -> str:
        token = secrets.token_urlsafe(32)
        await self._redis.set(self._key(token), json.dumps(asdict(principal)), ex=self._ttl)
        return token

    async def resolve(self, token: str) -> Principal | None:
        if len(token) < 32:
            return None
        raw = await self._redis.get(self._key(token))
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode()
        payload = json.loads(raw)
        return Principal(str(payload["user_id"]), Role(payload["role"]))

    async def revoke(self, token: str) -> None:
        await self._redis.delete(self._key(token))


def require_role(principal: Principal, *allowed: Role) -> None:
    if principal.role not in allowed:
        raise PermissionError("Role is not authorized for this action")


class CsrfService:
    def __init__(self, secret: str, *, max_age_seconds: int = 3600, clock=time.time) -> None:
        if len(secret) < 32:
            raise ValueError("CSRF secret must contain at least 32 characters")
        self._secret = secret.encode()
        self._max_age = max_age_seconds
        self._clock = clock

    def issue(self, session_token: str) -> str:
        timestamp = str(int(self._clock()))
        nonce = secrets.token_urlsafe(18)
        body = f"{session_token}.{timestamp}.{nonce}".encode()
        signature = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        return f"{timestamp}.{nonce}.{signature}"

    def verify(self, session_token: str, token: str) -> bool:
        try:
            timestamp, nonce, supplied = token.split(".", 2)
            age = self._clock() - int(timestamp)
        except (ValueError, TypeError):
            return False
        if age < 0 or age > self._max_age:
            return False
        body = f"{session_token}.{timestamp}.{nonce}".encode()
        expected = hmac.new(self._secret, body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(supplied, expected)


class FieldEncryption:
    """Version-ready field encryption adapter; keys are supplied outside Git."""

    def __init__(self, urlsafe_key: str) -> None:
        try:
            decoded = base64.urlsafe_b64decode(urlsafe_key)
        except ValueError as exc:
            raise ValueError("Invalid field encryption key") from exc
        if len(decoded) != 32:
            raise ValueError("Field encryption key must decode to 32 bytes")
        self._fernet = Fernet(urlsafe_key.encode())

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode()).decode()

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet.decrypt(ciphertext.encode()).decode()
        except InvalidToken as exc:
            raise ValueError("Encrypted field authentication failed") from exc
