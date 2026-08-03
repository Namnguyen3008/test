from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from redis.asyncio import Redis
from sqlalchemy import text

from src.api.auth_routes import get_auth_rate_limiter, get_session_store
from src.api.auth_routes import router as auth_router
from src.api.operations_routes import router as operations_router
from src.api.routes import router
from src.booking.api import router as booking_router
from src.config import get_settings
from src.observability import configure_observability
from src.persistence.database import get_engine
from src.review.api import router as review_router
from src.security import SecurityHeadersMiddleware
from src.services.emergency import (
    DataMode,
    activate_emergency_rules,
    compile_emergency_catalog,
    emergency_runtime_status,
    reset_emergency_rules,
)
from src.services.llm import get_llm
from src.services.routing import get_routing_retriever


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    validate_data_readiness(settings.app_data_mode)
    initialize_emergency_runtime(settings.app_data_mode, settings.emergency_catalog_path, settings.emergency_release_id)
    try:
        yield
    finally:
        reset_emergency_rules()
        if get_auth_rate_limiter.cache_info().currsize:
            await get_auth_rate_limiter().aclose()
            get_auth_rate_limiter.cache_clear()
        if get_session_store.cache_info().currsize:
            await get_session_store().aclose()
            get_session_store.cache_clear()
        if get_llm.cache_info().currsize:
            await get_llm().aclose()
            get_llm.cache_clear()
        if get_routing_retriever.cache_info().currsize:
            retriever = get_routing_retriever()
            if hasattr(retriever, "aclose"):
                await retriever.aclose()
            get_routing_retriever.cache_clear()


def validate_data_readiness(data_mode: DataMode, approved_manifest_path: str | None = None) -> None:
    manifest = Path(approved_manifest_path or get_settings().approved_corpus_manifest_path)
    if data_mode == "production" and not manifest.is_file():
        raise RuntimeError("Production data mode requires an approved corpus manifest")


def initialize_emergency_runtime(data_mode: DataMode, catalog_path: str, release_id: str = "") -> None:
    catalog = Path(catalog_path)
    if not catalog.is_file():
        if data_mode == "production":
            raise RuntimeError("Production emergency corpus is unavailable")
        return
    selected_release = (
        release_id
        or {
            "development": "vmec-development-v2",
            "review": "vmec-review-v2",
            "production": "vmec-production-v1",
        }[data_mode]
    )
    ruleset = compile_emergency_catalog(catalog, release_id=selected_release, mode=data_mode)
    activate_emergency_rules(ruleset)


app = FastAPI(
    title="VMEC-01 API",
    description="Emergency-first specialty routing and appointment platform",
    version="1.0.0",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-CSRF-Token"],
)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")
app.include_router(booking_router, prefix="/api/v1")
app.include_router(operations_router, prefix="/api/v1")
app.include_router(review_router, prefix="/api/v1")
configure_observability(app, settings)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness():
    settings = get_settings()
    persistence = "not_configured"
    if settings.database_url.startswith(("postgresql://", "postgresql+")):
        try:
            with get_engine().connect() as connection:
                migration = connection.scalar(text("SELECT version_num FROM alembic_version"))
                extensions = set(
                    connection.scalars(
                        text("SELECT extname FROM pg_extension WHERE extname IN ('vector','pg_trgm','unaccent')")
                    )
                )
            if migration != "20260803_0008_persistent_import" or extensions != {"vector", "pg_trgm", "unaccent"}:
                raise RuntimeError("persistent schema is incomplete")
            redis = Redis.from_url(settings.redis_url)
            sessions = Redis.from_url(settings.session_redis_url)
            try:
                if not await redis.ping() or not await sessions.ping():
                    raise RuntimeError("persistent cache is unavailable")
            finally:
                await redis.aclose()
                await sessions.aclose()
            persistence = "verified"
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Runtime dependencies unavailable"
            ) from exc
    return {"status": "ready", "persistence": persistence, "emergency_rules": emergency_runtime_status()}
