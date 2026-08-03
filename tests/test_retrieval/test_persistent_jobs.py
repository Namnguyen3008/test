from typing import cast

import pytest
from sqlalchemy.orm import Session, sessionmaker

from scripts.run_embedding_backfill import execution_gate
from services.retrieval import (
    EMBEDDING_DIMENSIONS,
    PRIMARY_EMBEDDING_SPACE,
    ClaimedEmbedding,
    PersistentEmbeddingBackfill,
    PersistentJobDiagnostics,
)
from services.retrieval.persistent_jobs import _CLAIM_SQL, _INSERT_EMBEDDINGS_SQL, _PREPARE_ITEMS_SQL
from src.config import Settings


def vector() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * (EMBEDDING_DIMENSIONS - 1)


class ScriptedBackfill(PersistentEmbeddingBackfill):
    def __init__(self, embed_document, claimed):
        super().__init__(cast(sessionmaker[Session], lambda: None), embed_document)
        self.claimed = list(claimed)
        self.completed: list[str] = []
        self.failed: list[str] = []

    def prepare(self, *, release_id, data_mode, space):
        return self.job_id(release_id, data_mode, space)

    def _claim(self, *, job_id, release_id, data_mode, batch_limit):
        values = tuple(self.claimed[:batch_limit])
        del self.claimed[:batch_limit]
        return values

    def _complete(self, *, job_id, release_id, data_mode, space, item, vector):
        self.vector_literal(vector)
        self.completed.append(item.content_hash)

    def _fail(self, *, job_id, space, item, exc):
        self.failed.append(item.content_hash)

    def diagnostics(self, *, job_id, model_id):
        return PersistentJobDiagnostics(
            job_id=job_id,
            model_id=model_id,
            pending=len(self.claimed),
            processing=0,
            failed=len(self.failed),
            complete=len(self.completed),
            quarantined=0,
            attempts=len(self.completed) + len(self.failed),
        )


@pytest.mark.asyncio
async def test_persistent_runner_is_bounded_and_records_safe_failures() -> None:
    calls: list[str] = []

    async def embed(document, space):
        calls.append(document)
        if document == "provider failure":
            raise TimeoutError("must not be persisted")
        return vector()

    records = [
        ClaimedEmbedding("a" * 64, "first grounded document", 1),
        ClaimedEmbedding("b" * 64, "provider failure", 1),
        ClaimedEmbedding("c" * 64, "not reached", 1),
    ]
    runner = ScriptedBackfill(embed, records)
    result = await runner.run(
        release_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        data_mode="development",
        space=PRIMARY_EMBEDDING_SPACE,
        batch_limit=2,
        max_items=2,
    )
    assert calls == ["first grounded document", "provider failure"]
    assert result.complete == 1 and result.failed == 1 and result.pending == 1
    assert runner.completed == ["a" * 64]
    assert runner.failed == ["b" * 64]


def test_persistent_sql_deduplicates_calls_but_writes_each_eligible_chunk() -> None:
    prepare = str(_PREPARE_ITEMS_SQL)
    claim = str(_CLAIM_SQL)
    insert = str(_INSERT_EMBEDDINGS_SQL)
    assert "SELECT DISTINCT" in prepare
    assert "FOR UPDATE SKIP LOCKED" in claim
    assert "GROUP BY claimed.content_hash" in claim
    assert "ON CONFLICT(chunk_id,model_id)" in insert
    for statement in (prepare, claim, insert):
        assert "kr.release_id = :release_id" in statement
        assert "kr.mode = :data_mode" in statement
        assert "knowledge_record_sources" in statement
        assert "canonical_url" in statement
        assert "conflict_status" in statement
        assert "canonical_status" in statement


def test_backfill_execution_gate_is_fail_closed() -> None:
    base = {
        "database_url": "postgresql+psycopg://user:password@localhost/vmec",
        "gemini_api_key": "configured-for-test-only",
        "vmec_persistent_pgvector_verified": True,
    }
    assert execution_gate("smoke", Settings(**base)) == (True, "")
    allowed, reason = execution_gate("full", Settings(**base))
    assert not allowed and "VMEC_ALLOW_FULL" in reason
    assert execution_gate("full", Settings(**base, vmec_allow_full_embedding_backfill=True)) == (True, "")
    allowed, reason = execution_gate(
        "smoke",
        Settings(**{**base, "vmec_persistent_pgvector_verified": False}),
    )
    assert not allowed and "PGVECTOR" in reason


def test_vector_shape_and_job_identity_are_exact() -> None:
    job = PersistentEmbeddingBackfill.job_id(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "development", PRIMARY_EMBEDDING_SPACE
    )
    assert job == PersistentEmbeddingBackfill.job_id(
        "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "development", PRIMARY_EMBEDDING_SPACE
    )
    assert PersistentEmbeddingBackfill.vector_literal(vector()).startswith("[1,")
    with pytest.raises(ValueError, match="768 finite"):
        PersistentEmbeddingBackfill.vector_literal((1.0,))
