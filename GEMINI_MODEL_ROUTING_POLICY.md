# VMEC-01 — Gemini Model Routing and Embedding Policy

This file is authoritative for all Gemini integration code.

## 1. Allowed model IDs

### Generative

```python
ALLOWED_GENERATIVE_MODELS = (
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash-lite",
)
```

No other generative model may be invoked. Model aliases such as `gemini-flash-latest`, preview IDs, Pro models, or hidden SDK defaults are forbidden.

### Embedding

```python
PRIMARY_EMBEDDING_MODEL = "gemini-embedding-2"
TEXT_FALLBACK_EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768
```

No other embedding model may be invoked.

## 2. Distributed round-robin for chat/routing

### Requirement

The initial model selected for each new logical generative call alternates globally:

```text
request 1 → gemini-3.1-flash-lite
request 2 → gemini-3.5-flash-lite
request 3 → gemini-3.1-flash-lite
request 4 → gemini-3.5-flash-lite
```

This must remain consistent across multiple API replicas and workers.

### Implementation

Use Redis `INCR` on a versioned key, for example:

```text
vmec:gemini:generative:round_robin:v1
```

Selection:

```python
counter = await redis.incr(key)
model = ALLOWED_GENERATIVE_MODELS[(counter - 1) % 2]
```

Do not use an in-memory counter as the authoritative selector.

### Logical-call identity

Create a `model_call_id` and persist/log only non-PHI metadata:

- call ID;
- purpose: intent/routing/rerank/response/summary;
- selected model;
- attempted models;
- status;
- latency;
- token usage when available;
- retry/failover reason;
- trace ID.

Never log prompts or raw patient text in production telemetry.

## 3. Failover behavior

For each logical call:

1. Select initial model by round-robin.
2. Call it with timeout and SDK retry policy bounded by application policy.
3. For transient failures only (`408`, `429`, `5xx`, network timeout):
   - apply exponential backoff with jitter;
   - fail over to the other allowed model when the selected model cannot complete within the request budget.
4. Do not retry/fail over on invalid requests, invalid credentials, semantic validation failure, policy-blocked output, or application bugs without correcting the cause.
5. If both allowed models fail:
   - do not call another model;
   - return deterministic safe response;
   - preserve emergency behavior;
   - create human-handoff/escalation when appropriate.

The round-robin counter advances once for each new logical call, not once per retry attempt.

## 4. Circuit breakers

Maintain per-model health in Redis:

```text
vmec:gemini:model_health:gemini-3.1-flash-lite
vmec:gemini:model_health:gemini-3.5-flash-lite
```

- Closed: normal.
- Open: selected requests immediately fail over to the other allowed model, but the logical round-robin sequence remains unchanged.
- Half-open: limited probes.
- Recovery resumes normal alternating initial selections.

Expose model health in an admin-only diagnostic endpoint and metrics; never expose API credentials.

## 5. Purpose-specific generation policy

Both models may be used for all approved generative purposes:

- input normalization;
- intent classification;
- clarifying-question selection;
- specialty-routing proposal;
- retrieval reranking;
- grounded response assembly;
- conversation summarization;
- notification drafting from allowlisted templates.

For every purpose:

- use structured outputs where applicable;
- validate with Pydantic;
- validate specialty/tool/source IDs against allowlists;
- apply low temperature;
- impose input/output size budgets;
- reject diagnosis/treatment assertions;
- do not directly mutate database state.

## 6. Embedding architecture

### Separate spaces

`gemini-embedding-2` and `gemini-embedding-001` are independent vector spaces even when both output 768 dimensions.

Use a normalized table such as:

```text
knowledge_embeddings
- knowledge_record_id
- model_id
- dimensions
- vector
- content_hash
- embedding_status
- embedded_at
- error_code
```

Create model-specific partial HNSW indexes, or separate tables, for example:

```sql
... WHERE model_id = 'gemini-embedding-2'
... WHERE model_id = 'gemini-embedding-001'
```

Never mix vectors across spaces.

### Indexing policy

- Embed all eligible text and supported multimodal knowledge with `gemini-embedding-2`.
- Embed all eligible text chunks with `gemini-embedding-001` as the text fallback index.
- Use checkpointed, quota-aware background jobs.
- Deduplicate by `(model_id, content_hash, dimensions)`.
- Preserve source/citation mapping independently of embeddings.
- Use task types appropriate for document and query embeddings when supported by the SDK/API.

### Chunking

For text records, create canonical chunks compatible with both models:

- target chunk size based on token count;
- hard cap below the fallback model input limit;
- semantic boundaries first;
- configurable overlap;
- no split that separates a citation/source mapping from the text it supports.

Multimodal assets may have Embedding 2 vectors plus text-extracted chunks for lexical/Embedding 1 fallback when available.

## 7. Query-time retrieval

### Normal path

1. Deterministic emergency gate.
2. PostgreSQL lexical search (`tsvector`, `unaccent`, `pg_trgm`).
3. Query embedding using `gemini-embedding-2`.
4. Search only the Embedding 2 index.
5. Fuse lexical and vector results with reciprocal-rank fusion.
6. Apply metadata/status/safety filters.
7. Rerank using the next allowed generative model selected by the global round-robin service.
8. Validate citation mappings.
9. Generate grounded response.

### Primary embedding degradation

If Embedding 2 fails transiently for a text query:

1. Keep lexical results.
2. Generate query vector with `gemini-embedding-001`.
3. Search only the Embedding 1 index.
4. Fuse lexical and Embedding 1 results.
5. Record degraded mode and metrics.

For non-text queries without a valid text representation, use lexical/metadata fallback or safe human handoff; never send an Embedding 1 vector into the Embedding 2 index.

### Both embedding services unavailable

Use lexical search plus deterministic filters and optional generative reranking only if enough grounded records exist. If grounding is insufficient, do not invent a recommendation; ask clarification or hand off.

## 8. Startup and diagnostics

At startup or through an admin command:

- verify all four exact model IDs are visible to the configured Gemini project;
- verify model capabilities required by the app;
- verify Redis round-robin and health keys;
- verify both vector indexes use the configured dimension;
- fail clearly on unknown/forbidden model configuration;
- never silently substitute another model.

Production readiness fails if required models/indexes are missing, unless an explicitly documented degraded deployment mode is enabled for non-clinical development.

## 9. Tests

Required tests include:

- deterministic alternating initial model selection;
- global alternation across multiple processes/replicas;
- failover uses only the other allowed model;
- no forbidden model ID can pass configuration validation;
- counter increments once per logical call;
- circuit breaker open/half-open/recovery behavior;
- both models failing produces safe handoff;
- Embedding 2 vectors never query Embedding 1 index and vice versa;
- text fallback retrieval works;
- lexical-only degradation works;
- idempotent embedding backfill/resume;
- model telemetry contains no PHI or secrets.
