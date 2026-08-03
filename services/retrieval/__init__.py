"""Retrieval primitives with strictly isolated Gemini embedding spaces."""

from .chunking import CanonicalChunk, canonical_chunks
from .embedding_gateway import GeminiQueryEmbeddingGateway
from .index import InMemoryVectorIndex, VectorHit
from .jobs import EmbeddingJobLedger, EmbeddingPipeline, EmbeddingRecord, JobDiagnostics, JobKey, JobState
from .postgres import (
    PersistentCitation,
    PersistentRetrievalRecord,
    PersistentRetrievalResult,
    PostgresHybridRetriever,
)
from .registry import (
    BackfillPlan,
    Citation,
    CitationRegistry,
    EligibilityDecision,
    EligibilityReason,
    RetrievalCandidate,
    candidate_from_dataset_row,
    plan_embedding_backfill,
    retrieval_eligibility,
)
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
    "GeminiQueryEmbeddingGateway",
    "PRIMARY_EMBEDDING_MODEL",
    "PRIMARY_EMBEDDING_SPACE",
    "PersistentCitation",
    "PersistentRetrievalRecord",
    "PersistentRetrievalResult",
    "PostgresHybridRetriever",
    "TEXT_FALLBACK_EMBEDDING_MODEL",
    "CanonicalChunk",
    "BackfillPlan",
    "Citation",
    "CitationRegistry",
    "EmbeddingJobLedger",
    "EmbeddingPipeline",
    "EmbeddingRecord",
    "EmbeddingSpace",
    "EligibilityDecision",
    "EligibilityReason",
    "HybridRetriever",
    "InMemoryVectorIndex",
    "JobKey",
    "JobDiagnostics",
    "JobState",
    "RetrievalMode",
    "RetrievalCandidate",
    "RetrievalResponse",
    "VectorHit",
    "canonical_chunks",
    "candidate_from_dataset_row",
    "plan_embedding_backfill",
    "retrieval_eligibility",
]
