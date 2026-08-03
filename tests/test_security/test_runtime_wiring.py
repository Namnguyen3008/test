from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def compose_services() -> dict[str, object]:
    document = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    return document["services"]


def test_compose_migrates_before_starting_runtime_processes() -> None:
    services = compose_services()

    assert services["migrate"]["command"] == ["alembic", "upgrade", "head"]
    for component in ("api", "worker", "scheduler"):
        assert services[component]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"


def test_compose_uses_postgres_and_distinct_session_redis_database() -> None:
    services = compose_services()

    for component in ("api", "worker", "scheduler"):
        environment = services[component]["environment"]
        assert environment["RETRIEVAL_RUNTIME_MODE"] == "postgres"
        assert environment["VMEC_PERSISTENT_PGVECTOR_VERIFIED"] == "true"
        assert environment["REDIS_URL"].endswith("/0")
        assert environment["SESSION_REDIS_URL"].endswith("/1")


def test_compose_runs_exactly_one_scheduler_workload() -> None:
    scheduler = compose_services()["scheduler"]

    assert scheduler["command"][:4] == ["celery", "-A", "apps.worker.__main__:app", "beat"]
    assert "--schedule=/tmp/celerybeat-schedule" in scheduler["command"]


def test_helm_wires_runtime_data_session_redis_migrations_and_valid_probes() -> None:
    templates = REPO_ROOT / "infra" / "helm" / "vmec" / "templates"
    deployment = (templates / "deployments.yaml").read_text(encoding="utf-8")
    migration = (templates / "migrations.yaml").read_text(encoding="utf-8")

    assert 'list "api" "web" "worker" "scheduler"' in deployment
    assert "SESSION_REDIS_URL" in deployment
    assert "APPROVED_CORPUS_MANIFEST_PATH" in deployment
    assert "EMERGENCY_CATALOG_PATH" in deployment
    assert "persistentVolumeClaim" in deployment
    assert "tcpSocket: { port: http }" in deployment
    assert "path: /health" not in deployment
    assert '["alembic", "upgrade", "head"]' in migration
    assert "pre-install,pre-upgrade" in migration


def test_helm_has_explicit_tls_ingress_for_web_and_api() -> None:
    ingress = (REPO_ROOT / "infra" / "helm" / "vmec" / "templates" / "ingress.yaml").read_text(encoding="utf-8")

    assert "tlsSecret" in ingress
    assert "vmec-web" in ingress
    assert "vmec-api" in ingress
    assert "apiHost" in ingress
