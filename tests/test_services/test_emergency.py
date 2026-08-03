import sqlite3

import pytest

from src.services.emergency import (
    EmergencyDetector,
    activate_emergency_rules,
    compile_emergency_catalog,
    compile_emergency_rows,
    reset_emergency_rules,
    screen_emergency,
)


def test_emergency_detector_handles_vietnamese_diacritics() -> None:
    result = screen_emergency("Bệnh nhân bất tỉnh, không đánh thức được")
    assert result.emergency
    assert "EMERGENCY_UNCONSCIOUS" in result.rule_ids
    assert result.ruleset_version == "seed-v1"


@pytest.mark.parametrize(
    "text",
    [
        "Tôi đã hết đau ngực dữ dội",
        "Trước đây tôi đau ngực dữ dội nhưng nay hoàn toàn bình thường",
        "Nếu đau ngực dữ dội thì tôi nên làm gì?",
    ],
)
def test_emergency_detector_respects_negation_temporality_and_hypotheticals(text: str) -> None:
    assert not screen_emergency(text).emergency


@pytest.mark.parametrize(
    "text,expected_rule",
    [
        ("Bé tím tái", "EMERGENCY_PEDIATRIC"),
        ("Tôi đang mang thai chảy máu nhiều", "EMERGENCY_MATERNAL"),
        ("Trẻ sơ sinh ngừng bú", "EMERGENCY_NEWBORN"),
    ],
)
def test_seed_rules_cover_age_and_pregnancy_contexts(text: str, expected_rule: str) -> None:
    result = screen_emergency(text)
    assert result.emergency
    assert expected_rule in result.rule_ids


def corpus_positive(*, status: str = "REVIEW_REQUIRED", review: str = "PENDING_CLINICAL_REVIEW"):
    return {
        "row_id": "RULE-1",
        "global_row_id": "GLOBAL-1",
        "trigger_phrase_vi": "khó thở dữ dội và không nói được trọn câu",
        "emergency_action_code": "CALL_115_OR_GO_TO_ED_NOW",
        "canonical_status": status,
        "review_status": review,
        "age_group": "INFANT_CHILD",
        "source_id": "SOURCE-1",
        "secondary_source_id": "SOURCE-2",
        "content_hash": "a" * 64,
    }


def corpus_negative():
    return {
        "row_id": "NEG-1",
        "utterance_vi": "Bé hiện không còn khó thở dữ dội và không nói được trọn câu.",
        "emergency_action_code": "NO_EMERGENCY_TRIGGER",
        "canonical_status": "REVIEW_REQUIRED",
    }


def test_development_compiler_versions_rules_and_hard_negatives() -> None:
    first = compile_emergency_rows([corpus_positive()], [corpus_negative()], release_id="dev-v2", mode="development")
    second = compile_emergency_rows([corpus_positive()], [corpus_negative()], release_id="dev-v2", mode="development")

    assert first.version == second.version
    assert first.version.startswith("dev-v2:")
    detector = EmergencyDetector(first)
    assert detector.screen("Bé khó thở dữ dội và không nói được trọn câu").emergency
    assert not detector.screen(corpus_negative()["utterance_vi"]).emergency


def test_production_compiler_fails_closed_for_review_required_rows() -> None:
    with pytest.raises(RuntimeError, match="zero clinically approved rules"):
        compile_emergency_rows([corpus_positive()], [corpus_negative()], release_id="prod-v1", mode="production")


def test_production_compiler_accepts_only_explicitly_clinically_approved_rows() -> None:
    ruleset = compile_emergency_rows(
        [corpus_positive(status="ACCEPTED", review="CLINICALLY_APPROVED")],
        [],
        release_id="prod-v1",
        mode="production",
    )
    assert len(ruleset.rules) == 1
    assert ruleset.approved_rule_count == 1


def test_validated_snapshot_can_be_activated_and_reset() -> None:
    ruleset = compile_emergency_rows(
        [corpus_positive()],
        [],
        release_id="dev-v2",
        mode="development",
    )
    activate_emergency_rules(ruleset)
    try:
        result = screen_emergency("Khó thở dữ dội và không nói được trọn câu")
        assert result.emergency
        assert result.ruleset_version == ruleset.version
    finally:
        reset_emergency_rules()
    assert screen_emergency("Bất tỉnh").ruleset_version == "seed-v1"


def test_catalog_compiler_reads_completed_release_read_only(tmp_path) -> None:
    database = tmp_path / "catalog.sqlite3"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE dataset_releases (release_id TEXT PRIMARY KEY, mode TEXT, status TEXT);
        CREATE TABLE dataset_rows (
          release_id TEXT, table_name TEXT, row_key TEXT, payload_json TEXT,
          PRIMARY KEY(release_id, table_name, row_key)
        );
        INSERT INTO dataset_releases VALUES ('dev-v2', 'development', 'completed');
        """
    )
    import json

    connection.execute(
        "INSERT INTO dataset_rows VALUES (?,?,?,?)",
        ("dev-v2", "urgent_exclusions", "1", json.dumps(corpus_positive(), ensure_ascii=False)),
    )
    connection.execute(
        "INSERT INTO dataset_rows VALUES (?,?,?,?)",
        ("dev-v2", "hard_negatives", "1", json.dumps(corpus_negative(), ensure_ascii=False)),
    )
    connection.commit()
    connection.close()

    ruleset = compile_emergency_catalog(database, release_id="dev-v2", mode="development")
    assert len(ruleset.rules) == 1
    assert len(ruleset.hard_negatives) == 1
