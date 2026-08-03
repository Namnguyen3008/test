"""Command-line entry point for ``python -m vmec_data``."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .importer import ImportConfig, run_import


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vmec_data")
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("import", help="stream immutable VMEC artifacts into a local catalog")
    command.add_argument("--development-zip", type=Path, required=True)
    command.add_argument("--research-zip", type=Path, required=True)
    command.add_argument("--source-ledger", type=Path, required=True)
    command.add_argument("--master-index", type=Path, required=True)
    command.add_argument("--mode", choices=("development", "review", "production"), default="development")
    command.add_argument("--database", type=Path, default=Path("data/staging/vmec_catalog.sqlite3"))
    command.add_argument("--report-dir", type=Path, default=Path("data/reports"))
    command.add_argument("--release-id")
    command.add_argument("--table")
    command.add_argument("--dry-run", action="store_true")
    command.add_argument("--resume", action="store_true")
    command.add_argument("--skip-embeddings", action="store_true")
    command.add_argument("--rebuild-embeddings", choices=("primary", "fallback", "all"))
    command.add_argument("--max-workers", type=int, default=1)
    command.add_argument("--batch-size", type=int, default=500)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.max_workers < 1 or args.batch_size < 1:
        raise SystemExit("--max-workers and --batch-size must be positive")
    config = ImportConfig(**{key: value for key, value in vars(args).items() if key != "command"})
    result = run_import(config)
    print(
        json.dumps(
            {
                "release_id": result.release_id,
                "status": result.status,
                "rows_imported": result.rows_imported,
                "rows_quarantined": result.rows_quarantined,
                "report_json": str(result.report_json),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
