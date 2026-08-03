"""Versioned deterministic emergency screening that runs before AI services.

The bundled VMEC corpus is useful for development and regression testing, but it
is not clinically approved.  This module therefore keeps compilation and
activation separate: development/review modes may compile ``REVIEW_REQUIRED``
rows, while production accepts only explicitly approved rows and otherwise
fails closed.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import unicodedata
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

DataMode = Literal["development", "review", "production"]

EMERGENCY_ACTION: Final = (
    "Đây có thể là tình huống khẩn cấp. Hãy gọi 115 hoặc đến cơ sở cấp cứu gần nhất ngay. "
    "Không tiếp tục đặt lịch thông thường."
)
_APPROVED_STATUSES: Final = frozenset({"ACCEPTED", "GOLD", "APPROVED"})
_APPROVED_REVIEW_STATUSES: Final = frozenset({"CLINICALLY_APPROVED", "APPROVED"})
_EMERGENCY_ACTION_CODES: Final = frozenset({"CALL_115_OR_GO_TO_ED_NOW", "GO_TO_ED_NOW"})
_CORPUS_RULE_TEXT_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "urgent_exclusions": ("trigger_phrase_vi", "positive_pattern_vi", "pattern_vi"),
    "adult_emergency_rules": ("trigger_definition_vi", "trigger_summary_vi", "adult_emergency_rules"),
    "pediatric_emergency_rules": (
        "trigger_definition_vi",
        "trigger_summary_vi",
        "pediatric_emergency_rules",
    ),
    "maternal_emergency_rules": ("trigger_summary_vi", "maternal_emergency_rules"),
    "newborn_rules": ("trigger_summary_vi", "newborn_rules"),
    "postpartum_rules": ("trigger_summary_vi", "postpartum_rules"),
}
_NEGATION_MARKERS: Final = (
    "khong bi",
    "khong co",
    "khong con",
    "da het",
    "chua tung",
    "khong thay",
)
_HISTORICAL_MARKERS: Final = ("truoc day", "thang truoc", "nam ngoai", "hoi truoc", "da tung")
_HYPOTHETICAL_MARKERS: Final = ("neu ", "gia su", "lo rang", "so rang")


@dataclass(frozen=True, slots=True)
class EmergencyResult:
    emergency: bool
    rule_ids: tuple[str, ...] = ()
    action: str = ""
    ruleset_version: str = "seed-v1"
    data_mode: DataMode = "development"


@dataclass(frozen=True, slots=True)
class EmergencyRule:
    rule_id: str
    phrase: str
    category: str
    source_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.rule_id or not _normalize(self.phrase):
            raise ValueError("Emergency rule requires a non-empty identifier and phrase")


@dataclass(frozen=True, slots=True)
class VersionedEmergencyRules:
    version: str
    data_mode: DataMode
    rules: tuple[EmergencyRule, ...]
    hard_negatives: frozenset[str] = frozenset()
    approved_rule_count: int = 0

    def __post_init__(self) -> None:
        if self.data_mode == "production" and not self.rules:
            raise RuntimeError("production emergency corpus unavailable: zero clinically approved rules")


def _normalize(text: str) -> str:
    value = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", value)).strip()


def _pipe_values(*values: object) -> tuple[str, ...]:
    return tuple(
        part.strip()
        for value in values
        if value
        for part in str(value).split("|")
        if part.strip() and part.strip() != "CONTEXT"
    )


def _is_approved(row: Mapping[str, object]) -> bool:
    return (
        str(row.get("canonical_status", "")).upper() in _APPROVED_STATUSES
        and str(row.get("review_status", "")).upper() in _APPROVED_REVIEW_STATUSES
    )


def _is_suppressed_context(normalized: str, phrase_start: int) -> bool:
    prefix = normalized[max(0, phrase_start - 48) : phrase_start]
    return any(marker in prefix for marker in (*_NEGATION_MARKERS, *_HISTORICAL_MARKERS, *_HYPOTHETICAL_MARKERS))


def _canonical_emergency_rows(table: str, rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    """Promote heterogeneous supplied rule tables into the narrow runtime schema."""
    fields = _CORPUS_RULE_TEXT_FIELDS[table]
    canonical: list[dict[str, object]] = []
    for row in rows:
        action = str(row.get("emergency_action_code") or row.get("action_code") or "").upper()
        if action not in _EMERGENCY_ACTION_CODES:
            continue
        phrase = next((str(row.get(field, "")).strip() for field in fields if str(row.get(field, "")).strip()), "")
        normalized = _normalize(phrase)
        if len(normalized) < 4 or len(normalized) > 500:
            continue
        row_id = str(row.get("row_id") or row.get("rule_id") or row.get("global_row_id") or "").strip()
        if not row_id:
            continue
        canonical.append(
            {
                "row_id": f"{table}:{row_id}",
                "trigger_phrase_vi": phrase,
                "emergency_action_code": action,
                "canonical_status": row.get("canonical_status", ""),
                "review_status": row.get("review_status", ""),
                "age_group": row.get("age_group") or row.get("adult_age_group") or table,
                "source_id": row.get("source_id") or row.get("primary_source_id"),
                "secondary_source_id": row.get("secondary_source_id"),
                "content_hash": row.get("content_hash") or f"{table}\0{row_id}\0{normalized}",
            }
        )
    return canonical


class EmergencyDetector:
    """Deterministic matcher over an immutable, versioned rule snapshot."""

    def __init__(self, ruleset: VersionedEmergencyRules) -> None:
        self.ruleset = ruleset
        self._compiled = tuple((rule, _normalize(rule.phrase)) for rule in ruleset.rules)

    def screen(self, text: str) -> EmergencyResult:
        normalized = _normalize(text)
        if not normalized or normalized in self.ruleset.hard_negatives:
            return EmergencyResult(False, ruleset_version=self.ruleset.version, data_mode=self.ruleset.data_mode)

        matches: list[str] = []
        for rule, phrase in self._compiled:
            start = normalized.find(phrase)
            if start < 0 or _is_suppressed_context(normalized, start):
                continue
            matches.append(rule.rule_id)
        unique_matches = tuple(dict.fromkeys(matches))
        if not unique_matches:
            return EmergencyResult(False, ruleset_version=self.ruleset.version, data_mode=self.ruleset.data_mode)
        return EmergencyResult(
            True,
            unique_matches,
            EMERGENCY_ACTION,
            self.ruleset.version,
            self.ruleset.data_mode,
        )


_SEED_RULES: Final = VersionedEmergencyRules(
    version="seed-v1",
    data_mode="development",
    rules=tuple(
        EmergencyRule(rule_id, phrase, category)
        for rule_id, category, phrases in (
            ("EMERGENCY_BREATHING", "adult", ("không thở được", "khó thở dữ dội", "ngừng thở")),
            ("EMERGENCY_CHEST", "adult", ("đau ngực dữ dội", "đau thắt ngực")),
            ("EMERGENCY_STROKE", "adult", ("méo miệng", "liệt nửa người", "nói khó đột ngột")),
            ("EMERGENCY_BLEEDING", "adult", ("chảy máu không cầm", "xuất huyết nhiều")),
            ("EMERGENCY_UNCONSCIOUS", "all", ("bất tỉnh", "hôn mê", "không đánh thức được")),
            ("EMERGENCY_PEDIATRIC", "pediatric", ("bé tím tái", "trẻ co giật")),
            ("EMERGENCY_MATERNAL", "maternal", ("đang mang thai chảy máu nhiều",)),
            ("EMERGENCY_NEWBORN", "newborn", ("trẻ sơ sinh ngừng bú",)),
        )
        for phrase in phrases
    ),
)
_DEFAULT_DETECTOR: Final = EmergencyDetector(_SEED_RULES)
_ACTIVE_DETECTOR = _DEFAULT_DETECTOR


def screen_emergency(text: str) -> EmergencyResult:
    """Screen with the atomically activated immutable rule snapshot."""
    return _ACTIVE_DETECTOR.screen(text)


def activate_emergency_rules(ruleset: VersionedEmergencyRules) -> None:
    """Atomically activate a validated snapshot without mutating its rules."""
    global _ACTIVE_DETECTOR
    if ruleset.data_mode != "production":
        existing_ids = {rule.rule_id for rule in ruleset.rules}
        ruleset = VersionedEmergencyRules(
            version=f"{ruleset.version}+seed-v1",
            data_mode=ruleset.data_mode,
            rules=ruleset.rules + tuple(rule for rule in _SEED_RULES.rules if rule.rule_id not in existing_ids),
            hard_negatives=ruleset.hard_negatives,
            approved_rule_count=ruleset.approved_rule_count,
        )
    _ACTIVE_DETECTOR = EmergencyDetector(ruleset)


def reset_emergency_rules() -> None:
    """Restore the conservative seed snapshot (primarily for test isolation)."""
    global _ACTIVE_DETECTOR
    _ACTIVE_DETECTOR = _DEFAULT_DETECTOR


def emergency_runtime_status() -> dict[str, object]:
    """Return aggregate, PHI-free readiness metadata for diagnostics."""
    ruleset = _ACTIVE_DETECTOR.ruleset
    return {
        "version": ruleset.version,
        "data_mode": ruleset.data_mode,
        "rule_count": len(ruleset.rules),
        "hard_negative_count": len(ruleset.hard_negatives),
        "approved_rule_count": ruleset.approved_rule_count,
    }


def compile_emergency_rows(
    rows: Iterable[Mapping[str, object]],
    hard_negative_rows: Iterable[Mapping[str, object]],
    *,
    release_id: str,
    mode: DataMode,
) -> VersionedEmergencyRules:
    """Compile normalized corpus rows without changing their review status.

    Expected positive fields match ``urgent_exclusions`` from the supplied
    corpus.  The narrow contract intentionally rejects ambiguous rule schemas.
    """
    rules: list[EmergencyRule] = []
    approved_count = 0
    fingerprints: list[str] = []
    for row in rows:
        approved = _is_approved(row)
        if approved:
            approved_count += 1
        if mode == "production" and not approved:
            continue
        action = str(row.get("emergency_action_code", "")).upper()
        phrase = str(row.get("trigger_phrase_vi", "")).strip()
        rule_id = str(row.get("row_id") or row.get("global_row_id") or "").strip()
        if action not in _EMERGENCY_ACTION_CODES or not phrase or not rule_id:
            continue
        source_ids = _pipe_values(row.get("source_id"), row.get("secondary_source_id"))
        rules.append(EmergencyRule(rule_id, phrase, str(row.get("age_group", "unspecified")), source_ids))
        fingerprints.append(str(row.get("content_hash") or f"{rule_id}\0{phrase}"))

    hard_negatives_list: list[str] = []
    for row in hard_negative_rows:
        if mode == "production" and not _is_approved(row):
            continue
        if str(row.get("emergency_action_code", "")).upper() != "NO_EMERGENCY_TRIGGER":
            continue
        normalized = _normalize(str(row.get("utterance_vi", "")))
        if normalized:
            hard_negatives_list.append(normalized)
            fingerprints.append(str(row.get("content_hash") or f"hard-negative\0{normalized}"))
    hard_negatives = frozenset(hard_negatives_list)
    digest = hashlib.sha256("\n".join(sorted(fingerprints)).encode()).hexdigest()[:16]
    return VersionedEmergencyRules(
        version=f"{release_id}:{digest}",
        data_mode=mode,
        rules=tuple(sorted(rules, key=lambda rule: rule.rule_id)),
        hard_negatives=hard_negatives,
        approved_rule_count=approved_count,
    )


def compile_emergency_catalog(
    catalog_path: Path,
    *,
    release_id: str,
    mode: DataMode,
) -> VersionedEmergencyRules:
    """Compile a VMEC SQLite catalog into an in-memory immutable snapshot."""
    if not catalog_path.is_file():
        raise FileNotFoundError(catalog_path)
    connection = sqlite3.connect(f"file:{catalog_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        release = connection.execute(
            "SELECT mode, status FROM dataset_releases WHERE release_id=?", (release_id,)
        ).fetchone()
        if release is None or release[1] != "completed":
            raise RuntimeError("emergency corpus release is missing or incomplete")

        def load(table: str) -> list[dict[str, object]]:
            return [
                json.loads(payload)
                for (payload,) in connection.execute(
                    "SELECT payload_json FROM dataset_rows WHERE release_id=? AND table_name=? ORDER BY row_key",
                    (release_id, table),
                )
            ]

        positive_rows = [
            row for table in _CORPUS_RULE_TEXT_FIELDS for row in _canonical_emergency_rows(table, load(table))
        ]
        return compile_emergency_rows(
            positive_rows,
            load("hard_negatives"),
            release_id=release_id,
            mode=mode,
        )
    finally:
        connection.close()
