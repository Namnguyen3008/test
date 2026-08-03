import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_tracked_lifecycle_schemas_are_strict_and_versioned() -> None:
    schemas = ROOT / "docs/governance/schemas"
    expected = {
        "governance-supersession-v1.schema.json": "vmec.governance-supersession.v1",
        "governance-revocation-v1.schema.json": "vmec.governance-revocation.v1",
    }
    for filename, version in expected.items():
        artifact = json.loads((schemas / filename).read_text(encoding="utf-8"))
        assert artifact["$schema"] == "https://json-schema.org/draft/2020-12/schema"
        assert artifact["additionalProperties"] is False
        assert artifact["properties"]["schema_version"]["const"] == version
        assert {"signature", "owner_authorization", "expected_generation"} <= set(artifact["required"])
