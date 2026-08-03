# Embedding rebuild and rollback

The only spaces are `gemini-embedding-2` and `gemini-embedding-001`, each at 768 dimensions. Jobs are deterministic per release/mode/model, checkpointed in PostgreSQL, deduplicated by content hash, and write a model-specific vector for every eligible chunk. Retries store coded errors only; terminal failures enter `embedding_quarantine`.

## Safe preparation

Plan against the ignored local catalog without calling Gemini:

```powershell
.\.venv\Scripts\python.exe scripts\plan_embedding_backfill.py --catalog data\staging\vmec_catalog.sqlite3 --release-id vmec-development-v2 --mode development
```

Apply migrations and verify the persistent release UUID, pgvector extension and current head. Do not infer persistent readiness from offline Alembic SQL.

```powershell
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

## Smoke backfill

Configure `GEMINI_API_KEY` in the runtime secret store without printing it. Set `VMEC_PERSISTENT_PGVECTOR_VERIFIED=true` only after the database checks pass. Smoke is bounded per model:

```powershell
.\.venv\Scripts\python.exe scripts\run_embedding_backfill.py --execution smoke --release-id "<persistent-release-uuid>" --data-mode development --space both --smoke-items 10
```

Verify job counts, vector dimensions, exact model IDs, canonical-source joins and retrieval in each isolated index. Rerun the same command and confirm completed content hashes do not cause new provider calls or duplicate `(chunk_id, model_id)` rows.

## Full backfill

Full execution additionally requires explicit quota/cost authorization and `VMEC_ALLOW_FULL_EMBEDDING_BACKFILL=true`:

```powershell
.\.venv\Scripts\python.exe scripts\run_embedding_backfill.py --execution full --release-id "<persistent-release-uuid>" --data-mode development --space both --batch-limit 10 --rate-limit-seconds 0.2
```

Monitor aggregate `embedding_job_items` states and quarantine codes; do not export text or provider error messages. A nonzero quarantine count requires adjudication and must not be relabeled complete. Production mode remains blocked unless canonical and clinical approval fields satisfy the fail-closed filters.

## Rollback

Stop workers, preserve the failed job diagnostics, and select the last verified release/job metadata. Delete or quarantine only the explicitly identified failed job/vector rows inside a reviewed transaction. Never copy, compare or reuse vectors between model spaces. When either embedding API fails, retrieval uses the peer model's independent index; when both fail, it remains lexical-only and hands off if grounding is insufficient.

Do not set `EMBEDDING_BACKFILL_COMPLETE=true` until both spaces have complete persistent counts and retrieval smoke evidence.
