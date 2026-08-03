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
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Protocol, cast

from services.retrieval import GeminiQueryEmbeddingGateway, PostgresHybridRetriever
from services.retrieval.registry import (
    CitationRegistry,
    DataMode,
    candidate_from_dataset_row,
    retrieval_eligibility,
)
from src.config import get_settings
from src.persistence.database import get_session_factory

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
    diagnostics: Mapping[str, object] = field(default_factory=dict)

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
            {"adapter": "catalog", "grounded_records": min(len(scored), limit)},
        )


class PostgresRoutingRetriever:
    """Graph adapter for the persistent citation-gated hybrid repository."""

    def __init__(self, retriever: PostgresHybridRetriever, gateway: GeminiQueryEmbeddingGateway) -> None:
        self._retriever = retriever
        self._gateway = gateway

    async def retrieve(self, query: str, *, limit: int = 6) -> RoutingContext:
        result = await self._retriever.retrieve(query, limit=limit)
        records = tuple(
            RoutingRecord(
                record_id=item.record_id,
                text=item.text,
                specialty_id=item.specialty_id,
                source_ids=tuple(citation.source_id for citation in item.citations),
            )
            for item in result.records
        )
        return RoutingContext(
            records,
            result.mode.value,
            frozenset(record.specialty_id for record in records),
            {"adapter": "postgres", **result.diagnostics},
        )

    async def aclose(self) -> None:
        await self._gateway.aclose()


@lru_cache
def get_routing_retriever() -> RoutingRetriever:
    settings = get_settings()
    release_id = (
        settings.emergency_release_id
        or {
            "development": "vmec-development-v2",
            "review": "vmec-review-v2",
            "production": "vmec-production-v1",
        }[settings.app_data_mode]
    )
    postgres_url = settings.database_url.startswith(("postgresql://", "postgresql+"))
    persistent_selected = postgres_url and (
        settings.app_env == "production"
        or settings.retrieval_runtime_mode == "postgres"
        or settings.vmec_persistent_pgvector_verified
    )
    if settings.retrieval_runtime_mode == "postgres" and not postgres_url:
        raise RuntimeError("PostgreSQL retrieval was requested without a PostgreSQL DATABASE_URL")
    if persistent_selected and settings.retrieval_runtime_mode != "lexical":
        gateway = GeminiQueryEmbeddingGateway(settings.gemini_api_key.get_secret_value())
        return PostgresRoutingRetriever(
            PostgresHybridRetriever(
                get_session_factory(),
                gateway.embed_query,
                release_id=release_id,
                data_mode=settings.app_data_mode,
                statement_timeout_ms=settings.retrieval_statement_timeout_ms,
                embedding_timeout_seconds=settings.retrieval_embedding_timeout_seconds,
                candidate_limit=settings.retrieval_candidate_limit,
            ),
            gateway,
        )
    return CatalogRoutingRetriever.from_catalog(
        Path(settings.emergency_catalog_path),
        release_id=release_id,
        mode=settings.app_data_mode,
    )
