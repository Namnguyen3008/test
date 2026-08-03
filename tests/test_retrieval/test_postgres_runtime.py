import asyncio
import math
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy.orm import Session, sessionmaker

from services.retrieval import (
    EMBEDDING_DIMENSIONS,
    FALLBACK_EMBEDDING_SPACE,
    PRIMARY_EMBEDDING_SPACE,
    GeminiQueryEmbeddingGateway,
    PersistentCitation,
    PersistentRetrievalRecord,
    PostgresHybridRetriever,
    RetrievalMode,
)
from services.retrieval.postgres import _LEXICAL_SQL, _VECTOR_SQL
from services.retrieval.spaces import EmbeddingSpace


def vector() -> tuple[float, ...]:
    return (1.0,) + (0.0,) * (EMBEDDING_DIMENSIONS - 1)


class ScriptedRetriever(PostgresHybridRetriever):
    def __init__(self, embed_query, *, vector_failures: set[str] | None = None, embedding_timeout=1.0):
        super().__init__(
            cast(sessionmaker[Session], lambda: None),
            embed_query,
            release_id="release-1",
            data_mode="development",
            embedding_timeout_seconds=embedding_timeout,
        )
        self.vector_failures = vector_failures or set()
        self.spaces: list[EmbeddingSpace] = []

    def _lexical(self, query):
        return [
            {
                "record_id": "lexical",
                "normalized_text": "lexical evidence",
                "specialty_id": "CARDIOLOGY",
            }
        ]

    def _vector(self, values, space):
        self.spaces.append(space)
        if space.model_id in self.vector_failures:
            raise TimeoutError("coded failure only")
        return [
            {
                "record_id": f"vector-{space.model_id}",
                "normalized_text": "vector evidence",
                "specialty_id": "CARDIOLOGY",
            }
        ]

    def _hydrate(self, record_ids, row_lookup):
        citation = PersistentCitation("GLOBAL-1", "https://example.test/source", "Source", "section")
        return tuple(
            PersistentRetrievalRecord(
                record_id=record_id,
                text=str(row_lookup[record_id]["normalized_text"]),
                specialty_id=str(row_lookup[record_id]["specialty_id"]),
                citations=(citation,),
            )
            for record_id in record_ids
            if record_id in row_lookup
        )


def test_sql_contract_has_bounded_filters_citations_and_exact_model_predicate() -> None:
    lexical = str(_LEXICAL_SQL)
    vector_sql = str(_VECTOR_SQL)
    for statement in (lexical, vector_sql):
        assert "kr.release_id = :release_id" in statement
        assert "kr.mode = :data_mode" in statement
        assert "conflict_status" in statement
        assert "knowledge_record_sources" in statement
        assert "canonical_url" in statement
        assert "LIMIT :candidate_limit" in statement
    assert "plainto_tsquery" in lexical and "similarity" in lexical
    assert "ke.model_id = :model_id" in vector_sql
    assert "ke.dimensions = :dimensions" in vector_sql
    assert "vector(768)" in vector_sql
    assert "gemini-embedding-2" not in vector_sql
    assert "gemini-embedding-001" not in vector_sql


def test_vector_binding_rejects_cross_dimension_and_non_finite_values() -> None:
    assert PostgresHybridRetriever._vector_literal(vector()).startswith("[1,")
    with pytest.raises(ValueError, match="768 finite"):
        PostgresHybridRetriever._vector_literal((1.0,))
    invalid = list(vector())
    invalid[2] = math.nan
    with pytest.raises(ValueError, match="768 finite"):
        PostgresHybridRetriever._vector_literal(invalid)


@pytest.mark.asyncio
async def test_primary_path_queries_only_primary_model_space() -> None:
    spaces = []

    async def embed(query, space):
        spaces.append(space)
        return vector()

    retriever = ScriptedRetriever(embed)
    result = await retriever.retrieve("đau ngực")
    assert result.mode is RetrievalMode.PRIMARY
    assert spaces == [PRIMARY_EMBEDDING_SPACE]
    assert retriever.spaces == [PRIMARY_EMBEDDING_SPACE]
    assert result.records


@pytest.mark.asyncio
async def test_primary_failure_queries_only_fallback_space_then_fuses_lexical() -> None:
    spaces = []

    async def embed(query, space):
        spaces.append(space)
        if space == PRIMARY_EMBEDDING_SPACE:
            raise TimeoutError("primary unavailable")
        return vector()

    retriever = ScriptedRetriever(embed)
    result = await retriever.retrieve("đau ngực")
    assert result.mode is RetrievalMode.FALLBACK
    assert spaces == [PRIMARY_EMBEDDING_SPACE, FALLBACK_EMBEDDING_SPACE]
    assert retriever.spaces == [FALLBACK_EMBEDDING_SPACE]
    assert {item.record_id for item in result.records} == {
        "lexical",
        "vector-gemini-embedding-001",
    }


@pytest.mark.asyncio
async def test_embedding_timeouts_degrade_to_lexical_without_leaking_query() -> None:
    secret_query = "private symptom text must not enter diagnostics"

    async def slow_embed(query, space):
        await asyncio.sleep(0.02)
        return vector()

    retriever = ScriptedRetriever(slow_embed, embedding_timeout=0.001)
    result = await retriever.retrieve(secret_query)
    assert result.mode is RetrievalMode.LEXICAL_ONLY
    assert [item.record_id for item in result.records] == ["lexical"]
    assert secret_query not in str(result.diagnostics)
    assert result.diagnostics["degradation_codes"] == (
        "gemini-embedding-2:TimeoutError",
        "gemini-embedding-001:TimeoutError",
    )


class FakeEmbeddingModels:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def embed_content(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(embeddings=[SimpleNamespace(values=vector())])


@pytest.mark.asyncio
async def test_gateway_uses_exact_models_and_model_specific_query_instructions() -> None:
    models = FakeEmbeddingModels()
    client = SimpleNamespace(aio=SimpleNamespace(models=models))
    gateway = GeminiQueryEmbeddingGateway("configured-secret-not-returned", client=client)
    await gateway.embed_query("đau ngực", PRIMARY_EMBEDDING_SPACE)
    await gateway.embed_query("đau ngực", FALLBACK_EMBEDDING_SPACE)

    assert [call["model"] for call in models.calls] == [
        "gemini-embedding-2",
        "gemini-embedding-001",
    ]
    assert models.calls[0]["contents"].startswith("task: search result | query:")
    assert models.calls[0]["config"].task_type is None
    assert models.calls[1]["contents"] == "đau ngực"
    assert models.calls[1]["config"].task_type == "RETRIEVAL_QUERY"
    assert all(call["config"].output_dimensionality == 768 for call in models.calls)


@pytest.mark.asyncio
async def test_gateway_rejects_unknown_space_and_invalid_provider_shape() -> None:
    models = FakeEmbeddingModels()
    models.embed_content = lambda **kwargs: None  # type: ignore[method-assign]
    gateway = GeminiQueryEmbeddingGateway(
        "configured-secret-not-returned",
        client=SimpleNamespace(aio=SimpleNamespace(models=models)),
    )
    with pytest.raises(ValueError, match="Forbidden"):
        await gateway.embed_query("query", SimpleNamespace(model_id="forbidden", dimensions=768))  # type: ignore[arg-type]
