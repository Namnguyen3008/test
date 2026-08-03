import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from src.api.auth_routes import AuthContext, authenticated_context, csrf_protected
from src.persistence.database import Base, get_db_session
from src.persistence.identity_models import AuditEventRecord, UserRecord
from src.review.api import router
from src.review.models import ClinicalReviewDecision
from src.review.repository import ReviewConflictError, ReviewForbiddenError, ReviewRepository
from src.security.auth import Principal, Role

RELEASE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
ADMIN = "10000000-0000-0000-0000-000000000001"
REVIEWER_1 = "20000000-0000-0000-0000-000000000002"
REVIEWER_2 = "30000000-0000-0000-0000-000000000003"
PATIENT = "40000000-0000-0000-0000-000000000004"
STAFF = "50000000-0000-0000-0000-000000000005"


@pytest.fixture
def review_factory(tmp_path) -> sessionmaker[Session]:
    engine = create_engine(f"sqlite:///{tmp_path / 'review.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory.begin() as session:
        session.add_all(
            [
                UserRecord(id=ADMIN, email="admin@example.test", role=Role.ADMIN, password_hash="unused"),
                UserRecord(
                    id=REVIEWER_1,
                    email="reviewer1@example.test",
                    role=Role.CLINICAL_REVIEWER,
                    password_hash="unused",
                ),
                UserRecord(
                    id=REVIEWER_2,
                    email="reviewer2@example.test",
                    role=Role.CLINICAL_REVIEWER,
                    password_hash="unused",
                ),
                UserRecord(id=PATIENT, email="patient@example.test", role=Role.PATIENT, password_hash="unused"),
                UserRecord(id=STAFF, email="staff@example.test", role=Role.STAFF, password_hash="unused"),
            ]
        )
    return factory


def create_item(factory, *, row_id="route-1", safety_critical=False):
    with factory() as session:
        return ReviewRepository(session).create_item(
            release_id=RELEASE,
            origin_table="routing_rows",
            origin_row_id=row_id,
            content_hash=("a" if not safety_critical else "b") * 64,
            evidence_summary="Nội dung bằng chứng chỉ hiển thị cho reviewer.",
            source_ids=["GLOBAL-1"],
            safety_critical=safety_critical,
            actor_id=ADMIN,
        )


def test_single_review_is_audited_but_never_marks_production_approved(review_factory) -> None:
    item = create_item(review_factory)
    with review_factory() as session:
        claimed = ReviewRepository(session).claim(item_id=item.id, reviewer_id=REVIEWER_1, expected_version=1)
    with review_factory() as session:
        approved = ReviewRepository(session).decide(
            item_id=item.id,
            reviewer_id=REVIEWER_1,
            expected_version=claimed.version,
            decision="APPROVE",
            rationale="Nguồn và định tuyến đã được đối chiếu đầy đủ.",
        )
    assert approved.status == "APPROVED"

    with review_factory() as session:
        repository = ReviewRepository(session)
        report = repository.promotion_report(RELEASE)
        exported = repository.safe_export(RELEASE)
        actions = list(session.scalars(select(AuditEventRecord.action).order_by(AuditEventRecord.id)))
    assert report["status"] == "ELIGIBLE_FOR_GOVERNANCE_REVIEW"
    assert report["production_approved"] is False
    assert exported["production_approved"] is False
    assert exported["contains_evidence_text"] is False
    assert "evidence_summary" not in str(exported)
    assert "Nguồn và định tuyến" not in str(exported)
    assert actions == ["review.item_create", "review.claim", "review.approve"]


def test_safety_critical_item_requires_distinct_second_reviewer(review_factory) -> None:
    item = create_item(review_factory, row_id="critical-1", safety_critical=True)
    with review_factory() as session:
        first_claim = ReviewRepository(session).claim(item_id=item.id, reviewer_id=REVIEWER_1, expected_version=1)
    with review_factory() as session:
        first = ReviewRepository(session).decide(
            item_id=item.id,
            reviewer_id=REVIEWER_1,
            expected_version=first_claim.version,
            decision="APPROVE",
            rationale="Vòng một xác nhận nguồn và quy tắc an toàn phù hợp.",
        )
    assert first.status == "ADJUDICATION_REQUIRED"

    with pytest.raises(ReviewForbiddenError, match="different reviewer"):
        with review_factory() as session:
            ReviewRepository(session).claim(item_id=item.id, reviewer_id=REVIEWER_1, expected_version=first.version)
    with review_factory() as session:
        second_claim = ReviewRepository(session).claim(
            item_id=item.id, reviewer_id=REVIEWER_2, expected_version=first.version
        )
    with review_factory() as session:
        approved = ReviewRepository(session).decide(
            item_id=item.id,
            reviewer_id=REVIEWER_2,
            expected_version=second_claim.version,
            decision="APPROVE",
            rationale="Vòng hai độc lập xác nhận bằng chứng và hard negatives.",
        )
    assert approved.status == "APPROVED"
    with review_factory() as session:
        reviewers = set(session.scalars(select(ClinicalReviewDecision.reviewer_id)))
    assert reviewers == {REVIEWER_1, REVIEWER_2}


def test_claim_version_rationale_and_competing_reviewer_are_enforced(review_factory) -> None:
    item = create_item(review_factory, row_id="conflict-1")
    with review_factory() as session:
        claimed = ReviewRepository(session).claim(
            item_id=item.id, reviewer_id=REVIEWER_1, expected_version=item.version
        )
    with pytest.raises(ReviewConflictError, match="version changed"):
        with review_factory() as session:
            ReviewRepository(session).claim(item_id=item.id, reviewer_id=REVIEWER_2, expected_version=item.version)
    with pytest.raises(ReviewConflictError, match="substantive"):
        with review_factory() as session:
            ReviewRepository(session).decide(
                item_id=item.id,
                reviewer_id=REVIEWER_1,
                expected_version=claimed.version,
                decision="APPROVE",
                rationale="quá ngắn",
            )


@pytest.mark.parametrize(("user_id", "role"), [(PATIENT, Role.PATIENT), (STAFF, Role.STAFF)])
def test_patient_and_staff_cannot_read_claim_or_decide_review_items(review_factory, user_id, role) -> None:
    item = create_item(review_factory, row_id="rbac-1")
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    def db_override():
        with review_factory() as session:
            yield session

    patient_context = AuthContext(Principal(user_id, role), "opaque-session")
    app.dependency_overrides[get_db_session] = db_override
    app.dependency_overrides[authenticated_context] = lambda: patient_context
    app.dependency_overrides[csrf_protected] = lambda: patient_context
    client = TestClient(app)
    assert client.get("/api/v1/review/workflow/items").status_code == 403
    assert (
        client.post(
            f"/api/v1/review/workflow/items/{item.id}/claim",
            json={"expected_version": 1},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/review/workflow/items/{item.id}/decision",
            json={
                "expected_version": 1,
                "decision": "APPROVE",
                "rationale": "Patient must never approve clinical review data.",
            },
        ).status_code
        == 403
    )
