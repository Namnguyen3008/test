from pathlib import Path

import pytest

from scripts.local_encrypted_backup import _archive_name, _verify_archive_digest, parser


def test_local_backup_parser_requires_explicit_secret_paths() -> None:
    parsed = parser().parse_args(
        ["backup", "--backup-directory", "D:/safe", "--recipient", "D:/safe/recipient.txt"]
    )
    assert parsed.database == "vmec"
    assert parsed.backup_database_user == "vmec_v8_backup"
    assert parsed.restore_database_user == "vmec"
    assert parsed.recipient.endswith("recipient.txt")


def test_local_backup_names_are_encrypted_custom_dumps() -> None:
    assert _archive_name().startswith("vmec-")
    assert _archive_name().endswith(".dump.age")


def test_restore_refuses_changed_or_missing_digest(tmp_path: Path) -> None:
    archive = tmp_path / "vmec.dump.age"
    archive.write_bytes(b"encrypted backup fixture")
    with pytest.raises(ValueError, match="sidecar"):
        _verify_archive_digest(archive)

    sidecar = archive.with_suffix(".age.sha256")
    sidecar.write_text("0" * 64 + "  vmec.dump.age\n", encoding="ascii")
    with pytest.raises(ValueError, match="does not match"):
        _verify_archive_digest(archive)
