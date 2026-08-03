"""Bounded PostgreSQL FTS/pg_trgm and model-isolated pgvector retrieval."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final, TypeAlias

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session, sessionmaker

from .service import RetrievalMode
from .spaces import EMBEDDING_DIMENSIONS, PRIMARY_EMBEDDING_SPACE, EmbeddingSpace

Vector: TypeAlias = tuple[float, ...]
QueryEmbedder: TypeAlias = Callable[[str, EmbeddingSpace], Awaitable[Vector]]

_ELIGIBLE_TABLES: Final = (
    "adult_emergency_phrases",
    "adult_emergency_rules",
    "maternal_emergency_rules",
    "newborn_rules",
    "pediatric_emergency_rules",
    "postpartum_rules",
    "urgent_exclusions",
    "routing_rows",
    "specialty_reference",
    "clarifying_questions",
    "faq",
    "human_support_content",
    "visit_preparation",
)
_TABLE_SQL: Final = ",".join(f"'{value}'" for value in _ELIGIBLE_TABLES)
_ELIGIBILITY_SQL: Final = f"""
    kr.release_id = :release_id
    AND kr.mode = :data_mode
    AND kr.origin_table IN ({_TABLE_SQL})
    AND coalesce(upper(kr.canonical_status),'') <> 'REJECTED'
    AND coalesce(upper(kr.conflict_status),'') NOT IN ('CONFLICT','REJECTED','BLOCKED')
    AND (
      :data_mode <> 'production'
      OR (
        upper(coalesce(kr.canonical_status,'')) IN ('APPROVED','ACCEPTED','GOLD')
        AND upper(coalesce(kr.review_status,'')) IN ('APPROVED','CLINICALLY_APPROVED')
      )
    )
    AND EXISTS (
      SELECT 1 FROM knowledge_record_sources eligible_krs
      JOIN global_sources eligible_gs ON eligible_gs.id = eligible_krs.source_id
      WHERE eligible_krs.record_id = kr.id
        AND eligible_gs.canonical_url IS NOT NULL
        AND eligible_gs.canonical_url ~ '^(https?://|internal://|//)'
    )
"""

_LEXICAL_SQL: Final = text(
    f"""
    SELECT kr.id::text AS record_id, kc.id::text AS chunk_id, kc.normalized_text,
           coalesce(kr.metadata->>'primary_specialty_code', kr.metadata->>'specialty_code') AS specialty_id,
           greatest(
             ts_rank_cd(kc.search_vector, plainto_tsquery('simple', :query)),
             similarity(kc.normalized_text, :query)
           ) AS score
    FROM knowledge_chunks kc
    JOIN knowledge_records kr ON kr.id = kc.record_id
    WHERE {_ELIGIBILITY_SQL}
      AND (
        kc.search_vector @@ plainto_tsquery('simple', :query)
        OR similarity(kc.normalized_text, :query) >= :trigram_threshold
      )
    ORDER BY score DESC, kr.id, kc.ordinal
    LIMIT :candidate_limit
    """
)

_VECTOR_SQL: Final = text(
    f"""
    SELECT kr.id::text AS record_id, kc.id::text AS chunk_id, kc.normalized_text,
           coalesce(kr.metadata->>'primary_specialty_code', kr.metadata->>'specialty_code') AS specialty_id,
           1 - (ke.embedding <=> cast(:query_vector AS vector(768))) AS score
    FROM knowledge_embeddings ke
    JOIN knowledge_chunks kc ON kc.id = ke.chunk_id
    JOIN knowledge_records kr ON kr.id = kc.record_id
    WHERE {_ELIGIBILITY_SQL}
      AND ke.model_id = :model_id
      AND ke.dimensions = :dimensions
      AND ke.status = 'ready'
    ORDER BY ke.embedding <=> cast(:query_vector AS vector(768)), kr.id, kc.ordinal
    LIMIT :candidate_limit
    """
)

_CITATION_SQL = text(
    """
    SELECT krs.record_id::text AS record_id, gs.id AS source_id,
           gs.canonical_url, coalesce(gs.title,'') AS title,
           coalesce(krs.evidence_locator,'') AS evidence_locator
    FROM knowledge_record_sources krs
    JOIN global_sources gs ON gs.id = krs.source_id
    WHERE krs.record_id IN :record_ids
      AND gs.canonical_url IS NOT NULL
      AND gs.canonical_url ~ '^(https?://|internal://|//)'
    ORDER BY krs.record_id, gs.id, krs.evidence_locator
    """
).bindparams(bindparam("record_ids", expanding=True))


@dataclass(frozen=True, slots=True)
class PersistentCitation:
    source_id: str
    canonical_url: str
    title: str
    locator: str


@dataclass(frozen=True, slots=True)
class PersistentRetrievalRecord:
    record_id: str
    text: str
    specialty_id: str
    citations: tuple[PersistentCitation, ...]


@dataclass(frozen=True, slots=True)
class PersistentRetrievalResult:
    records: tuple[PersistentRetrievalRecord, ...]
    mode: RetrievalMode
    diagnostics: Mapping[str, object]


class PostgresHybridRetriever:
    """Queries each embedding model only through its exact partial-index predicate."""

    def __init__(
        self,
        factory: sessionmaker[Session],
        embed_query: QueryEmbedder,
        *,
        release_id: str,
        data_mode: str,
        statement_timeout_ms: int = 1500,
        embedding_timeout_seconds: float = 8.0,
        candidate_limit: int = 50,
        trigram_threshold: float = 0.2,
    ) -> None:
        if data_mode not in {"development", "review", "production"}:
            raise ValueError("Unsupported retrieval data mode")
        if not 100 <= statement_timeout_ms <= 30_000:
            raise ValueError("Retrieval statement timeout is outside the safe bound")
        if not 1 <= candidate_limit <= 200:
            raise ValueError("Retrieval candidate limit is outside the safe bound")
        self._factory = factory
        self._embed_query = embed_query
        self._release_id = release_id
        self._data_mode = data_mode
        self._statement_timeout_ms = statement_timeout_ms
        self._embedding_timeout_seconds = embedding_timeout_seconds
        self._candidate_limit = candidate_limit
        self._trigram_threshold = trigram_threshold

    @staticmethod
    def _fuse(rankings: Iterable[Iterable[str]], limit: int) -> tuple[str, ...]:
        scores: dict[str, float] = {}
        for ranking in rankings:
            for rank, record_id in enumerate(ranking, start=1):
                scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (60 + rank)
        return tuple(sorted(scores, key=lambda value: (-scores[value], value))[:limit])

    @staticmethod
    def _dedupe_rows(rows: Sequence[Mapping[str, object]]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(row["record_id"]) for row in rows))

    @staticmethod
    def _vector_literal(vector: Sequence[float]) -> str:
        if len(vector) != EMBEDDING_DIMENSIONS or any(not math.isfinite(float(value)) for value in vector):
            raise ValueError("Query embedding must contain exactly 768 finite values")
        return "[" + ",".join(format(float(value), ".9g") for value in vector) + "]"

    def _parameters(self) -> dict[str, object]:
        return {
            "release_id": self._release_id,
            "data_mode": self._data_mode,
            "candidate_limit": self._candidate_limit,
        }

    def _execute(self, statement, parameters: Mapping[str, object]) -> list[Mapping[str, object]]:
        with self._factory() as session, session.begin():
            session.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{self._statement_timeout_ms}ms"},
            )
            return [dict(row) for row in session.execute(statement, dict(parameters)).mappings()]

    def _lexical(self, query: str) -> list[Mapping[str, object]]:
        return self._execute(
            _LEXICAL_SQL,
            {**self._parameters(), "query": query, "trigram_threshold": self._trigram_threshold},
        )

    def _vector(self, vector: Sequence[float], space: EmbeddingSpace) -> list[Mapping[str, object]]:
        return self._execute(
            _VECTOR_SQL,
            {
                **self._parameters(),
                "query_vector": self._vector_literal(vector),
                "model_id": space.model_id,
                "dimensions": space.dimensions,
            },
        )

    def _hydrate(
        self,
        record_ids: tuple[str, ...],
        row_lookup: Mapping[str, Mapping[str, object]],
    ) -> tuple[PersistentRetrievalRecord, ...]:
        if not record_ids:
            return ()
        citation_rows = self._execute(_CITATION_SQL, {"record_ids": record_ids})
        citations: dict[str, list[PersistentCitation]] = {}
        for row in citation_rows:
            citations.setdefault(str(row["record_id"]), []).append(
                PersistentCitation(
                    source_id=str(row["source_id"]),
                    canonical_url=str(row["canonical_url"]),
                    title=str(row["title"]),
                    locator=str(row["evidence_locator"]),
                )
            )
        records: list[PersistentRetrievalRecord] = []
        for record_id in record_ids:
            candidate_row = row_lookup.get(record_id)
            sources = tuple(citations.get(record_id, ()))
            specialty_id = str(candidate_row.get("specialty_id") or "") if candidate_row else ""
            if candidate_row is None or not sources or not specialty_id:
                continue
            records.append(
                PersistentRetrievalRecord(
                    record_id=record_id,
                    text=str(candidate_row["normalized_text"]),
                    specialty_id=specialty_id,
                    citations=sources,
                )
            )
        return tuple(records)

    async def retrieve(self, query: str, *, limit: int = 6) -> PersistentRetrievalResult:
        if not query.strip() or not 1 <= limit <= 20:
            raise ValueError("Retrieval query/limit is outside the safe bound")
        started = time.monotonic()
        lexical_rows = await asyncio.to_thread(self._lexical, query)
        lexical_ids = self._dedupe_rows(lexical_rows)
        selected_rows = list(lexical_rows)
        errors: list[str] = []
        mode = RetrievalMode.LEXICAL_ONLY
        vector_ids: tuple[str, ...] = ()

        for space, candidate_mode in (
            (PRIMARY_EMBEDDING_SPACE, RetrievalMode.PRIMARY),
            (EmbeddingSpace("gemini-embedding-001"), RetrievalMode.FALLBACK),
        ):
            try:
                vector = await asyncio.wait_for(
                    self._embed_query(query, space), timeout=self._embedding_timeout_seconds
                )
                vector_rows = await asyncio.to_thread(self._vector, vector, space)
            except Exception as exc:
                errors.append(f"{space.model_id}:{type(exc).__name__}")
                continue
            vector_ids = self._dedupe_rows(vector_rows)
            selected_rows.extend(vector_rows)
            mode = candidate_mode
            break

        fused_ids = self._fuse((lexical_ids, vector_ids), self._candidate_limit)
        row_lookup = {str(row["record_id"]): row for row in selected_rows}
        records = await asyncio.to_thread(self._hydrate, fused_ids, row_lookup)
        diagnostics: Mapping[str, object] = {
            "mode": mode.value,
            "lexical_candidates": len(lexical_ids),
            "vector_candidates": len(vector_ids),
            "grounded_records": len(records[:limit]),
            "latency_ms": int((time.monotonic() - started) * 1000),
            "degradation_codes": tuple(errors),
        }
        return PersistentRetrievalResult(records[:limit], mode, diagnostics)
