import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.log_redaction import metadata_only_entry, sanitize_value

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_env_example_disables_external_ai_log_submission() -> None:
    values = {}
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key] = value

    assert "AI_LOG_API_KEY" not in values
    assert values["VMEC_AI_LOG_EXTERNAL_SUBMISSION_ENABLED"] == "false"


def test_ai_log_payload_redacts_nested_credentials() -> None:
    payload = {
        "prompt": ("Use ai20k_exampleSecret123, AQ.Ab8RN6IuExampleSecret, and Bearer abcdefghijklmnop"),
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


def test_metadata_only_entry_drops_free_text_and_identity() -> None:
    entry = metadata_only_entry(
        {
            "ts": "2026-08-03T00:00:00+07:00",
            "tool": "codex",
            "event": "turn",
            "prompt": "Patient Nguyen Van A has chest pain",
            "response_summary": "Call this phone number 0900000000",
            "student": "person@example.test",
            "transcript_path": "C:/private/transcript.jsonl",
            "payload_present": True,
            "payload_char_count": 72,
        }
    )

    serialized = str(entry)
    assert entry["payload_present"] is True
    assert "prompt" not in entry
    assert "response_summary" not in entry
    assert "student" not in entry
    assert "transcript_path" not in entry
    assert "Nguyen Van A" not in serialized
    assert "0900000000" not in serialized


def test_hook_normalization_never_persists_prompt_or_tool_payload(monkeypatch) -> None:
    from scripts import log_hook

    monkeypatch.setattr(log_hook, "git", lambda command: "vmec.git")
    entry = log_hook.normalize(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "private-session",
            "tool_name": "Read",
            "tool_input": {
                "content": "Patient Nguyen Van A has chest pain",
                "phone": "0900000000",
            },
            "tool_response": "private medical note",
        },
        "claude",
    )

    assert entry is not None
    assert entry["payload_present"] is True
    serialized = str(entry)
    assert "Nguyen Van A" not in serialized
    assert "0900000000" not in serialized
    assert "private medical note" not in serialized
    assert "private-session" not in serialized


def test_antigravity_entry_never_persists_prompt_or_identity() -> None:
    from scripts.log_antigravity import build_entry

    entry = build_entry(
        {
            "timestamp": "2026-08-03T00:00:00Z",
            "conv_id": "private-conversation",
            "step_index": 7,
            "text": "Patient Nguyen Van A has chest pain",
        },
        repo="vmec",
        branch="security",
        commit="abc123",
        student="person@example.test",
    )

    assert entry["payload_present"] is True
    serialized = str(entry)
    assert "Nguyen Van A" not in serialized
    assert "private-conversation" not in serialized
    assert "person@example.test" not in serialized


def test_external_ai_log_submission_is_disabled_by_default(monkeypatch) -> None:
    import scripts.submit_log as submit_log

    monkeypatch.setattr(submit_log, "EXTERNAL_SUBMISSION_ENABLED", False)
    monkeypatch.setattr(
        submit_log.urllib.request,
        "urlopen",
        lambda *args, **kwargs: pytest.fail("network submission was attempted"),
    )

    with pytest.raises(SystemExit) as exc_info:
        submit_log.main()

    assert exc_info.value.code == 0


@pytest.mark.skipif(os.name == "nt", reason="Uses POSIX executable shims")
def test_pyrun_skips_broken_python3(tmp_path: Path) -> None:
    broken_python3 = tmp_path / "python3"
    broken_python3.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    broken_python3.chmod(0o755)

    working_python = tmp_path / "python"
    working_python.write_text(
        f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n',
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
