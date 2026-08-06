"""Seed demo appointment slots for local testing."""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from src.booking.models import Slot  # noqa: F401
from src.config import get_settings
from src.persistence.database import Base


SPECIALTIES = [
    "SP_PED",
    "SP_OBG",
    "cardiology",
    "K27",
    "SP_INT",
    "SP_SUR",
    "main",
]

FACILITIES = ["main", "facility-vinmec-01", "facility-vinmec-02"]


def seed_slots() -> None:
    settings = get_settings()
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    slots_to_add = []

    # Generate slots for the next 14 days, from 8:00 to 17:00 every hour
    for day_offset in range(14):
        base_date = now + timedelta(days=day_offset)
        for hour in (8, 9, 10, 11, 13, 14, 15, 16):
            slot_start = base_date.replace(hour=hour, minute=0, second=0)
            slot_end = slot_start + timedelta(minutes=45)
            
            for spec in SPECIALTIES:
                for fac in FACILITIES[:2]:
                    slot_id = str(uuid.uuid4())
                    slots_to_add.append({
                        "id": slot_id,
                        "specialty_id": spec,
                        "facility_id": fac,
                        "starts_at": slot_start,
                        "ends_at": slot_end,
                        "capacity": 2,
                        "enabled": True,
                        "created_at": now,
                    })

    with factory() as session:
        with session.begin():
            if settings.database_url.startswith("sqlite"):
                session.execute(text("DELETE FROM slots;"))
            else:
                session.execute(text("TRUNCATE TABLE slots CASCADE;"))
            session.execute(
                text("""
                    INSERT INTO slots (id, specialty_id, facility_id, starts_at, ends_at, capacity, enabled, created_at)
                    VALUES (:id, :specialty_id, :facility_id, :starts_at, :ends_at, :capacity, :enabled, :created_at)
                """),
                slots_to_add,
            )
    print(f"Successfully seeded {len(slots_to_add)} slots for local testing across {len(SPECIALTIES)} specialties!")


if __name__ == "__main__":
    seed_slots()
