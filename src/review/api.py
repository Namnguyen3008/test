"""RBAC-protected human review actions and safe governance reports."""

from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from src.api.auth_routes import AuthContext, authenticated_context, csrf_protected
from src.persistence.database import get_db_session
from src.review.models import ClinicalReviewItem
from src.review.repository import ReviewConflictError, ReviewForbiddenError, ReviewNotFoundError, ReviewRepository
from src.security.auth import Principal, Role, require_role

router = APIRouter(prefix="/review/workflow", tags=["clinical-review"])
SessionDependency = Annotated[Session, Depends(get_db_session)]
AuthDependency = Annotated[AuthContext, Depends(authenticated_context)]
MutationAuthDependency = Annotated[AuthContext, Depends(csrf_protected)]


class ReviewItemCreate(BaseModel):
    release_id: str = Field(min_length=1, max_length=64)
    record_id: str | None = None
    origin_table: str = Field(min_length=1, max_length=100)
    origin_row_id: str = Field(min_length=1, max_length=200)
    content_hash: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    evidence_summary: str = Field(min_length=1, max_length=5000)
    source_ids: list[str] = Field(min_length=1, max_length=20)
    safety_critical: bool = False


class ReviewPackageImport(BaseModel):
    items: list[ReviewItemCreate] = Field(min_length=1, max_length=100)


class VersionRequest(BaseModel):
    expected_version: int = Field(ge=1)


class ClaimRequest(VersionRequest):
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class DecisionRequest(VersionRequest):
    decision: Literal["APPROVE", "REJECT", "REQUEST_CHANGES"]
    rationale: str = Field(min_length=20, max_length=2000)


class ReviewItemView(BaseModel):
    id: str
    release_id: str
    origin_table: str
    origin_row_id: str
    content_hash: str
    evidence_summary: str
    source_ids: list[str]
    safety_critical: bool
    required_reviews: int
    status: str
    claimed_by: str | None
    claim_expires_at: str | None
    version: int


def _allow(principal: Principal, *roles: Role) -> None:
    try:
        require_role(principal, *roles)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc


def _view(item: ClinicalReviewItem) -> ReviewItemView:
    return ReviewItemView(
        id=item.id,
        release_id=item.release_id,
        origin_table=item.origin_table,
        origin_row_id=item.origin_row_id,
        content_hash=item.content_hash,
        evidence_summary=item.evidence_summary,
        source_ids=item.source_ids,
        safety_critical=item.safety_critical,
        required_reviews=item.required_reviews,
        status=item.status,
        claimed_by=item.claimed_by,
        claim_expires_at=item.claim_expires_at.isoformat() if item.claim_expires_at else None,
        version=item.version,
    )


def _translate(exc: Exception) -> None:
    if isinstance(exc, ReviewNotFoundError):
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if isinstance(exc, ReviewForbiddenError):
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if isinstance(exc, ReviewConflictError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


@router.get("/items", response_model=list[ReviewItemView])
def workflow_queue(session: SessionDependency, context: AuthDependency) -> list[ReviewItemView]:
    _allow(context.principal, Role.CLINICAL_REVIEWER, Role.ADMIN)
    return [_view(item) for item in ReviewRepository(session).queue()]


@router.post("/items", response_model=ReviewItemView, status_code=201)
def create_review_item(
    body: ReviewItemCreate, session: SessionDependency, context: MutationAuthDependency
) -> ReviewItemView:
    _allow(context.principal, Role.ADMIN)
    try:
        return _view(ReviewRepository(session).create_item(**body.model_dump(), actor_id=context.principal.user_id))
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/packages/import", response_model=list[ReviewItemView])
def import_review_package(
    body: ReviewPackageImport, session: SessionDependency, context: MutationAuthDependency
) -> list[ReviewItemView]:
    _allow(context.principal, Role.ADMIN)
    repository = ReviewRepository(session)
    try:
        imported = repository.import_package(
            [item.model_dump() for item in body.items], actor_id=context.principal.user_id
        )
        return [_view(item) for item in imported]
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/items/{item_id}/claim", response_model=ReviewItemView)
def claim_item(
    item_id: str, body: ClaimRequest, session: SessionDependency, context: MutationAuthDependency
) -> ReviewItemView:
    _allow(context.principal, Role.CLINICAL_REVIEWER, Role.ADMIN)
    try:
        return _view(
            ReviewRepository(session).claim(
                item_id=item_id,
                reviewer_id=context.principal.user_id,
                expected_version=body.expected_version,
                ttl_seconds=body.ttl_seconds,
            )
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/items/{item_id}/release", response_model=ReviewItemView)
def release_item(
    item_id: str, body: VersionRequest, session: SessionDependency, context: MutationAuthDependency
) -> ReviewItemView:
    _allow(context.principal, Role.CLINICAL_REVIEWER, Role.ADMIN)
    try:
        return _view(
            ReviewRepository(session).release(
                item_id=item_id,
                reviewer_id=context.principal.user_id,
                expected_version=body.expected_version,
            )
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.post("/items/{item_id}/decision", response_model=ReviewItemView)
def decide_item(
    item_id: str, body: DecisionRequest, session: SessionDependency, context: MutationAuthDependency
) -> ReviewItemView:
    _allow(context.principal, Role.CLINICAL_REVIEWER, Role.ADMIN)
    try:
        return _view(
            ReviewRepository(session).decide(
                item_id=item_id,
                reviewer_id=context.principal.user_id,
                expected_version=body.expected_version,
                decision=body.decision,
                rationale=body.rationale,
            )
        )
    except Exception as exc:
        _translate(exc)
        raise


@router.get("/releases/{release_id}/promotion-report")
def promotion_report(release_id: str, session: SessionDependency, context: AuthDependency) -> dict[str, object]:
    _allow(context.principal, Role.CLINICAL_REVIEWER, Role.ADMIN)
    return ReviewRepository(session).promotion_report(release_id)


@router.get("/releases/{release_id}/export")
def safe_export(release_id: str, session: SessionDependency, context: AuthDependency) -> dict[str, object]:
    _allow(context.principal, Role.CLINICAL_REVIEWER, Role.ADMIN)
    return ReviewRepository(session).safe_export(release_id)
