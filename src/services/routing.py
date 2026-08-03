"""Citation-gated lexical runtime used by the emergency-first agent graph.

The persistent pgvector retriever can replace this adapter without changing the
graph contract. Until that infrastructure is verified, this adapter provides a
safe lexical degradation over retrieval-eligible catalog rows only.
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

from services.retrieval.registry import (
    CitationRegistry,
    DataMode,
    candidate_from_dataset_row,
    retrieval_eligibility,
)
from src.config import get_settings

_TOKEN = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class RoutingRecord:
    record_id: str
    text: str
    specialty_id: str
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoutingContext:
    records: tuple[RoutingRecord, ...]
    mode: str
    allowed_specialty_ids: frozenset[str]

    @property
    def valid_source_ids(self) -> frozenset[str]:
        return frozenset(source_id for record in self.records for source_id in record.source_ids)


class RoutingRetriever(Protocol):
    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext: ...


class CatalogRoutingRetriever:
    """Read-only, PHI-minimized runtime snapshot compiled from the VMEC catalog."""

    def __init__(self, records: tuple[RoutingRecord, ...], specialty_ids: frozenset[str]) -> None:
        self._records = records
        self._specialty_ids = specialty_ids

    @classmethod
    def from_catalog(cls, catalog: Path, *, release_id: str, mode: DataMode) -> CatalogRoutingRetriever:
        if not catalog.is_file():
            return cls((), frozenset())
        connection = sqlite3.connect(f"file:{catalog.resolve().as_posix()}?mode=ro", uri=True)
        try:
            release = connection.execute(
                "SELECT status FROM dataset_releases WHERE release_id=?", (release_id,)
            ).fetchone()
            if release is None or release[0] != "completed":
                return cls((), frozenset())
            ledger = CitationRegistry.from_global_ledger(
                json.loads(raw)
                for (raw,) in connection.execute(
                    "SELECT payload_json FROM global_sources WHERE release_id=?", (release_id,)
                )
            )
            specialty_ids = frozenset(
                specialty_id
                for (raw,) in connection.execute(
                    "SELECT payload_json FROM dataset_rows WHERE release_id=? AND table_name='specialty_reference'",
                    (release_id,),
                )
                if (specialty_id := str(json.loads(raw).get("specialty_code", "")).strip())
            )
            records: list[RoutingRecord] = []
            rows = connection.execute(
                "SELECT row_key,content_hash,payload_json FROM dataset_rows "
                "WHERE release_id=? AND table_name='routing_rows'",
                (release_id,),
            )
            for row_id, content_hash, raw in rows:
                payload = cast(Mapping[str, object], json.loads(raw))
                candidate = candidate_from_dataset_row("routing_rows", row_id, content_hash, payload)
                if not retrieval_eligibility(candidate, mode=mode, citations=ledger).eligible:
                    continue
                specialty_id = str(payload.get("primary_specialty_code", "")).strip()
                if specialty_id not in specialty_ids:
                    continue
                citations = ledger.resolve(candidate.source_ids)
                records.append(
                    RoutingRecord(
                        record_id=str(row_id),
                        text=candidate.text,
                        specialty_id=specialty_id,
                        source_ids=tuple(citation.source_id for citation in citations),
                    )
                )
            return cls(tuple(records), specialty_ids)
        finally:
            connection.close()

    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext:
        query_tokens = {token.casefold() for token in _TOKEN.findall(query)}
        scored: list[tuple[int, str, RoutingRecord]] = []
        for record in self._records:
            tokens = {token.casefold() for token in _TOKEN.findall(record.text)}
            score = len(query_tokens & tokens)
            if score:
                scored.append((score, record.record_id, record))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return RoutingContext(
            tuple(item[2] for item in scored[:limit]),
            "lexical-only",
            self._specialty_ids,
        )


@lru_cache
def get_routing_retriever() -> CatalogRoutingRetriever:
    settings = get_settings()
    release_id = (
        settings.emergency_release_id
        or {
            "development": "vmec-development-v2",
            "review": "vmec-review-v2",
            "production": "vmec-production-v1",
        }[settings.app_data_mode]
    )
    return CatalogRoutingRetriever.from_catalog(
        Path(settings.emergency_catalog_path),
        release_id=release_id,
        mode=settings.app_data_mode,
    )
