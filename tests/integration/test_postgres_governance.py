from __future__ import annotations

import base64
import hashlib
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from src.governance.canonical import canonical_json, digest, signature_payload
from src.governance.manifest import GovernanceManifest, TrustRegistry, verify_receipt
from src.governance.promotion import GovernancePromotionRepository, PromotionRecord, scope_snapshot

POSTGRES_URL = os.environ.get("VMEC_TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="VMEC_TEST_POSTGRES_URL is not configured")


def _key(capability: str) -> tuple[Ed25519PrivateKey, dict[str, object]]:
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes_raw()
    return private, {
        "key_id": hashlib.sha256(public).hexdigest(),
        "algorithm": "Ed25519",
        "public_key_base64": base64.b64encode(public).decode(),
        "capabilities": [capability],
        "valid_from": "2026-01-01T00:00:00Z",
        "not_after": "2027-01-01T00:00:00Z",
        "revoked_at": None,
        "revocation_reason": None,
    }


def test_postgres_promotion_is_atomic_signed_idempotent_and_append_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    factory = sessionmaker(engine, expire_on_commit=False)
    suffix = uuid.uuid4().hex
    release_uuid = str(uuid.uuid4())
    logical_release = f"governance-integration-{suffix}"
    source_id = f"GOV-SOURCE-{suffix}"
    ordinary_id = str(uuid.uuid4())
    gold_id = str(uuid.uuid4())
    normalized_text_hash = hashlib.sha256(b"test").hexdigest()
    records = [
        PromotionRecord(
            ordinary_id,
            logical_release,
            "faq",
            "ordinary",
            hashlib.sha256(f"ordinary-{suffix}".encode()).hexdigest(),
            "REVIEW_REQUIRED",
            "PENDING_CLINICAL_REVIEW",
            "NONE",
            (source_id,),
            normalized_text_hash=normalized_text_hash,
        ),
        PromotionRecord(
            gold_id,
            logical_release,
            "adult_emergency_rules",
            "gold",
            hashlib.sha256(f"gold-{suffix}".encode()).hexdigest(),
            "REVIEW_REQUIRED",
            "PENDING_GOLD_REVIEW",
            "",
            (source_id,),
            True,
            True,
            normalized_text_hash,
            "SAFETY_CRITICAL_TABLE_V1",
        ),
    ]
    snapshot = scope_snapshot(records)
    with factory() as session, session.begin():
        session.execute(
            text(
                "INSERT INTO dataset_releases(id,logical_release_id,mode,source_hashes,status,registry_digest,"
                "imported_records) VALUES(:id,:logical,'review','{}'::jsonb,'completed',:registry,2)"
            ),
            {"id": release_uuid, "logical": logical_release, "registry": snapshot.registry_digest},
        )
        session.execute(
            text(
                "INSERT INTO global_sources(id,canonical_url,title,metadata) "
                "VALUES(:id,:url,'governance integration','{}'::jsonb)"
            ),
            {"id": source_id, "url": f"https://example.test/{suffix}"},
        )
        session.execute(
            text("INSERT INTO dataset_release_sources(release_id,source_id) VALUES(:release_id,:source_id)"),
            {"release_id": release_uuid, "source_id": source_id},
        )
        for record in records:
            session.execute(
                text(
                    "INSERT INTO knowledge_records(id,release_id,origin_table,origin_row_id,mode,canonical_status,"
                    "review_status,conflict_status,normalized_text,content_hash,metadata) VALUES(:id,:release_id,"
                    ":table,:row_id,'review','REVIEW_REQUIRED',:review_status,:conflict,'test',:content_hash,'{}'::jsonb)"
                ),
                {
                    "id": record.record_id,
                    "release_id": release_uuid,
                    "table": record.origin_table,
                    "row_id": record.origin_row_id,
                    "review_status": record.review_status,
                    "conflict": record.conflict_status,
                    "content_hash": record.content_hash,
                },
            )
            session.execute(
                text(
                    "INSERT INTO knowledge_record_sources(record_id,source_id,evidence_locator) VALUES(:id,:source,'')"
                ),
                {"id": record.record_id, "source": source_id},
            )

    approval_private, approval_key = _key("APPROVAL_MANIFEST")
    receipt_private, receipt_key = _key("PROMOTION_RECEIPT")
    now = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)
    raw = {
        "schema_version": "vmec.governance-approval.v1",
        "manifest_id": f"manifest-{suffix}",
        "project_id": "VMEC-01",
        "release_scope": {
            "release_ids": [logical_release],
            "registry_digest": snapshot.registry_digest,
            "expected_rows": 2,
            "canonical_sources": 1,
            "included_tables": ["adult_emergency_rules", "faq"],
            "included_row_hashes_digest": snapshot.row_hashes_digest,
        },
        "policy": {
            "policy_version": "vmec-governance-policy-v1",
            "accepted_policy": "ALL_ELIGIBLE_IN_SCOPE",
            "gold_policy": "EXPLICIT_GOLD_CANDIDATES_TWO_REVIEWERS",
        },
        "reviewers": [
            {
                "reviewer_id": "integration-reviewer-one",
                "organization": "Test Hospital",
                "authorization_reference": "TEST-AUTH-ONE",
                "scope": ["ALL_APPROVED_RELEASE_ROWS", "SAFETY_CRITICAL_AND_GOLD_CANDIDATES"],
                "decision": "APPROVE",
                "reviewed_at": (now - timedelta(hours=2)).isoformat(),
            },
            {
                "reviewer_id": "integration-reviewer-two",
                "organization": "Test Hospital",
                "authorization_reference": "TEST-AUTH-TWO",
                "scope": ["SAFETY_CRITICAL_AND_GOLD_CANDIDATES"],
                "decision": "APPROVE",
                "reviewed_at": (now - timedelta(hours=1)).isoformat(),
            },
        ],
        "owner_authorization": {
            "owner_id": "integration-owner",
            "authorization_reference": "TEST-OWNER-AUTH",
            "authorized_at": (now - timedelta(minutes=30)).isoformat(),
        },
        "evidence_package": {"schema_version": "vmec.review-evidence.v1", "package_digest": "e" * 64},
        "promotion": {
            "accepted_mode": "PROMOTE_ALL_ELIGIBLE_IN_SCOPE",
            "gold_mode": "PROMOTE_POLICY_GOLD_ONLY",
        },
        "issued_at": (now - timedelta(minutes=10)).isoformat(),
        "expires_at": (now + timedelta(days=1)).isoformat(),
        "signature": {
            "algorithm": "Ed25519",
            "key_id": approval_key["key_id"],
            "value_base64": base64.b64encode(b"0" * 64).decode(),
        },
    }
    evidence_payload = {
        "schema_version": "vmec.review-evidence.v1",
        "release_id": logical_release,
        "included_row_hashes_digest": snapshot.row_hashes_digest,
    }
    evidence = {**evidence_payload, "package_digest": digest(evidence_payload)}
    raw["evidence_package"]["package_digest"] = evidence["package_digest"]
    unsigned = GovernanceManifest.model_validate(raw)
    raw["signature"]["value_base64"] = base64.b64encode(
        approval_private.sign(signature_payload(unsigned.model_dump(mode="json")))
    ).decode()
    manifest = GovernanceManifest.model_validate(raw)
    registry = TrustRegistry.model_validate(
        {"schema_version": "vmec.governance-trust-registry.v1", "keys": [approval_key, receipt_key]}
    )
    receipt_key_path = tmp_path / "receipt.key"
    receipt_key_path.write_text(base64.b64encode(receipt_private.private_bytes_raw()).decode(), encoding="ascii")
    evidence_path = tmp_path / "evidence.json"
    evidence_path.write_bytes(canonical_json(evidence))
    monkeypatch.setenv("VMEC_ALLOW_GOVERNANCE_PROMOTION", "true")
    repository = GovernancePromotionRepository(factory)
    function_name = f"vmec_test_governance_fail_{suffix}"
    trigger_name = f"governance_fail_{suffix}"
    with factory() as session, session.begin():
        session.execute(
            text(
                f"CREATE FUNCTION {function_name}() RETURNS trigger AS $$ BEGIN "
                "RAISE EXCEPTION 'injected governance rollback'; END; $$ LANGUAGE plpgsql"
            )
        )
        session.execute(
            text(
                f"CREATE TRIGGER {trigger_name} BEFORE INSERT ON governance_row_promotions "
                f"FOR EACH ROW WHEN (NEW.source_record_id = '{ordinary_id}'::uuid) "
                f"EXECUTE FUNCTION {function_name}()"
            )
        )
    with pytest.raises(DBAPIError, match="injected governance rollback"):
        repository.promote(manifest, registry, receipt_key_path=receipt_key_path, evidence_path=evidence_path, now=now)
    with factory() as session:
        assert (
            session.execute(
                text("SELECT count(*) FROM governance_manifests WHERE manifest_id=:id"),
                {"id": manifest.manifest_id},
            ).scalar_one()
            == 0
        )
        assert (
            session.execute(
                text("SELECT count(*) FROM dataset_releases WHERE logical_release_id='vmec-production-v1'")
            ).scalar_one()
            == 0
        )
    with factory() as session, session.begin():
        session.execute(text(f"DROP TRIGGER {trigger_name} ON governance_row_promotions"))
        session.execute(text(f"DROP FUNCTION {function_name}()"))
    first = repository.promote(
        manifest, registry, receipt_key_path=receipt_key_path, evidence_path=evidence_path, now=now
    )
    second = repository.promote(
        manifest, registry, receipt_key_path=receipt_key_path, evidence_path=evidence_path, now=now
    )
    assert first == second
    assert first["accepted_rows"] == 1
    assert first["gold_rows"] == 1
    assert len(verify_receipt(first, registry)) == 64
    same_id_tamper = manifest.model_dump(mode="json")
    same_id_tamper["expires_at"] = (now + timedelta(days=2)).isoformat()
    same_id_tamper["signature"]["value_base64"] = base64.b64encode(b"0" * 64).decode()
    unsigned_tamper = GovernanceManifest.model_validate(same_id_tamper)
    same_id_tamper["signature"]["value_base64"] = base64.b64encode(
        approval_private.sign(signature_payload(unsigned_tamper.model_dump(mode="json")))
    ).decode()
    with pytest.raises(RuntimeError, match="replayed with different bytes"):
        repository.promote(
            GovernanceManifest.model_validate(same_id_tamper),
            registry,
            receipt_key_path=receipt_key_path,
            evidence_path=evidence_path,
            now=now,
        )
    other_id = manifest.model_dump(mode="json")
    other_id["manifest_id"] = f"other-{suffix}"
    other_id["signature"]["value_base64"] = base64.b64encode(b"0" * 64).decode()
    unsigned_other = GovernanceManifest.model_validate(other_id)
    other_id["signature"]["value_base64"] = base64.b64encode(
        approval_private.sign(signature_payload(unsigned_other.model_dump(mode="json")))
    ).decode()
    with pytest.raises(RuntimeError, match="already bound"):
        repository.promote(
            GovernanceManifest.model_validate(other_id),
            registry,
            receipt_key_path=receipt_key_path,
            evidence_path=evidence_path,
            now=now,
        )
    with factory() as session:
        source_statuses = dict(
            session.execute(
                text("SELECT id::text,canonical_status FROM knowledge_records WHERE id=ANY(:ids)"),
                {"ids": [ordinary_id, gold_id]},
            )
        )
        assert source_statuses == {ordinary_id: "REVIEW_REQUIRED", gold_id: "REVIEW_REQUIRED"}
        production_statuses = dict(
            session.execute(
                text(
                    "SELECT kr.origin_row_id,kr.canonical_status FROM knowledge_records kr "
                    "JOIN dataset_releases dr ON dr.id=kr.release_id WHERE dr.logical_release_id='vmec-production-v1'"
                )
            )
        )
        assert production_statuses == {"ordinary": "ACCEPTED", "gold": "GOLD"}
        assert (
            session.execute(
                text("SELECT count(*) FROM governance_row_promotions WHERE manifest_id=:id"),
                {"id": manifest.manifest_id},
            ).scalar_one()
            == 2
        )
    with factory() as session, pytest.raises(DBAPIError, match="append-only"):
        with session.begin():
            session.execute(
                text("DELETE FROM governance_row_promotions WHERE manifest_id=:id"),
                {"id": manifest.manifest_id},
            )
