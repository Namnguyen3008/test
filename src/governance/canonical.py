"""VMEC's deliberately narrow canonical JSON profile for signed artifacts."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Mapping
from typing import Any

APPROVAL_DOMAIN = b"VMEC\x00governance-approval\x00v1\x00"
RECEIPT_DOMAIN = b"VMEC\x00governance-promotion-receipt\x00v1\x00"


class DuplicateKeyError(ValueError):
    pass


def _pairs_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateKeyError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def strict_json_loads(raw: str) -> dict[str, Any]:
    value = json.loads(
        raw,
        object_pairs_hook=_pairs_without_duplicates,
        parse_float=lambda value: (_ for _ in ()).throw(ValueError(f"floats are forbidden: {value}")),
        parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"non-finite value: {value}")),
    )
    if not isinstance(value, dict):
        raise ValueError("signed artifact must be a JSON object")
    return value


def _normalize(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, str):
        normalized = unicodedata.normalize("NFC", value)
        if any(ord(character) < 32 for character in normalized):
            raise ValueError("control characters are forbidden in signed JSON")
        return normalized
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        normalized_mapping: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key.isascii():
                raise ValueError("signed JSON keys must be ASCII strings")
            normalized_mapping[key] = _normalize(item)
        return normalized_mapping
    raise ValueError(f"unsupported signed JSON type: {type(value).__name__}")


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        _normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def signature_payload(value: Mapping[str, Any], *, receipt: bool = False) -> bytes:
    clone = json.loads(canonical_json(value))
    signature = clone.get("signature")
    if not isinstance(signature, dict) or "value_base64" not in signature:
        raise ValueError("signature envelope is missing")
    signature["value_base64"] = ""
    return (RECEIPT_DOMAIN if receipt else APPROVAL_DOMAIN) + canonical_json(clone)
