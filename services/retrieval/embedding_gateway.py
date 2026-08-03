"""Exact-model Gemini query embeddings without prompt or credential telemetry."""

from __future__ import annotations

import math
from typing import Any

from google import genai
from google.genai import types

from .spaces import (
    EMBEDDING_DIMENSIONS,
    PRIMARY_EMBEDDING_SPACE,
    TEXT_FALLBACK_EMBEDDING_MODEL,
    EmbeddingSpace,
)


class GeminiQueryEmbeddingGateway:
    def __init__(self, api_key: str, *, client: Any | None = None) -> None:
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not configured")
        self._client = client or genai.Client(api_key=api_key)

    async def embed_query(self, query: str, space: EmbeddingSpace) -> tuple[float, ...]:
        if not query.strip():
            raise ValueError("Embedding query must not be empty")
        if space == PRIMARY_EMBEDDING_SPACE:
            contents = f"task: search result | query: {query}"
            config = types.EmbedContentConfig(output_dimensionality=EMBEDDING_DIMENSIONS)
        elif space.model_id == TEXT_FALLBACK_EMBEDDING_MODEL and space.dimensions == EMBEDDING_DIMENSIONS:
            contents = query
            config = types.EmbedContentConfig(
                task_type="RETRIEVAL_QUERY",
                output_dimensionality=EMBEDDING_DIMENSIONS,
            )
        else:
            raise ValueError("Forbidden query embedding space")
        response = await self._client.aio.models.embed_content(
            model=space.model_id,
            contents=contents,
            config=config,
        )
        embeddings = response.embeddings or []
        values = tuple(float(value) for value in (embeddings[0].values or ())) if embeddings else ()
        if len(values) != EMBEDDING_DIMENSIONS or any(not math.isfinite(value) for value in values):
            raise RuntimeError("Embedding provider returned an invalid vector shape")
        return values

    async def aclose(self) -> None:
        aio = getattr(self._client, "aio", None)
        if aio is not None and hasattr(aio, "aclose"):
            await aio.aclose()
        if hasattr(self._client, "close"):
            self._client.close()
