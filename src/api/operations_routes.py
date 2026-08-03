"""Role-restricted clinical review and aggregate platform diagnostics."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from services.retrieval import candidate_from_dataset_row
from src.api.auth_routes import AuthContext, authenticated_context
from src.config import get_settings
from src.security.auth import Role, require_role
from src.services.emergency import emergency_runtime_status

router = APIRouter(tags=["operations"])
_REVIEW_TABLES = (
    "routing_rows",
    "specialty_reference",
    "clarifying_questions",
    "faq",
    "human_support_content",
    "visit_preparation",
)


class ReviewItem(BaseModel):
    row_id: str
    table: str
    content_preview: str = Field(max_length=500)
    canonical_status: str
    review_status: str
    source_ids: list[str]


class ReviewQueue(BaseModel):
    items: list[ReviewItem]
    offset: int
    limit: int
    read_only: bool = True


class AdminDiagnostics(BaseModel):
    data_mode: str
    catalog_available: bool
    release_id: str
    release_status: str
    imported_rows: int
    canonical_sources: int
    emergency_rules: dict[str, object]
    gemini_models: list[str]
    embedding_models: list[str]
    embedding_dimensions: int
    gemini_key_configured: bool
    full_embedding_backfill_permitted: bool
    production_approved: bool = False


def _allow(context: AuthContext, *roles: Role) -> None:
    try:
        require_role(context.principal, *roles)
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden") from exc


def _release_id() -> str:
    settings = get_settings()
    return (
        settings.emergency_release_id
        or {
            "development": "vmec-development-v2",
            "review": "vmec-review-v2",
            "production": "vmec-production-v1",
        }[settings.app_data_mode]
    )


def _connection() -> sqlite3.Connection | None:
    catalog = Path(get_settings().emergency_catalog_path)
    if not catalog.is_file():
        return None
    return sqlite3.connect(f"file:{catalog.resolve().as_posix()}?mode=ro", uri=True)


@router.get("/review/items", response_model=ReviewQueue)
def review_items(
    context: AuthContext = Depends(authenticated_context),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
) -> ReviewQueue:
    _allow(context, Role.CLINICAL_REVIEWER, Role.ADMIN)
    connection = _connection()
    if connection is None:
        return ReviewQueue(items=[], offset=offset, limit=limit)
    try:
        placeholders = ",".join("?" for _ in _REVIEW_TABLES)
        rows = connection.execute(
            f"SELECT table_name,row_key,content_hash,payload_json FROM dataset_rows "  # noqa: S608
            f"WHERE release_id=? AND table_name IN ({placeholders}) ORDER BY table_name,row_key",
            (_release_id(), *_REVIEW_TABLES),
        )
        items: list[ReviewItem] = []
        skipped = 0
        for table, row_id, content_hash, raw in rows:
            payload = json.loads(raw)
            canonical_status = str(payload.get("canonical_status", "REVIEW_REQUIRED")).upper()
            review_status = str(payload.get("review_status", "PENDING_CLINICAL_REVIEW")).upper()
            if canonical_status != "REVIEW_REQUIRED" and review_status != "PENDING_CLINICAL_REVIEW":
                continue
            candidate = candidate_from_dataset_row(table, row_id, content_hash, payload)
            if not candidate.text or candidate.conflict_status.upper() in {"CONFLICT", "REJECTED"}:
                continue
            if skipped < offset:
                skipped += 1
                continue
            items.append(
                ReviewItem(
                    row_id=str(row_id),
                    table=str(table),
                    content_preview=candidate.text[:500],
                    canonical_status=canonical_status,
                    review_status=review_status,
                    source_ids=list(candidate.source_ids),
                )
            )
            if len(items) >= limit:
                break
        return ReviewQueue(items=items, offset=offset, limit=limit)
    finally:
        connection.close()


@router.get("/admin/diagnostics", response_model=AdminDiagnostics)
def admin_diagnostics(context: AuthContext = Depends(authenticated_context)) -> AdminDiagnostics:
    _allow(context, Role.ADMIN)
    settings = get_settings()
    release_id = _release_id()
    connection = _connection()
    release_status = "unavailable"
    row_count = 0
    source_count = 0
    if connection is not None:
        try:
            release = connection.execute(
                "SELECT status FROM dataset_releases WHERE release_id=?", (release_id,)
            ).fetchone()
            release_status = str(release[0]) if release else "missing"
            row_count = int(
                connection.execute("SELECT count(*) FROM dataset_rows WHERE release_id=?", (release_id,)).fetchone()[0]
            )
            source_count = int(
                connection.execute("SELECT count(*) FROM global_sources WHERE release_id=?", (release_id,)).fetchone()[
                    0
                ]
            )
        finally:
            connection.close()
    return AdminDiagnostics(
        data_mode=settings.app_data_mode,
        catalog_available=connection is not None,
        release_id=release_id,
        release_status=release_status,
        imported_rows=row_count,
        canonical_sources=source_count,
        emergency_rules=emergency_runtime_status(),
        gemini_models=[settings.gemini_generative_model_1, settings.gemini_generative_model_2],
        embedding_models=[
            settings.gemini_embedding_primary_model,
            settings.gemini_embedding_text_fallback_model,
        ],
        embedding_dimensions=settings.gemini_embedding_dimensions,
        gemini_key_configured=bool(settings.gemini_api_key.get_secret_value()),
        full_embedding_backfill_permitted=False,
    )
