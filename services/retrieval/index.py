"""In-memory adapter that models strict per-model pgvector indexes."""

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .spaces import EmbeddingSpace


@dataclass(frozen=True, slots=True)
class VectorHit:
    record_id: str
    score: float


class InMemoryVectorIndex:
    """A single-space index; all writes and queries carry an explicit space."""

    def __init__(self, space: EmbeddingSpace) -> None:
        self.space = space
        self._vectors: dict[str, tuple[float, ...]] = {}

    def __len__(self) -> int:
        return len(self._vectors)

    def _validate(self, space: EmbeddingSpace, vector: Sequence[float]) -> None:
        if space != self.space:
            raise ValueError(f"Embedding-space mismatch: index={self.space.model_id}, vector={space.model_id}")
        if len(vector) != self.space.dimensions:
            raise ValueError(f"Vector dimension mismatch: expected {self.space.dimensions}, got {len(vector)}")

    def insert(self, record_id: str, vector: Sequence[float], *, space: EmbeddingSpace) -> None:
        self._validate(space, vector)
        if not record_id:
            raise ValueError("record_id must not be empty")
        self._vectors[record_id] = tuple(float(value) for value in vector)

    def query(
        self,
        vector: Sequence[float],
        *,
        space: EmbeddingSpace,
        limit: int = 10,
    ) -> tuple[VectorHit, ...]:
        self._validate(space, vector)
        if limit <= 0:
            return ()
        query_norm = math.sqrt(sum(value * value for value in vector))
        if query_norm == 0:
            raise ValueError("Query vector must have non-zero magnitude")

        hits: list[VectorHit] = []
        for record_id, candidate in self._vectors.items():
            candidate_norm = math.sqrt(sum(value * value for value in candidate))
            score = 0.0
            if candidate_norm:
                score = sum(left * right for left, right in zip(vector, candidate, strict=True))
                score /= query_norm * candidate_norm
            hits.append(VectorHit(record_id, score))
        hits.sort(key=lambda hit: (-hit.score, hit.record_id))
        return tuple(hits[:limit])
