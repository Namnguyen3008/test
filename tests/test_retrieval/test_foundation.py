import hashlib

import pytest

from services.retrieval import (
    EMBEDDING_DIMENSIONS,
    FALLBACK_EMBEDDING_SPACE,
    PRIMARY_EMBEDDING_SPACE,
    EmbeddingJobLedger,
    EmbeddingPipeline,
    EmbeddingRecord,
    HybridRetriever,
    InMemoryVectorIndex,
    JobState,
    RetrievalMode,
    canonical_chunks,
)


def vector(axis: int = 0) -> tuple[float, ...]:
    values = [0.0] * EMBEDDING_DIMENSIONS
    values[axis] = 1.0
    return tuple(values)


def test_indexes_reject_cross_space_insertion_and_query() -> None:
    primary = InMemoryVectorIndex(PRIMARY_EMBEDDING_SPACE)

    with pytest.raises(ValueError, match="Embedding-space mismatch"):
        primary.insert("record", vector(), space=FALLBACK_EMBEDDING_SPACE)
    primary.insert("record", vector(), space=PRIMARY_EMBEDDING_SPACE)
    with pytest.raises(ValueError, match="Embedding-space mismatch"):
        primary.query(vector(), space=FALLBACK_EMBEDDING_SPACE)
    with pytest.raises(ValueError, match="dimension mismatch"):
        primary.query((1.0,), space=PRIMARY_EMBEDDING_SPACE)


def test_canonical_chunking_is_stable_and_hard_capped() -> None:
    text = "  Câu đầu tiên.   Câu thứ hai dài hơn!  " + "x" * 30
    first = canonical_chunks("record-1", text, target_chars=20, hard_cap_chars=25)
    second = canonical_chunks("record-1", text, target_chars=20, hard_cap_chars=25)

    assert first == second
    assert all(len(chunk.text) <= 25 for chunk in first)
    assert len({chunk.chunk_id for chunk in first}) == len(first)


@pytest.mark.asyncio
async def test_embedding_jobs_resume_without_duplicate_embedding() -> None:
    calls: list[str] = []
    fail_once = True

    async def embed(text, space):
        nonlocal fail_once
        calls.append(text)
        if text == "second" and fail_once:
            fail_once = False
            raise TimeoutError("interrupted")
        return vector()

    records = [
        EmbeddingRecord("one", "first", hashlib.sha256(b"first").hexdigest()),
        EmbeddingRecord("two", "second", hashlib.sha256(b"second").hexdigest()),
    ]
    ledger = EmbeddingJobLedger()
    pipeline = EmbeddingPipeline(ledger, embed)
    index = InMemoryVectorIndex(PRIMARY_EMBEDDING_SPACE)

    with pytest.raises(TimeoutError, match="interrupted"):
        await pipeline.build(records, space=PRIMARY_EMBEDDING_SPACE, index=index)
    completed = await pipeline.build(records, space=PRIMARY_EMBEDDING_SPACE, index=index)

    assert completed == 1
    assert calls == ["first", "second", "second"]
    assert len(index) == 2


@pytest.mark.asyncio
async def test_repeated_embedding_failure_is_quarantined_with_phi_safe_diagnostics() -> None:
    async def embed(text, space):
        raise TimeoutError("upstream unavailable")

    record = EmbeddingRecord("one", "sensitive text must not enter diagnostics", hashlib.sha256(b"one").hexdigest())
    ledger = EmbeddingJobLedger()
    pipeline = EmbeddingPipeline(ledger, embed, max_attempts=2)
    index = InMemoryVectorIndex(PRIMARY_EMBEDDING_SPACE)

    for _ in range(2):
        with pytest.raises(TimeoutError):
            await pipeline.build([record], space=PRIMARY_EMBEDDING_SPACE, index=index)
    assert await pipeline.build([record], space=PRIMARY_EMBEDDING_SPACE, index=index) == 0

    key = ledger.key(PRIMARY_EMBEDDING_SPACE, record.content_hash)
    diagnostics = ledger.diagnostics()
    assert ledger.attempts(key) == 2
    assert diagnostics.quarantined == 1
    assert diagnostics.attempts == 2
    assert JobState.QUARANTINED.value not in record.text


@pytest.mark.asyncio
async def test_duplicate_content_is_embedded_once_but_maps_every_record() -> None:
    calls = 0

    async def embed(text, space):
        nonlocal calls
        calls += 1
        return vector()

    content_hash = hashlib.sha256(b"shared").hexdigest()
    records = [
        EmbeddingRecord("one", "shared", content_hash),
        EmbeddingRecord("two", "shared", content_hash),
    ]
    index = InMemoryVectorIndex(PRIMARY_EMBEDDING_SPACE)
    pipeline = EmbeddingPipeline(EmbeddingJobLedger(), embed)

    await pipeline.build(records, space=PRIMARY_EMBEDDING_SPACE, index=index)

    assert calls == 1
    assert len(index) == 2


@pytest.mark.asyncio
async def test_job_identity_includes_model_and_dimensions() -> None:
    calls = []

    async def embed(text, space):
        calls.append(space.model_id)
        return vector()

    record = EmbeddingRecord("one", "same", hashlib.sha256(b"same").hexdigest())
    ledger = EmbeddingJobLedger()
    pipeline = EmbeddingPipeline(ledger, embed)
    await pipeline.build(
        [record],
        space=PRIMARY_EMBEDDING_SPACE,
        index=InMemoryVectorIndex(PRIMARY_EMBEDDING_SPACE),
    )
    await pipeline.build(
        [record],
        space=FALLBACK_EMBEDDING_SPACE,
        index=InMemoryVectorIndex(FALLBACK_EMBEDDING_SPACE),
    )

    assert calls == [PRIMARY_EMBEDDING_SPACE.model_id, FALLBACK_EMBEDDING_SPACE.model_id]


def configured_indexes():
    primary = InMemoryVectorIndex(PRIMARY_EMBEDDING_SPACE)
    fallback = InMemoryVectorIndex(FALLBACK_EMBEDDING_SPACE)
    primary.insert("primary-vector", vector(), space=PRIMARY_EMBEDDING_SPACE)
    fallback.insert("fallback-vector", vector(), space=FALLBACK_EMBEDDING_SPACE)
    return primary, fallback


@pytest.mark.asyncio
async def test_normal_retrieval_queries_only_primary_index() -> None:
    primary, fallback = configured_indexes()
    spaces = []

    async def embed_query(query, space):
        spaces.append(space)
        return vector()

    retriever = HybridRetriever({"lexical": "đau ngực"}, primary, fallback, embed_query)
    result = await retriever.retrieve("đau ngực")

    assert result.mode is RetrievalMode.PRIMARY
    assert spaces == [PRIMARY_EMBEDDING_SPACE]
    assert "primary-vector" in result.record_ids
    assert "fallback-vector" not in result.record_ids


@pytest.mark.asyncio
async def test_primary_failure_uses_only_text_fallback_index() -> None:
    primary, fallback = configured_indexes()
    spaces = []

    async def embed_query(query, space):
        spaces.append(space)
        if space == PRIMARY_EMBEDDING_SPACE:
            raise TimeoutError("primary unavailable")
        return vector()

    retriever = HybridRetriever({"lexical": "đau ngực"}, primary, fallback, embed_query)
    result = await retriever.retrieve("đau ngực")

    assert result.mode is RetrievalMode.FALLBACK
    assert spaces == [PRIMARY_EMBEDDING_SPACE, FALLBACK_EMBEDDING_SPACE]
    assert "fallback-vector" in result.record_ids
    assert "primary-vector" not in result.record_ids


@pytest.mark.asyncio
async def test_both_embedding_failures_degrade_to_lexical_only() -> None:
    primary, fallback = configured_indexes()

    async def embed_query(query, space):
        raise TimeoutError(space.model_id)

    retriever = HybridRetriever(
        {"matching": "đau ngực", "not-matching": "khám mắt"},
        primary,
        fallback,
        embed_query,
    )
    result = await retriever.retrieve("đau ngực")

    assert result.mode is RetrievalMode.LEXICAL_ONLY
    assert result.record_ids == ("matching",)
