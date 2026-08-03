"""Deterministic canonical text chunking shared by both embedding spaces."""

import hashlib
import re
from dataclasses import dataclass

_WHITESPACE = re.compile(r"\s+")
_BOUNDARY = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass(frozen=True, slots=True)
class CanonicalChunk:
    chunk_id: str
    record_id: str
    ordinal: int
    text: str
    content_hash: str


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _hard_split(text: str, hard_cap: int) -> list[str]:
    return [text[start : start + hard_cap].strip() for start in range(0, len(text), hard_cap)]


def canonical_chunks(
    record_id: str,
    text: str,
    *,
    target_chars: int = 900,
    hard_cap_chars: int = 1_500,
) -> tuple[CanonicalChunk, ...]:
    """Create stable chunks, preferring sentence boundaries and enforcing a hard cap."""
    if not record_id.strip():
        raise ValueError("record_id must not be empty")
    if target_chars <= 0 or hard_cap_chars <= 0 or target_chars > hard_cap_chars:
        raise ValueError("chunk sizes must satisfy 0 < target_chars <= hard_cap_chars")

    normalized = _normalize(text)
    if not normalized:
        return ()

    units: list[str] = []
    for unit in _BOUNDARY.split(normalized):
        unit = _normalize(unit)
        units.extend(_hard_split(unit, hard_cap_chars) if len(unit) > hard_cap_chars else [unit])

    chunk_texts: list[str] = []
    current: list[str] = []
    current_length = 0
    for unit in units:
        added_length = len(unit) + (1 if current else 0)
        if current and current_length + added_length > target_chars:
            chunk_texts.append(" ".join(current))
            current = []
            current_length = 0
        current.append(unit)
        current_length += len(unit) + (1 if len(current) > 1 else 0)
    if current:
        chunk_texts.append(" ".join(current))

    chunks: list[CanonicalChunk] = []
    for ordinal, chunk_text in enumerate(chunk_texts):
        content_hash = hashlib.sha256(chunk_text.encode("utf-8")).hexdigest()
        identity = f"{record_id}\0{ordinal}\0{content_hash}".encode()
        chunk_id = hashlib.sha256(identity).hexdigest()
        chunks.append(CanonicalChunk(chunk_id, record_id, ordinal, chunk_text, content_hash))
    return tuple(chunks)
