"""Create and restore local VMEC rehearsal backups encrypted with age."""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path


def _run(arguments: list[str], *, stdin=None, stdout=None) -> None:
    completed = subprocess.run(arguments, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE, check=False)
    if completed.returncode:
        raise RuntimeError(f"backup command failed: {arguments[0]}")


def _archive_name() -> str:
    return f"vmec-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.dump.age"


def _digest_sidecar(archive: Path) -> Path:
    return archive.with_suffix(archive.suffix + ".sha256")


def _verify_archive_digest(archive: Path) -> None:
    sidecar = _digest_sidecar(archive)
    if not sidecar.is_file() or sidecar.is_symlink():
        raise ValueError("encrypted archive digest sidecar must be a regular file")
    expected = sidecar.read_text(encoding="ascii").strip().split(maxsplit=1)
    if len(expected) != 2 or expected[1] != archive.name:
        raise ValueError("encrypted archive digest sidecar is malformed")
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if actual != expected[0]:
        raise ValueError("encrypted archive digest does not match")


def backup(arguments: argparse.Namespace) -> Path:
    destination = Path(arguments.backup_directory).resolve()
    recipient = Path(arguments.recipient).resolve()
    if not recipient.is_file() or recipient.is_symlink():
        raise ValueError("age recipient file must be a regular file")
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / _archive_name()
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        raw_dump = Path(temporary) / "vmec.dump"
        with raw_dump.open("wb") as output:
            _run(
                [
                    arguments.docker,
                    "compose",
                    "exec",
                    "-T",
                    "postgres",
                    "pg_dump",
                    "-U",
                    arguments.backup_database_user,
                    "--format=custom",
                    "--compress=9",
                    "--no-owner",
                    "--no-acl",
                    arguments.database,
                ],
                stdout=output,
            )
        _run([arguments.age, "-R", str(recipient), "-o", str(target), str(raw_dump)])
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    sidecar = _digest_sidecar(target)
    sidecar.write_text(f"{digest}  {target.name}\n", encoding="ascii")
    print(f"ENCRYPTED_BACKUP_CREATED={target.name}")
    return target


def restore(arguments: argparse.Namespace) -> None:
    archive = Path(arguments.archive).resolve()
    identity = Path(arguments.identity).resolve()
    if not archive.is_file() or archive.is_symlink() or not identity.is_file() or identity.is_symlink():
        raise ValueError("archive and age identity must be regular files")
    _verify_archive_digest(archive)
    with tempfile.TemporaryDirectory(dir=archive.parent) as temporary:
        raw_dump = Path(temporary) / "vmec.dump"
        _run([arguments.age, "-d", "-i", str(identity), "-o", str(raw_dump), str(archive)])
        _run(
            [
                arguments.docker,
                "compose",
                "exec",
                "-T",
                "postgres",
                    "createdb",
                    "-U",
                    arguments.restore_database_user,
                arguments.restore_database,
            ]
        )
        with raw_dump.open("rb") as input_stream:
            _run(
                [
                    arguments.docker,
                    "compose",
                    "exec",
                    "-T",
                    "postgres",
                    "pg_restore",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-acl",
                    "-U",
                    arguments.restore_database_user,
                    "--dbname",
                    arguments.restore_database,
                ],
                stdin=input_stream,
            )
    print("ENCRYPTED_BACKUP_RESTORE_COMPLETED")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--docker", default="docker")
    result.add_argument("--age", default="age")
    result.add_argument("--backup-database-user", default="vmec_v8_backup")
    result.add_argument("--restore-database-user", default="vmec")
    result.add_argument("--database", default="vmec")
    commands = result.add_subparsers(dest="command", required=True)
    create = commands.add_parser("backup")
    create.add_argument("--backup-directory", required=True)
    create.add_argument("--recipient", required=True)
    create.set_defaults(handler=backup)
    restore_parser = commands.add_parser("restore")
    restore_parser.add_argument("--archive", required=True)
    restore_parser.add_argument("--identity", required=True)
    restore_parser.add_argument("--restore-database", required=True)
    restore_parser.set_defaults(handler=restore)
    return result


def main() -> int:
    arguments = parser().parse_args()
    arguments.handler(arguments)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
