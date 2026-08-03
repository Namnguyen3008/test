from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_docker_context_excludes_private_and_runtime_data() -> None:
    patterns = {
        line.strip()
        for line in (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }

    assert {
        ".env",
        ".ai-log/",
        ".codex/",
        "data/",
        "var/",
        "tmp/",
        "*.db",
        "*.sqlite3",
    } <= patterns


def test_compose_drops_privileges_and_uses_read_only_data() -> None:
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "read_only: true" in compose
    assert "cap_drop:" in compose and "- ALL" in compose
    assert "no-new-privileges:true" in compose
    assert "./data:/app/data:ro" in compose
    assert 'user: "10001:10001"' in compose


def test_runtime_image_uses_python_312_and_non_root_user() -> None:
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert dockerfile.count("FROM python:3.12-slim") == 2
    assert "USER appuser" in dockerfile
