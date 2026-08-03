import base64

import pytest

from src.security.auth import (
    CsrfService,
    FieldEncryption,
    PasswordService,
    Principal,
    Role,
    SessionStore,
    require_role,
)
from src.services.llm import InMemoryRedisState


def test_passwords_use_argon2id_and_wrong_password_fails():
    service = PasswordService()
    encoded = service.hash("a-strong-password")
    assert encoded.startswith("$argon2id$")
    assert service.verify(encoded, "a-strong-password")
    assert not service.verify(encoded, "wrong-password")


@pytest.mark.asyncio
async def test_opaque_session_resolve_and_revoke():
    store = SessionStore(InMemoryRedisState())
    principal = Principal("patient-1", Role.PATIENT)
    token = await store.create(principal)
    assert "patient-1" not in token
    assert await store.resolve(token) == principal
    await store.revoke(token)
    assert await store.resolve(token) is None


def test_rbac_is_deny_by_default():
    patient = Principal("p1", Role.PATIENT)
    require_role(patient, Role.PATIENT)
    with pytest.raises(PermissionError):
        require_role(patient, Role.STAFF, Role.ADMIN)


def test_csrf_is_bound_to_session_and_expires():
    now = [1000.0]
    csrf = CsrfService("x" * 32, max_age_seconds=60, clock=lambda: now[0])
    token = csrf.issue("session-a")
    assert csrf.verify("session-a", token)
    assert not csrf.verify("session-b", token)
    now[0] = 1061
    assert not csrf.verify("session-a", token)


def test_field_encryption_round_trip_and_tamper_detection():
    key = base64.urlsafe_b64encode(b"k" * 32).decode()
    encryption = FieldEncryption(key)
    ciphertext = encryption.encrypt("sensitive medical note")
    assert "medical note" not in ciphertext
    assert encryption.decrypt(ciphertext) == "sensitive medical note"
    with pytest.raises(ValueError):
        encryption.decrypt(ciphertext[:-2] + "xx")
