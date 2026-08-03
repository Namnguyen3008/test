from scripts.local_encrypted_backup import _archive_name, parser


def test_local_backup_parser_requires_explicit_secret_paths() -> None:
    parsed = parser().parse_args(
        ["backup", "--backup-directory", "D:/safe", "--recipient", "D:/safe/recipient.txt"]
    )
    assert parsed.database == "vmec"
    assert parsed.recipient.endswith("recipient.txt")


def test_local_backup_names_are_encrypted_custom_dumps() -> None:
    assert _archive_name().startswith("vmec-")
    assert _archive_name().endswith(".dump.age")
