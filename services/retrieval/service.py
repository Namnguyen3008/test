"""Hybrid lexical/vector retrieval with deterministic degradation."""

import re
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .index import InMemoryVectorIndex
from .spaces import FALLBACK_EMBEDDING_SPACE, PRIMARY_EMBEDDING_SPACE, EmbeddingSpace

Vector: TypeAlias = tuple[float, ...]
QueryEmbedder: TypeAlias = Callable[[str, EmbeddingSpace], Awaitable[Vector]]
_TOKEN = re.compile(r"\w+", re.UNICODE)


class RetrievalMode(StrEnum):
    PRIMARY = "lexical+gemini-embedding-2"
    FALLBACK = "lexical+gemini-embedding-001"
    LEXICAL_ONLY = "lexical-only"


@dataclass(frozen=True, slots=True)
class RetrievalResponse:
    record_ids: tuple[str, ...]
    mode: RetrievalMode


class HybridRetriever:
    def __init__(
        self,
        documents: dict[str, str],
        primary_index: InMemoryVectorIndex,
        fallback_index: InMemoryVectorIndex,
        embed_query: QueryEmbedder,
    ) -> None:
        if primary_index.space != PRIMARY_EMBEDDING_SPACE:
            raise ValueError("Primary index has the wrong embedding space")
        if fallback_index.space != FALLBACK_EMBEDDING_SPACE:
            raise ValueError("Fallback index has the wrong embedding space")
        self._documents = dict(documents)
        self._primary_index = primary_index
        self._fallback_index = fallback_index
        self._embed_query = embed_query

    def _lexical(self, query: str) -> tuple[str, ...]:
        query_tokens = {token.casefold() for token in _TOKEN.findall(query)}
        scored: list[tuple[int, str]] = []
        for record_id, text in self._documents.items():
            document_tokens = {token.casefold() for token in _TOKEN.findall(text)}
            overlap = len(query_tokens & document_tokens)
            if overlap:
                scored.append((overlap, record_id))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return tuple(record_id for _, record_id in scored)

    @staticmethod
    def _fuse(rankings: Iterable[Iterable[str]], limit: int) -> tuple[str, ...]:
        scores: dict[str, float] = {}
        for ranking in rankings:
            for rank, record_id in enumerate(ranking, start=1):
                scores[record_id] = scores.get(record_id, 0.0) + 1.0 / (60 + rank)
        ordered = sorted(scores, key=lambda record_id: (-scores[record_id], record_id))
        return tuple(ordered[:limit])

    async def retrieve(self, query: str, *, limit: int = 10) -> RetrievalResponse:
        lexical = self._lexical(query)
        try:
            vector = await self._embed_query(query, PRIMARY_EMBEDDING_SPACE)
            hits = self._primary_index.query(vector, space=PRIMARY_EMBEDDING_SPACE, limit=limit)
            record_ids = self._fuse((lexical, (hit.record_id for hit in hits)), limit)
            return RetrievalResponse(record_ids, RetrievalMode.PRIMARY)
        except Exception:
            pass

        try:
            vector = await self._embed_query(query, FALLBACK_EMBEDDING_SPACE)
            hits = self._fallback_index.query(vector, space=FALLBACK_EMBEDDING_SPACE, limit=limit)
            record_ids = self._fuse((lexical, (hit.record_id for hit in hits)), limit)
            return RetrievalResponse(record_ids, RetrievalMode.FALLBACK)
        except Exception:
            return RetrievalResponse(lexical[:limit], RetrievalMode.LEXICAL_ONLY)
