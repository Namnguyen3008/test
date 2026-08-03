from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.config import get_settings
from src.security import SecurityHeadersMiddleware
from src.services.llm import get_llm


@asynccontextmanager
async def lifespan(app: FastAPI):
    validate_data_readiness(get_settings().app_data_mode)
    try:
        yield
    finally:
        if get_llm.cache_info().currsize:
            await get_llm().aclose()
            get_llm.cache_clear()


def validate_data_readiness(data_mode: str) -> None:
    if data_mode == "production" and not Path("data/source/APPROVED_CORPUS_MANIFEST.json").is_file():
        raise RuntimeError("Production data mode requires an approved corpus manifest")


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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/ready")
async def readiness():
    return {"status": "ready"}
