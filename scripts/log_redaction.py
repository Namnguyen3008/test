"""Privacy helpers for local, metadata-only AI activity logs."""

import re
from typing import Any

_METADATA_KEYS = frozenset(
    {
        "ts",
        "tool",
        "event",
        "entry_id",
        "model",
        "repo",
        "branch",
        "commit",
        "payload_present",
        "payload_char_count",
    }
)

_SECRET_KEY = re.compile(r"(?i)(?:key|token|secret|password|authorization)")
_SECRET_PATTERNS = (
    re.compile(r"\bai20k_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\b21st_sk_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bghp_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"\bAQ\.[A-Za-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
    re.compile(
        r"(?i)\b([A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)"
        r"(\s*[:=]\s*)[^\s,;]+"
    ),
)


def redact_text(value: str, limit: int = 4000) -> str:
    """Replace common credential forms while keeping useful prompt context."""
    redacted = value
    for pattern in _SECRET_PATTERNS:
        if pattern.groups == 2:
            redacted = pattern.sub(r"\1\2[REDACTED]", redacted)
        else:
            redacted = pattern.sub("[REDACTED]", redacted)
    return redacted[:limit]


def sanitize_value(value: Any, depth: int = 0) -> Any:
    """Recursively redact secrets and cap nested external-tool payloads."""
    if depth > 6:
        return "[TRUNCATED]"
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        clean = {}
        for key, item in list(value.items())[:100]:
            clean[key] = "[REDACTED]" if _SECRET_KEY.search(str(key)) else sanitize_value(item, depth + 1)
        return clean
    if isinstance(value, list):
        return [sanitize_value(item, depth + 1) for item in value[:100]]
    if isinstance(value, tuple):
        return tuple(sanitize_value(item, depth + 1) for item in value[:100])
    return value


def metadata_only_entry(value: dict[str, Any]) -> dict[str, Any]:
    """Return an allowlisted event record that cannot contain prompt or PHI text.

    Redaction is deliberately not the privacy boundary: free-form medical text
    cannot be made safe using credential regular expressions. Producers must
    persist only this small, non-user-content metadata schema.
    """
    return {
        key: sanitize_value(item)
        for key, item in value.items()
        if key in _METADATA_KEYS
    }
