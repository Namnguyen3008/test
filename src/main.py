from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router
from src.config import get_settings
from src.security import SecurityHeadersMiddleware
from src.services.llm import get_llm


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        yield
    finally:
        if get_llm.cache_info().currsize:
            await get_llm().aclose()
            get_llm.cache_clear()


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
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "env": settings.app_env}
