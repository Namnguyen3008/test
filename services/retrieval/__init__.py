"""Retrieval primitives with strictly isolated Gemini embedding spaces."""

from .chunking import CanonicalChunk, canonical_chunks
from .embedding_gateway import GeminiQueryEmbeddingGateway
from .index import InMemoryVectorIndex, VectorHit
from .jobs import EmbeddingJobLedger, EmbeddingPipeline, EmbeddingRecord, JobDiagnostics, JobKey, JobState
from .persistent_import import (
    CatalogProjection,
    PersistentCatalogImporter,
    PersistentImportResult,
    PersistentRecordProjection,
    PersistentSource,
)
from .persistent_jobs import ClaimedEmbedding, PersistentEmbeddingBackfill, PersistentJobDiagnostics
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
    GovernanceClassification,
    RetrievalCandidate,
    candidate_from_dataset_row,
    governance_classification,
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
    "PersistentEmbeddingBackfill",
    "PersistentCatalogImporter",
    "PersistentImportResult",
    "PersistentRecordProjection",
    "PersistentSource",
    "CatalogProjection",
    "PersistentJobDiagnostics",
    "ClaimedEmbedding",
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
    "GovernanceClassification",
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
    "governance_classification",
    "plan_embedding_backfill",
    "retrieval_eligibility",
]
