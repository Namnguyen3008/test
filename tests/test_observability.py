import logging

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest.mark.asyncio
async def test_metrics_endpoint_exposes_aggregate_http_metrics() -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/health")).status_code == 200
        metrics = await client.get("/metrics/")
    assert metrics.status_code == 200
    assert "vmec_http_requests_total" in metrics.text


@pytest.mark.asyncio
async def test_request_telemetry_excludes_body_query_and_concrete_identifier(caplog) -> None:
    secret_phrase = "patient-secret-symptom-9f4c"
    concrete_id = "10000000-0000-0000-0000-000000000001"
    caplog.set_level(logging.INFO, logger="vmec.request")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            f"/api/v1/chat?patient_id={concrete_id}",
            json={"message": secret_phrase},
        )
    assert response.status_code == 200
    logs = "\n".join(record.getMessage() for record in caplog.records if record.name == "vmec.request")
    assert '"route":"/api/v1/chat"' in logs
    assert secret_phrase not in logs
    assert concrete_id not in logs
    assert "patient_id" not in logs
