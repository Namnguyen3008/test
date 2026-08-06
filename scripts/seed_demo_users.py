import sys
import os

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from src.persistence.database import Base, get_engine, get_session_factory
from src.security.identity import IdentityService, DuplicateIdentityError
from src.security.auth import SessionStore, Role
from src.services.llm import InMemoryRedisState

DEMO_USERS = [
    {"email": "patient@vmec.vn", "password": "Patient123456!", "role": Role.PATIENT},
    {"email": "staff@vmec.vn", "password": "Staff12345678!", "role": Role.STAFF},
    {"email": "reviewer@vmec.vn", "password": "Reviewer12345!", "role": Role.CLINICAL_REVIEWER},
    {"email": "admin@vmec.vn", "password": "Admin12345678!", "role": Role.ADMIN},
]

def main():
    engine = get_engine()
    Base.metadata.create_all(engine)
    factory = get_session_factory()
    store = SessionStore(InMemoryRedisState())

    print("=======================================================")
    print("SEEDING DEMO USERS FOR ALL 4 ROLES")
    print("=======================================================")

    with factory() as db:
        service = IdentityService(db, store)
        for u in DEMO_USERS:
            try:
                user = service.create_user(u["email"], u["password"], role=u["role"])
                print(f"✅ Created {u['role']:<18} : {u['email']} (Password: {u['password']})")
            except DuplicateIdentityError:
                print(f"ℹ️ Already exists {u['role']:<13} : {u['email']}")

    print("\nDemo users successfully seeded!")

if __name__ == "__main__":
    main()
