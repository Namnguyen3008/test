import pytest

from services.retrieval import governance_classification


@pytest.mark.parametrize(
    ("table", "payload", "safety", "gold"),
    [
        ("faq", {"data_tier": "GOLD"}, False, True),
        ("faq", {"data_tier": " gold_draft "}, False, True),
        ("routing_rows", {"intended_tier": "GOLD_CORE_CANDIDATE"}, False, True),
        ("routing_rows", {"hidden_gold": "YES"}, False, True),
        ("adult_emergency_rules", {}, True, True),
        ("clinical_gold", {}, False, True),
        ("faq", {"data_tier": "SILVER", "hidden_gold": "NO"}, False, False),
        ("ordinary_gold_sounding_name", {}, False, False),
    ],
)
def test_versioned_governance_classification(table: str, payload: dict[str, str], safety: bool, gold: bool) -> None:
    result = governance_classification(table, payload)
    assert result.safety_critical is safety
    assert result.gold_candidate is gold
    assert bool(result.gold_reason) is gold
