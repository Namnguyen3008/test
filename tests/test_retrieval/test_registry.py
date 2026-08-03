from services.retrieval import (
    Citation,
    CitationRegistry,
    EligibilityReason,
    RetrievalCandidate,
    candidate_from_dataset_row,
    plan_embedding_backfill,
    retrieval_eligibility,
)


def candidate(**overrides) -> RetrievalCandidate:
    values = {
        "origin_table": "routing_rows",
        "origin_row_id": "route-1",
        "text": "Nội dung định tuyến có nguồn",
        "content_hash": "a" * 64,
        "source_ids": ("SOURCE-1",),
        "canonical_status": "REVIEW_REQUIRED",
        "review_status": "PENDING_CLINICAL_REVIEW",
        "conflict_status": "",
    }
    values.update(overrides)
    return RetrievalCandidate(**values)


def citations() -> CitationRegistry:
    return CitationRegistry({"SOURCE-1": Citation("SOURCE-1", "https://example.test/source")})


def test_development_registry_accepts_allowlisted_sourced_review_content() -> None:
    decision = retrieval_eligibility(candidate(), mode="development", citations=citations())
    assert decision.eligible
    assert decision.reason is EligibilityReason.ELIGIBLE


def test_registry_excludes_patient_history_security_evals_conflicts_and_unknown_tables() -> None:
    cases = (
        (candidate(origin_table="hold_events"), EligibilityReason.FORBIDDEN_TABLE),
        (candidate(origin_table="prompt_injection"), EligibilityReason.FORBIDDEN_TABLE),
        (candidate(origin_table="synthetic_profiles"), EligibilityReason.FORBIDDEN_TABLE),
        (candidate(conflict_status="CONFLICT"), EligibilityReason.CONFLICT_OR_REJECTED),
        (candidate(origin_table="random_table"), EligibilityReason.TABLE_NOT_ALLOWLISTED),
    )
    for item, reason in cases:
        decision = retrieval_eligibility(item, mode="development", citations=citations())
        assert not decision.eligible
        assert decision.reason is reason


def test_registry_requires_canonical_source_and_production_approval() -> None:
    no_source = retrieval_eligibility(candidate(source_ids=()), mode="development", citations=citations())
    unapproved = retrieval_eligibility(candidate(), mode="production", citations=citations())
    approved = retrieval_eligibility(
        candidate(canonical_status="ACCEPTED", review_status="CLINICALLY_APPROVED"),
        mode="production",
        citations=citations(),
    )
    assert no_source.reason is EligibilityReason.NO_CANONICAL_SOURCE
    assert unapproved.reason is EligibilityReason.UNAPPROVED_PRODUCTION
    assert approved.eligible


def test_citation_registry_rejects_noncanonical_ids() -> None:
    registry = citations()
    try:
        registry.resolve(("MISSING",))
    except ValueError as error:
        assert "MISSING" in str(error)
    else:  # pragma: no cover
        raise AssertionError("unknown source must not resolve")


def test_citation_registry_rejects_invalid_canonical_metadata() -> None:
    try:
        CitationRegistry({"SOURCE-1": Citation("DIFFERENT", "javascript:alert(1)")})
    except ValueError as error:
        assert "SOURCE-1" in str(error)
    else:  # pragma: no cover
        raise AssertionError("invalid citation metadata must not be accepted")


def test_global_source_ledger_bridge_resolves_local_ids_to_canonical_ids() -> None:
    registry = CitationRegistry.from_global_ledger(
        [
            {
                "global_source_id": "GLOBAL_SRC_1",
                "source_id": "LOCAL_1",
                "canonical_url": "https://example.test/canonical",
                "source_title": "Canonical source",
            }
        ]
    )
    resolved = registry.resolve(("LOCAL_1",))
    assert resolved == (Citation("GLOBAL_SRC_1", "https://example.test/canonical", "Canonical source"),)


def test_ambiguous_ledger_alias_is_excluded_instead_of_misresolved() -> None:
    registry = CitationRegistry.from_global_ledger(
        [
            {"global_source_id": "GLOBAL_1", "source_id": "LOCAL", "canonical_url": "https://one.test"},
            {"global_source_id": "GLOBAL_2", "source_id": "LOCAL", "canonical_url": "https://two.test"},
        ]
    )
    try:
        registry.resolve(("LOCAL",))
    except ValueError as error:
        assert "LOCAL" in str(error)
    else:  # pragma: no cover
        raise AssertionError("ambiguous alias must not resolve")


def test_embedding_plan_is_deterministic_and_refuses_unapproved_full_run() -> None:
    candidates = [candidate(), candidate(origin_row_id="route-2", text="x" * 901, content_hash="b" * 64)]
    first = plan_embedding_backfill(candidates, mode="development", citations=citations())
    second = plan_embedding_backfill(reversed(candidates), mode="development", citations=citations())

    assert first.registry_digest == second.registry_digest
    assert first.eligible_count == 2
    assert first.estimated_chunks == 3
    assert not first.full_backfill_permitted
    assert "VMEC_ALLOW_FULL_EMBEDDING_BACKFILL" in first.refusal_reason


def test_embedding_plan_requires_both_flag_and_persistent_pgvector() -> None:
    blocked = plan_embedding_backfill(
        [candidate()],
        mode="development",
        citations=citations(),
        allow_full_backfill=True,
        persistent_pgvector_ready=False,
    )
    allowed = plan_embedding_backfill(
        [candidate()],
        mode="development",
        citations=citations(),
        allow_full_backfill=True,
        persistent_pgvector_ready=True,
    )
    assert not blocked.full_backfill_permitted
    assert "pgvector" in blocked.refusal_reason
    assert allowed.full_backfill_permitted


def test_dataset_row_projection_keeps_only_retrieval_fields_and_sources() -> None:
    projected = candidate_from_dataset_row(
        "routing_rows",
        "route-1",
        "a" * 64,
        {
            "user_utterance_vi": "Tôi cần tìm chuyên khoa phù hợp",
            "source_ids": "SOURCE-1|SOURCE-2",
            "secondary_source_id": "SOURCE-2",
            "canonical_status": "REVIEW_REQUIRED",
            "private_note": "must not be retained",
        },
    )

    assert projected.text == "Tôi cần tìm chuyên khoa phù hợp"
    assert projected.source_ids == ("SOURCE-1", "SOURCE-2")
    assert not hasattr(projected, "private_note")
