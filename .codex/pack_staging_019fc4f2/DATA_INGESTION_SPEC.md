# VMEC-01 — Data Ingestion and Dual-Embedding Specification

## 1. Immutable source artifacts

Expected under `data/source/`:

```text
VMEC_FULL_DATA_DEVELOPMENT_READY.zip
VMEC_FULL_DATA_RESEARCH_MASTER.zip
VMEC_GLOBAL_SOURCE_LEDGER.csv.gz
VMEC_FULL_DATA_MASTER_INDEX.xlsx
```

Never edit or overwrite them. Record SHA-256 before import.

## 2. Intended use

- `DEVELOPMENT_READY`: conflict-free runtime corpus for development/testing; not clinically approved.
- `RESEARCH_MASTER`: reviewer/conflict/audit corpus; not patient-facing.
- `GLOBAL_SOURCE_LEDGER`: canonical citations.
- `MASTER_INDEX`: inventory and consolidation QA.

## 3. Import CLI

Implement an idempotent CLI similar to:

```powershell
uv run python -m vmec_data import `
  --development-zip data/source/VMEC_FULL_DATA_DEVELOPMENT_READY.zip `
  --research-zip data/source/VMEC_FULL_DATA_RESEARCH_MASTER.zip `
  --source-ledger data/source/VMEC_GLOBAL_SOURCE_LEDGER.csv.gz `
  --master-index data/source/VMEC_FULL_DATA_MASTER_INDEX.xlsx `
  --mode development `
  --resume
```

Options:

- `--dry-run`
- `--resume`
- `--release-id`
- `--table`
- `--mode development|review|production`
- `--rebuild-embeddings primary|fallback|all`
- `--skip-embeddings`
- `--max-workers`
- `--report-dir`

## 4. Streaming and validation

- Stream ZIP and `.csv.gz`; do not load the corpus into RAM.
- Use Polars/PyArrow or efficient streaming equivalents.
- Validate headers/types/IDs/statuses/citations.
- Preserve origin file, table, row ID, batch, review/conflict status, content hash and uncommon fields.
- Use staging tables and bounded transactions.
- Quarantine malformed/unsupported records with reasons.
- Never infer clinical approval.
- Escape spreadsheet formula-injection characters in generated reports.
- Scan for secrets and likely PII/PHI; quarantine findings rather than silently dropping them.
- Produce machine-readable JSON and human-readable Markdown reports.

## 5. Database schema

At minimum:

- `dataset_releases`
- `dataset_files`
- `dataset_import_jobs`
- `dataset_quarantine`
- `global_sources`
- `knowledge_records`
- `knowledge_record_sources`
- `knowledge_chunks`
- `knowledge_embeddings`
- `embedding_jobs`
- `embedding_job_items`
- `emergency_rules`
- `routing_examples`
- `clarifying_questions`
- `faq_entries`
- `notification_templates`
- `evaluation_cases`
- `security_test_cases`
- `synthetic_profiles`

Use JSONB to preserve uncommon columns while promoting frequently queried fields to typed columns.

## 6. Classification

Classify all domain files, not a hard-coded handful:

- emergency/safety;
- routing/clarification;
- language/NLU;
- conversations/booking;
- content/policies/notifications;
- evaluation/security;
- synthetic profiles/history/analytics;
- source/provenance metadata.

Generate a classification report and fail/quarantine unknown critical tables instead of ignoring them.

## 7. Citation import

- Normalize global source IDs and canonical URLs.
- Preserve evidence locator, role, grade, applicability, localization and review status.
- Build many-to-many row/source mappings.
- Do not invent missing sources.
- Runtime records without valid citation mappings cannot produce grounded clinical recommendations.

## 8. Canonical text chunks

Text chunks must support both embedding models:

- semantic boundary-aware splitting;
- hard cap below the fallback model's text input limit;
- configurable target/overlap;
- stable chunk IDs and content hashes;
- retain record/source mapping;
- no split that detaches an evidence statement from its citation context;
- separate runtime, evaluation-hidden and research-only scopes.

## 9. Dual embedding pipeline

### Primary

- Model: `gemini-embedding-2`
- Dimension: `768`
- Eligible: all text and supported multimodal knowledge.

### Text fallback

- Model: `gemini-embedding-001`
- Dimension: `768`
- Eligible: all text chunks.

### Rules

- Store each vector with exact `model_id`, dimensions and content hash.
- Separate HNSW indexes by model ID.
- Never mix spaces.
- Idempotency key: `(model_id, dimensions, content_hash)`.
- Use checkpoint/resume and quota-aware scheduling.
- Use exponential backoff and jitter for transient API errors.
- Respect API quotas and cap concurrency per model.
- Do not send PHI-bearing research rows to an external model unless the selected data mode and policy explicitly allow it. Source corpus is synthetic/research by default, but still apply data classification.
- Record only non-sensitive error metadata.

## 10. Retrieval indexes

- GIN FTS index on normalized Vietnamese text.
- `pg_trgm` indexes for typo/no-diacritic lookup.
- HNSW cosine index for Embedding 2.
- Independent HNSW cosine index for Embedding 1.
- Metadata indexes for status, mode, specialty, age, safety class, language, origin table and source.

## 11. Production gating

- Development mode may import conflict-free development rows and must expose warnings.
- Review mode may import research rows into restricted reviewer tables.
- Production mode imports only rows with verified approval evidence, no conflicts and valid citations.
- Production import fails closed if the approved corpus is absent.

## 12. Import reports

Report:

- source file hashes;
- rows by table/status/mode;
- quarantined rows and reasons;
- citation coverage;
- missing/conflicting source mappings;
- duplicate/content-hash stats;
- chunks produced;
- primary/fallback embedding counts;
- embedding failures/retries/backlog;
- index status;
- data-mode readiness;
- reproducibility metadata.

## 13. Tests

- streaming memory bound;
- idempotent rerun;
- interrupted-job resume;
- malformed row quarantine;
- citation FK validation;
- hidden-test isolation;
- production fail-closed;
- duplicate content not re-embedded;
- both embedding indexes populated independently;
- fallback model input limits respected;
- no cross-space retrieval;
- generated reports have no spreadsheet formula/reference errors.
