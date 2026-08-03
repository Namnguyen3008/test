"""Resumable, idempotent embedding job primitives."""

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .index import InMemoryVectorIndex
from .spaces import EmbeddingSpace

Vector: TypeAlias = tuple[float, ...]
EmbedFunction: TypeAlias = Callable[[str, EmbeddingSpace], Awaitable[Vector]]


@dataclass(frozen=True, slots=True)
class JobKey:
    model_id: str
    content_hash: str
    dimensions: int


@dataclass(frozen=True, slots=True)
class EmbeddingRecord:
    record_id: str
    text: str
    content_hash: str


class JobState(StrEnum):
    STARTED = "started"
    COMPLETE = "complete"
    FAILED = "failed"


class EmbeddingJobLedger:
    """Checkpoint ledger keyed exactly by model, content hash, and dimensions."""

    def __init__(self) -> None:
        self._states: dict[JobKey, JobState] = {}
        self._vectors: dict[JobKey, Vector] = {}

    @staticmethod
    def key(space: EmbeddingSpace, content_hash: str) -> JobKey:
        return JobKey(space.model_id, content_hash, space.dimensions)

    def is_complete(self, key: JobKey) -> bool:
        return self._states.get(key) is JobState.COMPLETE

    def start(self, key: JobKey) -> bool:
        if self.is_complete(key):
            return False
        self._states[key] = JobState.STARTED
        return True

    def completed_vector(self, key: JobKey) -> Vector | None:
        if not self.is_complete(key):
            return None
        return self._vectors[key]

    def complete(self, key: JobKey, vector: Vector) -> None:
        self._vectors[key] = vector
        self._states[key] = JobState.COMPLETE

    def fail(self, key: JobKey) -> None:
        self._states[key] = JobState.FAILED


class EmbeddingPipeline:
    def __init__(self, ledger: EmbeddingJobLedger, embed: EmbedFunction) -> None:
        self._ledger = ledger
        self._embed = embed

    async def build(
        self,
        records: Iterable[EmbeddingRecord],
        *,
        space: EmbeddingSpace,
        index: InMemoryVectorIndex,
    ) -> int:
        if index.space != space:
            raise ValueError("Pipeline target index does not match requested embedding space")

        completed = 0
        for record in records:
            key = self._ledger.key(space, record.content_hash)
            cached_vector = self._ledger.completed_vector(key)
            if cached_vector is not None:
                index.insert(record.record_id, cached_vector, space=space)
                continue
            if not self._ledger.start(key):
                continue
            try:
                vector = await self._embed(record.text, space)
                index.insert(record.record_id, vector, space=space)
            except Exception:
                self._ledger.fail(key)
                raise
            self._ledger.complete(key, vector)
            completed += 1
        return completed
