"""Classification rules for every table shipped in the VMEC v2 corpus."""

from __future__ import annotations

from typing import Final

CATEGORIES: Final[tuple[str, ...]] = (
    "emergency_safety",
    "routing_clarification",
    "language_nlu",
    "conversation_booking",
    "content_policy_notification",
    "evaluation_security",
    "synthetic_profile_analytics",
    "source_provenance",
)

_TABLES: Final[dict[str, set[str]]] = {
    "emergency_safety": {
        "action_messages",
        "adult_emergency_phrases",
        "adult_emergency_rules",
        "age_specific_actions",
        "caregiver_phrases",
        "family_member_cases",
        "hard_negatives",
        "human_handoff_conditions",
        "maternal_action_messages",
        "maternal_emergency_rules",
        "negated_emergency_cases",
        "negation_flags",
        "newborn_rules",
        "pediatric_emergency_rules",
        "postpartum_rules",
        "stop_conditions",
        "urgent_exclusions",
    },
    "routing_clarification": {
        "ambiguity",
        "clarifying_questions",
        "clinical_gold",
        "handoff",
        "intent_entity_constraints",
        "question_conditions",
        "routing_rows",
        "specialty_reference",
    },
    "language_nlu": {
        "abbreviations",
        "entity_annotations",
        "intent_utterances",
        "no_diacritic_variants",
        "normalization_pairs",
        "paraphrase_lineage",
        "paraphrases",
        "parent_reference",
        "regional_variants",
        "register_tags",
        "speaker_roles",
        "typo_variants",
    },
    "conversation_booking": {
        "appointment_states",
        "booking_conversations",
        "booking_invariants",
        "booking_policies",
        "cancellation_scenarios",
        "consent_states",
        "conversation_state",
        "conversations",
        "expired_offer_scenarios",
        "handoff_events",
        "hold_events",
        "patient_confirm_events",
        "preferences",
        "reconfirmation_events",
        "reschedule_offers",
        "scenario_invariants",
        "staff_approval_events",
        "turns",
    },
    "content_policy_notification": {
        "content_versions",
        "email_templates",
        "faq",
        "human_support_content",
        "notification_policy",
        "privacy_notices",
        "push_templates",
        "sms_templates",
        "template_variables",
        "visit_preparation",
    },
    "evaluation_security": {
        "adult_emergency_gold_tests",
        "attack_taxonomy",
        "booking_grounding_cases",
        "citation_cases",
        "data_exfiltration",
        "emergency_hidden",
        "grounding_cases",
        "hard_negative_gold",
        "indirect_injection",
        "intent_gold_tests",
        "maternal_gold_tests",
        "memory_test_cases",
        "nonexistent_entity_cases",
        "pediatric_gold_tests",
        "phi_leakage",
        "prompt_injection",
        "routing_hidden",
        "scoring_rubric",
        "security_rubric",
        "tool_abuse",
        "unsupported_claim_cases",
    },
    "synthetic_profile_analytics": {
        "conflict_scenarios",
        "historical_cases",
        "hypothetical_cases",
        "linguistic_review_sample",
        "profile_lineage",
        "resolved_cases",
        "split_registry",
        "synthetic_history",
        "synthetic_profiles",
    },
    "source_provenance": {
        "citations_shown",
        "question_source_map",
        "reconciliation",
        "route_source_map",
        "source_bridge",
        "source_conflicts",
    },
}

TABLE_CLASSIFICATION: Final[dict[str, str]] = {
    table: category for category, tables in _TABLES.items() for table in tables
}
EXPECTED_TABLE_COUNT: Final[int] = 101

if len(TABLE_CLASSIFICATION) != EXPECTED_TABLE_COUNT:  # pragma: no cover - import invariant
    raise RuntimeError(f"classification map has {len(TABLE_CLASSIFICATION)} tables, expected 101")


def classify_table(table_name: str) -> str | None:
    """Return the authoritative domain category for a source table."""
    return TABLE_CLASSIFICATION.get(table_name)
