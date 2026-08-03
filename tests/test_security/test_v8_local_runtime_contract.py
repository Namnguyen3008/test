from pathlib import Path
from subprocess import run

ROOT = Path(__file__).resolve().parents[2]


def test_v8_compose_requires_secret_root_password_and_provisions_login_members() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?" in compose
    assert "provision-roles:" in compose
    assert '"python", "-m", "scripts.provision_local_postgres_roles"' in compose
    assert "provision-roles: { condition: service_completed_successfully }" in compose


def test_v8_secret_store_is_ignored_and_no_secret_template_is_tracked() -> None:
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".secrets/" in ignored
    assert run(["git", "check-ignore", "-q", ".secrets/v8/runtime.env"], cwd=ROOT, check=False).returncode == 0
