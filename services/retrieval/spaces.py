"""Authoritative embedding model identifiers and vector-space types."""

from dataclasses import dataclass
from typing import Final, Literal

PRIMARY_EMBEDDING_MODEL: Final = "gemini-embedding-2"
TEXT_FALLBACK_EMBEDDING_MODEL: Final = "gemini-embedding-001"
EMBEDDING_DIMENSIONS: Final = 768

EmbeddingModelId = Literal["gemini-embedding-2", "gemini-embedding-001"]


@dataclass(frozen=True, slots=True)
class EmbeddingSpace:
    """A model-specific vector space that cannot be substituted by dimensions alone."""

    model_id: EmbeddingModelId
    dimensions: int = EMBEDDING_DIMENSIONS

    def __post_init__(self) -> None:
        if self.model_id not in {PRIMARY_EMBEDDING_MODEL, TEXT_FALLBACK_EMBEDDING_MODEL}:
            raise ValueError(f"Forbidden embedding model: {self.model_id}")
        if self.dimensions != EMBEDDING_DIMENSIONS:
            raise ValueError(f"Embedding dimensions must be exactly {EMBEDDING_DIMENSIONS}")


PRIMARY_EMBEDDING_SPACE: Final = EmbeddingSpace(PRIMARY_EMBEDDING_MODEL)
FALLBACK_EMBEDDING_SPACE: Final = EmbeddingSpace(TEXT_FALLBACK_EMBEDDING_MODEL)
