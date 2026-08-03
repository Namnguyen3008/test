# VMEC-01

Production-oriented Vietnamese emergency-first specialty routing and appointment platform. The repository contains a Next.js patient/operations portal, FastAPI API, Celery worker, PostgreSQL/pgvector and Redis platform, streaming importer, independent Gemini embedding spaces, distributed Gemini model rotation, booking/privacy primitives, tests, Docker Compose and Helm artifacts.

This software supports specialty navigation; it does not diagnose, prescribe or replace a clinician. Production data mode fails closed until an approved corpus manifest is supplied.

## Prerequisites

- Python 3.12+
- Node.js 22+
- Docker with Compose for the complete platform
- `GEMINI_API_KEY` supplied outside Git for live model diagnostics and AI calls

## Prepare immutable data

```powershell
Set-ExecutionPolicy -Scope Process Bypass
.\PREPARE_VMEC_PROJECT.ps1 `
  -RepoPath "D:\ALL ABOUT PROJECT\PROJECT\P-208" `
  -SourceDataDir "D:\ALL ABOUT PROJECT\SOURCE_DATASET"
```

The four private artifacts are copied to ignored `data/source/`, verified by SHA-256 and recorded in a local manifest.

## Local platform

Copy `.env.example` to `.env`, supply secrets without committing them, then:

```powershell
docker compose up --build
```

Services are available at `http://localhost:3000` (web) and `http://localhost:8000` (API/OpenAPI). The API, worker and web run non-root with hardened container settings; PostgreSQL enables vector, trigram and unaccent extensions.

## Import both data modes

```powershell
python -m vmec_data import `
  --development-zip data/source/VMEC_FULL_DATA_DEVELOPMENT_READY.zip `
  --research-zip data/source/VMEC_FULL_DATA_RESEARCH_MASTER.zip `
  --source-ledger data/source/VMEC_GLOBAL_SOURCE_LEDGER.csv.gz `
  --master-index data/source/VMEC_FULL_DATA_MASTER_INDEX.xlsx `
  --mode development --resume --skip-embeddings
```

Use `--mode review` for the restricted research corpus. Production mode intentionally rejects the current corpus because it contains no production-approved rows. Embedding builds require the live Gemini project and preserve independent `gemini-embedding-2` and `gemini-embedding-001` spaces at 768 dimensions.

## Verification

```powershell
python -m ruff format --check src tests services vmec_data apps migrations
python -m ruff check src tests services vmec_data apps migrations
python -m mypy src services vmec_data apps --ignore-missing-imports
python -m pytest -q
npm ci
npm audit --audit-level=high
npm run lint:web
npm run typecheck:web
npm run test:web
npm run build:web
```

Live model visibility is a separate, secret-safe gate:

```powershell
.\VERIFY_GEMINI_MODELS.ps1
```

See `docs/IMPLEMENTATION_STATUS.md`, `docs/DECISIONS.md`, `docs/THREAT_MODEL.md` and `docs/runbooks/` for evidence, architecture decisions and operations.
