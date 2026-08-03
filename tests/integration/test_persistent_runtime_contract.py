from __future__ import annotations

import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from redis.asyncio import Redis
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.orm import Session, sessionmaker

from src.booking.models import (
    Appointment,
    AppointmentEvent,
    AppointmentReminder,
    BookingOutbox,
    IdempotencyRecord,
    Slot,
    SlotHold,
)
from src.booking.repository import BookingConflictError, BookingRepository
from src.persistence.identity_models import AuditEventRecord, UserRecord
from src.security.auth import Principal, Role, SessionStore
from src.services.llm import ALLOWED_GEMINI_MODELS, GeminiRoundRobin, RedisAsyncState

POSTGRES_URL = os.environ.get("VMEC_TEST_POSTGRES_URL", "")
REDIS_URL = os.environ.get("VMEC_TEST_REDIS_URL", "")


def postgres_factory() -> tuple[object, sessionmaker[Session]]:
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    return engine, sessionmaker(engine, expire_on_commit=False)


@pytest.mark.skipif(not POSTGRES_URL, reason="VMEC_TEST_POSTGRES_URL is not configured")
def test_empty_database_migration_has_required_extensions_and_single_head() -> None:
    engine, _ = postgres_factory()
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == (
                "20260803_0008_persistent_import"
            )
            extensions = set(
                connection.scalars(
                    text("SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm','unaccent')")
                )
            )
        assert extensions == {"vector", "pg_trgm", "unaccent"}
    finally:
        engine.dispose()


@pytest.mark.skipif(not REDIS_URL, reason="VMEC_TEST_REDIS_URL is not configured")
@pytest.mark.asyncio
async def test_real_redis_persists_sessions_and_global_round_robin() -> None:
    namespace = uuid.uuid4().hex
    session_state_1 = RedisAsyncState(REDIS_URL)
    session_state_2 = RedisAsyncState(REDIS_URL)
    first_store = SessionStore(session_state_1, ttl_seconds=300)
    second_store = SessionStore(session_state_2, ttl_seconds=300)
    token = await first_store.create(Principal(namespace, Role.PATIENT))
    assert await second_store.resolve(token) == Principal(namespace, Role.PATIENT)
    await second_store.revoke(token)
    assert await first_store.resolve(token) is None

    class Models:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def generate_content(self, *, model, contents, config):
            self.calls.append(model)
            return SimpleNamespace(text="safe test response")

    class Client:
        def __init__(self, models: Models) -> None:
            self.aio = SimpleNamespace(models=models)

    key = f"vmec:test:round-robin:{namespace}"
    first_models, second_models = Models(), Models()
    first = GeminiRoundRobin(
        "test-key", client=Client(first_models), redis=RedisAsyncState(REDIS_URL), round_robin_key=key
    )
    second = GeminiRoundRobin(
        "test-key", client=Client(second_models), redis=RedisAsyncState(REDIS_URL), round_robin_key=key
    )
    cleanup = Redis.from_url(REDIS_URL, decode_responses=True)
    try:
        await cleanup.delete(key)
        await first.generate("synthetic non-clinical test")
        await second.generate("synthetic non-clinical test")
        assert first_models.calls == [ALLOWED_GEMINI_MODELS[0]]
        assert second_models.calls == [ALLOWED_GEMINI_MODELS[1]]
        assert await cleanup.get(key) == "2"
    finally:
        await cleanup.delete(key)
        await cleanup.aclose()
        await first.aclose()
        await second.aclose()
        await first_store.aclose()
        await second_store.aclose()


@pytest.mark.skipif(not POSTGRES_URL, reason="VMEC_TEST_POSTGRES_URL is not configured")
def test_postgres_row_lock_and_unique_hold_allow_exactly_one_winner() -> None:
    engine, factory = postgres_factory()
    slot_id = str(uuid.uuid4())
    patient_ids = [str(uuid.uuid4()) for _ in range(4)]
    starts_at = datetime.now(UTC) + timedelta(days=1)
    try:
        with factory.begin() as session:
            session.add_all(
                UserRecord(id=value, email=f"{value}@example.test", role=Role.PATIENT, password_hash="unused")
                for value in patient_ids
            )
            session.add(
                Slot(
                    id=slot_id,
                    specialty_id="runtime-contract",
                    facility_id="runtime-contract",
                    starts_at=starts_at,
                    ends_at=starts_at + timedelta(minutes=30),
                )
            )

        barrier = threading.Barrier(len(patient_ids))

        def attempt(index: int) -> str:
            barrier.wait()
            try:
                with factory() as session:
                    BookingRepository(session).hold(
                        slot_id=slot_id,
                        patient_id=patient_ids[index],
                        key=f"runtime-race-{index}-{slot_id}",
                    )
                return "won"
            except BookingConflictError:
                return "conflict"

        with ThreadPoolExecutor(max_workers=len(patient_ids)) as pool:
            outcomes = list(pool.map(attempt, range(len(patient_ids))))

        assert outcomes.count("won") == 1
        assert outcomes.count("conflict") == len(patient_ids) - 1
        with factory() as session:
            assert (
                session.scalar(select(SlotHold).where(SlotHold.slot_id == slot_id, SlotHold.released_at.is_(None)))
                is not None
            )
    finally:
        with factory.begin() as session:
            appointment_ids = list(session.scalars(select(Appointment.id).where(Appointment.slot_id == slot_id)))
            if appointment_ids:
                session.execute(
                    delete(AppointmentReminder).where(AppointmentReminder.appointment_id.in_(appointment_ids))
                )
                session.execute(delete(AppointmentEvent).where(AppointmentEvent.appointment_id.in_(appointment_ids)))
                session.execute(delete(SlotHold).where(SlotHold.appointment_id.in_(appointment_ids)))
                session.execute(delete(BookingOutbox).where(BookingOutbox.aggregate_id.in_(appointment_ids)))
                session.execute(delete(Appointment).where(Appointment.id.in_(appointment_ids)))
            session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id.in_(patient_ids)))
            session.execute(delete(AuditEventRecord).where(AuditEventRecord.actor_id.in_(patient_ids)))
            session.execute(delete(Slot).where(Slot.id == slot_id))
            session.execute(delete(UserRecord).where(UserRecord.id.in_(patient_ids)))
        engine.dispose()
