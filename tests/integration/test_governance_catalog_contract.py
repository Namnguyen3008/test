from pathlib import Path

import pytest

from src.governance.catalog import build_governance_draft

CATALOG = Path("data/staging/vmec_catalog.sqlite3")
pytestmark = pytest.mark.skipif(not CATALOG.is_file(), reason="private immutable VMEC catalog is unavailable")


def test_real_development_catalog_governance_contract() -> None:
    draft, evidence = build_governance_draft(CATALOG, "vmec-development-v2", "development")
    assert draft["release_scope"] == {
        "release_ids": ["vmec-development-v2"],
        "registry_digest": "213b8dd1f6ce520df6bd87f0b560bcb14594a6c2a42e3659f3fd5f3670a86642",
        "expected_rows": 15_511,
        "canonical_sources": 947,
        "included_tables": [
            "adult_emergency_rules",
            "clarifying_questions",
            "faq",
            "human_support_content",
            "maternal_emergency_rules",
            "pediatric_emergency_rules",
            "routing_rows",
            "visit_preparation",
        ],
        "included_row_hashes_digest": "ba57590209cd5a5eb748cbbceacc260ce0a9692dd1a8025a0fade54a3393519f",
    }
    assert draft["candidate_counts"] == {
        "accepted_candidates": 15_511,
        "ordinary_accepted_candidates": 3_166,
        "gold_candidates": 12_345,
        "safety_critical_candidates": 528,
        "excluded_missing_source_or_ineligible": 32_706,
    }
    assert evidence["source_artifact_sha256"] == ("8ae42c51379c470c123eeef063b7c3da219311c8ca75475de24c4214d8b97b46")
    assert evidence["source_registry_digest"] == ("996a95e678b11bed868baaa1a12a77ddad3adf02a9ff0889ea0ecddce5b1ba98")
