import pytest
from fastapi import FastAPI, Response
from httpx import ASGITransport, AsyncClient

from src.security.headers import DEFAULT_SECURITY_HEADERS, SecurityHeadersMiddleware


@pytest.mark.asyncio
async def test_security_headers_are_added_to_http_responses() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    for name, value in DEFAULT_SECURITY_HEADERS.items():
        assert response.headers[name] == value


@pytest.mark.asyncio
async def test_security_headers_do_not_replace_endpoint_policy() -> None:
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/custom")
    async def custom() -> Response:
        return Response(headers={"Content-Security-Policy": "default-src 'self'"})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="https://test") as client:
        response = await client.get("/custom")

    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
