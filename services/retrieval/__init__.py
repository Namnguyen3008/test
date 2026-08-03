"""Retrieval primitives with strictly isolated Gemini embedding spaces."""

from .chunking import CanonicalChunk, canonical_chunks
from .index import InMemoryVectorIndex, VectorHit
from .jobs import EmbeddingJobLedger, EmbeddingPipeline, EmbeddingRecord, JobKey
from .service import HybridRetriever, RetrievalMode, RetrievalResponse
from .spaces import (
    EMBEDDING_DIMENSIONS,
    FALLBACK_EMBEDDING_SPACE,
    PRIMARY_EMBEDDING_MODEL,
    PRIMARY_EMBEDDING_SPACE,
    TEXT_FALLBACK_EMBEDDING_MODEL,
    EmbeddingSpace,
)

__all__ = [
    "EMBEDDING_DIMENSIONS",
    "FALLBACK_EMBEDDING_SPACE",
    "PRIMARY_EMBEDDING_MODEL",
    "PRIMARY_EMBEDDING_SPACE",
    "TEXT_FALLBACK_EMBEDDING_MODEL",
    "CanonicalChunk",
    "EmbeddingJobLedger",
    "EmbeddingPipeline",
    "EmbeddingRecord",
    "EmbeddingSpace",
    "HybridRetriever",
    "InMemoryVectorIndex",
    "JobKey",
    "RetrievalMode",
    "RetrievalResponse",
    "VectorHit",
    "canonical_chunks",
]
