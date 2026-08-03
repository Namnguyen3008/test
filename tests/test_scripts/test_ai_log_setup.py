import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.log_redaction import sanitize_value

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_example_uses_ai_log_placeholder() -> None:
    values = {}
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value

    assert values["AI_LOG_API_KEY"] == "ai20k_your-key-here"


def test_ai_log_payload_redacts_nested_credentials() -> None:
    payload = {
        "prompt": (
            "Use ai20k_exampleSecret123, AQ.Ab8RN6IuExampleSecret, "
            "and Bearer abcdefghijklmnop"
        ),
        "tool_input": {
            "API_KEY": "top-secret-value",
            "command": "export GITHUB_TOKEN=ghp_exampleSecret123",
        },
    }

    clean = sanitize_value(payload)
    serialized = str(clean)

    assert "exampleSecret123" not in serialized
    assert "abcdefghijklmnop" not in serialized
    assert "top-secret-value" not in serialized
    assert "Ab8RN6IuExampleSecret" not in serialized
    assert serialized.count("[REDACTED]") >= 3


@pytest.mark.skipif(os.name == "nt", reason="Uses POSIX executable shims")
def test_pyrun_skips_broken_python3(tmp_path: Path) -> None:
    broken_python3 = tmp_path / "python3"
    broken_python3.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    broken_python3.chmod(0o755)

    working_python = tmp_path / "python"
    working_python.write_text(
        f"#!/bin/sh\nexec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    working_python.chmod(0o755)

    env = os.environ.copy()
    env["PATH"] = f"{tmp_path}{os.pathsep}{env['PATH']}"
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "scripts" / "_pyrun.sh"),
            "-c",
            "print('PYRUN_OK')",
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "PYRUN_OK"


@pytest.mark.skipif(os.name != "nt", reason="Windows PowerShell regression test")
def test_windows_hook_is_bomless_and_executable(tmp_path: Path) -> None:
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        [
            "powershell",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(REPO_ROOT / "scripts" / "setup_hooks.ps1"),
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    hook_path_text = subprocess.run(
        ["git", "rev-parse", "--git-path", "hooks/pre-push"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    hook_path = Path(hook_path_text)
    if not hook_path.is_absolute():
        hook_path = tmp_path / hook_path

    hook_bytes = hook_path.read_bytes()
    assert hook_bytes.startswith(b"#!/usr/bin/env bash\n")
    assert not hook_bytes.startswith(b"\xef\xbb\xbf")
    assert b"\r\n" not in hook_bytes

    result = subprocess.run(
        ["git", "hook", "run", "pre-push"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
