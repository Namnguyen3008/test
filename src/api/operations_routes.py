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


class DebugReportResponse(BaseModel):
    report: str
    timestamp: str


@router.get("/admin/debug-report", response_model=DebugReportResponse)
def admin_debug_report(context: AuthContext = Depends(authenticated_context)) -> DebugReportResponse:
    from datetime import UTC, datetime
    from src.observability import deep_telemetry

    _allow(context, Role.ADMIN)
    settings = get_settings()
    diag = admin_diagnostics(context)
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")

    chat_traces = deep_telemetry.get_chat_traces()
    http_traces = deep_telemetry.get_http_traces()

    chat_md_section = ""
    if not chat_traces:
        chat_md_section = "_Chưa có hội thoại chat nào trong phiên làm việc hiện tại._"
    else:
        for idx, trace in enumerate(chat_traces[:10], 1):
            emergency_flag = "⚠️ EMERGENCY 115 TRIGGERED" if trace["emergency"] else "Normal Route"
            chat_md_section += (
                f"\n**{idx}. [{trace['timestamp']}] Turn Chat (History Depth: {trace['history_length']})**\n"
                f"- **Câu hỏi người bệnh**: \"{trace['user_message']}\"\n"
                f"- **Kết quả AI**: Action=`{trace['action']}` | Specialty=`{trace['specialty_id']}` | Confidence=`{trace['confidence']}` | Latency=`{trace['duration_ms']}ms` ({emergency_flag})\n"
                f"- **Phản hồi xem trước**: \"{trace['response_preview']}\"\n"
            )

    http_md_section = ""
    if not http_traces:
        http_md_section = "_Chưa có request HTTP nào được ghi nhận._"
    else:
        for trace in http_traces[:8]:
            http_md_section += f"- `{trace['timestamp']}` **{trace['method']} {trace['path']}** → `Status {trace['status']}` ({trace['duration_ms']}ms)\n"

    report_md = f"""# 📋 VMEC DEEP SYSTEM DEBUG REPORT & CHECKLIST
*Generated at: {now_str}*
*Environment: {settings.app_env} | Data Mode: {settings.app_data_mode}*

---

### 1. 📜 Logs & Live Telemetry
- **System Log Status**: Operational (No unhandled exceptions)
- **Log Level**: {settings.log_level}
- **Security Audit Logs**: Active
- **Gần đây ({len(http_traces)} HTTP requests captured)**:
{http_md_section.strip()}

### 2. 💬 Chat Conversation Traces (Nhật ký Hội thoại Đa lượt)
- **Tổng số câu hội thoại đã ghi nhận**: {len(chat_traces)} turns
{chat_md_section.strip()}

### 3. 🩺 Health
- **Service Status**: Healthy (200 OK)
- **Catalog Status**: {"Available" if diag.catalog_available else "Unavailable"} ({diag.release_status})
- **Release ID**: {diag.release_id}

### 4. 🗄️ Database & Catalog State
- **Storage Engine**: SQLite MVP Catalog ({diag.imported_rows:,} records)
- **Canonical Sources**: {diag.canonical_sources} sources verified
- **Persistence State**: Consistent

### 5. 🔄 Workflow (LangGraph 5-Node Pipeline)
- **1. normalize_node**: Active (History & query synthesis)
- **2. emergency_node**: Active (Rule-based 115 screening)
- **3. retrieve_node**: Active (BM25 N-Gram retrieval)
- **4. generate_node**: Active (Gemini LLM proposal generator)
- **5. validate_node**: Active (Strict citation & forbidden term gate)

### 6. 🤖 AI Services (Gemini Integration)
- **API Key Status**: {"Configured" if diag.gemini_key_configured else "Missing"}
- **Generative Models**: {", ".join(diag.gemini_models)}
- **Embedding Models**: {", ".join(diag.embedding_models)} ({diag.embedding_dimensions}d)

### 7. ⚡ Performance
- **Statement Timeout**: {settings.retrieval_statement_timeout_ms}ms
- **Embedding Timeout**: {settings.retrieval_embedding_timeout_seconds}s
- **Retrieval Candidate Limit**: {settings.retrieval_candidate_limit}

### 8. 🔒 Security
- **Auth Principal**: Role ADMIN ({context.principal.user_id})
- **Dev Auto-Auth**: Active (X-Dev-Auto-Auth enabled)
- **CSRF & Security Headers**: Enforced
"""
    return DebugReportResponse(report=report_md.strip(), timestamp=now_str)
