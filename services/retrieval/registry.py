"""Deterministic patient-facing retrieval eligibility and citation registry."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal

DataMode = Literal["development", "review", "production"]

_ELIGIBLE_TABLES: Final = frozenset(
    {
        "adult_emergency_phrases",
        "adult_emergency_rules",
        "maternal_emergency_rules",
        "newborn_rules",
        "pediatric_emergency_rules",
        "postpartum_rules",
        "urgent_exclusions",
        "routing_rows",
        "specialty_reference",
        "clarifying_questions",
        "faq",
        "human_support_content",
        "visit_preparation",
    }
)
_FORBIDDEN_TABLES: Final = frozenset(
    {
        "appointment_states",
        "booking_conversations",
        "hold_events",
        "patient_confirm_events",
        "staff_approval_events",
        "historical_cases",
        "synthetic_history",
        "synthetic_profiles",
        "prompt_injection",
        "indirect_injection",
        "data_exfiltration",
        "phi_leakage",
        "emergency_hidden",
        "routing_hidden",
        "source_conflicts",
    }
)
_PRODUCTION_STATUSES: Final = frozenset({"ACCEPTED", "GOLD", "APPROVED"})
_PRODUCTION_REVIEW_STATUSES: Final = frozenset({"CLINICALLY_APPROVED", "APPROVED"})
_TEXT_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    "routing_rows": ("user_utterance_vi", "utterance_vi", "question_text_vi", "response_text_vi"),
    "specialty_reference": ("name_vi",),
    "clarifying_questions": ("question_text_vi", "clarifying_question_vi"),
    "faq": ("question_vi", "answer_vi", "response_text_vi"),
    "human_support_content": ("content_vi", "response_text_vi"),
    "visit_preparation": ("content_vi", "response_text_vi"),
    "urgent_exclusions": ("trigger_phrase_vi", "patient_message_vi", "response_text_vi"),
    "adult_emergency_phrases": ("utterance_vi", "trigger_phrase_vi"),
    "adult_emergency_rules": ("trigger_definition_vi", "trigger_summary_vi"),
    "maternal_emergency_rules": ("trigger_summary_vi", "maternal_emergency_rules"),
    "newborn_rules": ("trigger_summary_vi", "newborn_rules"),
    "pediatric_emergency_rules": ("trigger_definition_vi", "trigger_summary_vi"),
    "postpartum_rules": ("trigger_summary_vi", "postpartum_rules"),
}


class EligibilityReason(StrEnum):
    ELIGIBLE = "eligible"
    FORBIDDEN_TABLE = "forbidden-table"
    TABLE_NOT_ALLOWLISTED = "table-not-allowlisted"
    CONFLICT_OR_REJECTED = "conflict-or-rejected"
    UNAPPROVED_PRODUCTION = "unapproved-production"
    EMPTY_CONTENT = "empty-content"
    NO_CANONICAL_SOURCE = "no-canonical-source"


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    origin_table: str
    origin_row_id: str
    text: str
    content_hash: str
    source_ids: tuple[str, ...]
    canonical_status: str = "REVIEW_REQUIRED"
    review_status: str = "PENDING_CLINICAL_REVIEW"
    conflict_status: str = ""


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    eligible: bool
    reason: EligibilityReason


@dataclass(frozen=True, slots=True)
class Citation:
    source_id: str
    canonical_url: str
    title: str = ""


class CitationRegistry:
    """Resolve only canonical Global Source Ledger identifiers."""

    def __init__(self, sources: Mapping[str, Citation], aliases: Mapping[str, str] | None = None) -> None:
        invalid = [
            source_id
            for source_id, citation in sources.items()
            if source_id != citation.source_id
            or not source_id.strip()
            or not citation.canonical_url.startswith(("https://", "http://", "internal://", "//"))
        ]
        if invalid:
            raise ValueError(f"Invalid canonical citations: {', '.join(sorted(invalid))}")
        self._sources = dict(sources)
        self._aliases = dict(aliases or {})
        unknown_targets = sorted(set(self._aliases.values()) - set(self._sources))
        if unknown_targets:
            raise ValueError(f"Citation aliases target unknown sources: {', '.join(unknown_targets)}")

    @classmethod
    def from_global_ledger(cls, rows: Iterable[Mapping[str, object]]) -> CitationRegistry:
        """Build the local-source-to-global-source bridge from ledger rows."""
        sources: dict[str, Citation] = {}
        aliases: dict[str, str] = {}
        ambiguous_aliases: set[str] = set()
        for row in rows:
            global_id = str(row.get("global_source_id", "")).strip()
            canonical_url = str(row.get("canonical_url") or row.get("source_url") or "").strip()
            if not global_id or not canonical_url.startswith(("https://", "http://", "internal://", "//")):
                continue
            sources[global_id] = Citation(global_id, canonical_url, str(row.get("source_title") or ""))
            local_id = str(row.get("source_id") or "").strip()
            if local_id and local_id not in ambiguous_aliases:
                prior = aliases.setdefault(local_id, global_id)
                if prior != global_id:
                    aliases.pop(local_id, None)
                    ambiguous_aliases.add(local_id)
        return cls(sources, aliases)

    def resolve(self, source_ids: Iterable[str]) -> tuple[Citation, ...]:
        unique = tuple(dict.fromkeys(self._aliases.get(source_id, source_id) for source_id in source_ids))
        if not unique:
            raise ValueError("Grounded retrieval record has no citation source")
        missing = [source_id for source_id in unique if source_id not in self._sources]
        if missing:
            raise ValueError(f"Unknown canonical source ids: {', '.join(sorted(missing))}")
        return tuple(self._sources[source_id] for source_id in unique)


def candidate_from_dataset_row(
    origin_table: str,
    origin_row_id: str,
    content_hash: str,
    payload: Mapping[str, object],
) -> RetrievalCandidate:
    """Create a minimal candidate without retaining unrelated/private payload fields."""
    text = next(
        (
            str(payload.get(field, "")).strip()
            for field in _TEXT_FIELDS.get(origin_table, ())
            if str(payload.get(field, "")).strip()
        ),
        "",
    )
    source_values = (
        payload.get("source_id"),
        payload.get("source_ids"),
        payload.get("primary_source_id"),
        payload.get("secondary_source_id"),
        payload.get("secondary_source_ids"),
    )
    source_ids = tuple(
        dict.fromkeys(
            part.strip()
            for value in source_values
            if value
            for part in str(value).replace(",", "|").split("|")
            if part.strip()
        )
    )
    return RetrievalCandidate(
        origin_table=origin_table,
        origin_row_id=origin_row_id,
        text=text,
        content_hash=content_hash,
        source_ids=source_ids,
        canonical_status=str(payload.get("canonical_status", "REVIEW_REQUIRED")),
        review_status=str(payload.get("review_status", "PENDING_CLINICAL_REVIEW")),
        conflict_status=str(payload.get("conflict_status", "")),
    )


def retrieval_eligibility(
    candidate: RetrievalCandidate,
    *,
    mode: DataMode,
    citations: CitationRegistry,
) -> EligibilityDecision:
    table = candidate.origin_table
    if table in _FORBIDDEN_TABLES:
        return EligibilityDecision(False, EligibilityReason.FORBIDDEN_TABLE)
    if table not in _ELIGIBLE_TABLES:
        return EligibilityDecision(False, EligibilityReason.TABLE_NOT_ALLOWLISTED)
    if not candidate.text.strip() or not candidate.content_hash:
        return EligibilityDecision(False, EligibilityReason.EMPTY_CONTENT)
    if (
        candidate.conflict_status.upper() in {"CONFLICT", "REJECTED"}
        or candidate.canonical_status.upper() == "REJECTED"
    ):
        return EligibilityDecision(False, EligibilityReason.CONFLICT_OR_REJECTED)
    if mode == "production" and (
        candidate.canonical_status.upper() not in _PRODUCTION_STATUSES
        or candidate.review_status.upper() not in _PRODUCTION_REVIEW_STATUSES
    ):
        return EligibilityDecision(False, EligibilityReason.UNAPPROVED_PRODUCTION)
    try:
        citations.resolve(candidate.source_ids)
    except ValueError:
        return EligibilityDecision(False, EligibilityReason.NO_CANONICAL_SOURCE)
    return EligibilityDecision(True, EligibilityReason.ELIGIBLE)


@dataclass(frozen=True, slots=True)
class BackfillPlan:
    candidate_count: int
    eligible_count: int
    total_characters: int
    estimated_chunks: int
    registry_digest: str
    full_backfill_permitted: bool
    refusal_reason: str = ""


def plan_embedding_backfill(
    candidates: Iterable[RetrievalCandidate],
    *,
    mode: DataMode,
    citations: CitationRegistry,
    allow_full_backfill: bool = False,
    persistent_pgvector_ready: bool = False,
) -> BackfillPlan:
    """Plan without calling an embedding API or writing generated vectors."""
    all_candidates = tuple(candidates)
    eligible = tuple(
        candidate
        for candidate in all_candidates
        if retrieval_eligibility(candidate, mode=mode, citations=citations).eligible
    )
    total_characters = sum(len(candidate.text) for candidate in eligible)
    estimated_chunks = sum(max(1, (len(candidate.text) + 899) // 900) for candidate in eligible)
    digest_input = "\n".join(
        sorted(f"{item.origin_table}\0{item.origin_row_id}\0{item.content_hash}" for item in eligible)
    )
    permitted = allow_full_backfill and persistent_pgvector_ready
    if permitted:
        refusal = ""
    elif not allow_full_backfill:
        refusal = "VMEC_ALLOW_FULL_EMBEDDING_BACKFILL is not enabled"
    else:
        refusal = "persistent PostgreSQL/pgvector is not verified"
    return BackfillPlan(
        candidate_count=len(all_candidates),
        eligible_count=len(eligible),
        total_characters=total_characters,
        estimated_chunks=estimated_chunks,
        registry_digest=hashlib.sha256(digest_input.encode()).hexdigest(),
        full_backfill_permitted=permitted,
        refusal_reason=refusal,
    )
