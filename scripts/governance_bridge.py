"""Offline draft/verify and gated PostgreSQL governance promotion CLI."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.governance.canonical import canonical_json, signature_payload, strict_json_loads
from src.governance.catalog import build_governance_draft
from src.governance.manifest import GovernanceManifest, TrustRegistry, verify_evidence, verify_manifest, verify_receipt
from src.governance.promotion import GovernancePromotionRepository


def _read_object(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError("governance artifact must be a regular file")
    return strict_json_loads(path.read_text(encoding="utf-8"))


def _draft(arguments: argparse.Namespace) -> dict[str, object]:
    output = Path(arguments.output).resolve()
    draft, evidence = build_governance_draft(Path(arguments.catalog), arguments.release_id, arguments.mode)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(draft) + b"\n")
    evidence_output = output.with_name(f"{output.stem}.evidence.json")
    evidence_output.write_bytes(canonical_json(evidence) + b"\n")
    return {
        "status": "DRAFT_CREATED_NOT_APPROVED",
        "draft_id": draft["draft_id"],
        "expected_rows": draft["release_scope"]["expected_rows"],
        "output": str(output),
        "evidence_output": str(evidence_output),
    }


def _registry(path: Path) -> TrustRegistry:
    return TrustRegistry.model_validate(_read_object(path))


def _sign(arguments: argparse.Namespace) -> dict[str, object]:
    raw = _read_object(Path(arguments.input))
    signature = raw.get("signature")
    if not isinstance(signature, dict) or set(signature) != {"algorithm", "key_id", "value_base64"}:
        raise ValueError("unsigned manifest requires the exact signature envelope")
    if signature.get("algorithm") != "Ed25519" or signature.get("value_base64") not in {"", None}:
        raise ValueError("unsigned manifest signature value must be empty")
    private_path = Path(arguments.private_key)
    if not private_path.is_file() or private_path.is_symlink():
        raise ValueError("approval private key must be a regular external file")
    try:
        private_raw = base64.b64decode(private_path.read_text(encoding="ascii").strip(), validate=True)
    except (UnicodeError, ValueError) as exc:
        raise ValueError("approval private key must be strict base64") from exc
    if len(private_raw) != 32:
        raise ValueError("approval private key must contain 32 Ed25519 private bytes")
    private = Ed25519PrivateKey.from_private_bytes(private_raw)
    key_id = hashlib.sha256(private.public_key().public_bytes_raw()).hexdigest()
    if signature.get("key_id") != key_id:
        raise ValueError("approval private key fingerprint does not match the manifest key id")
    trusted = _registry(Path(arguments.registry))
    if not any(key.key_id == key_id and "APPROVAL_MANIFEST" in key.capabilities for key in trusted.keys):
        raise ValueError("approval signing key is not registered for manifest capability")
    signature["value_base64"] = base64.b64encode(b"0" * 64).decode()
    unsigned = GovernanceManifest.model_validate(raw)
    signature["value_base64"] = base64.b64encode(
        private.sign(signature_payload(unsigned.model_dump(mode="json")))
    ).decode()
    signed = GovernanceManifest.model_validate(raw)
    verify_manifest(signed, trusted)
    verify_evidence(signed, Path(arguments.evidence))
    output = Path(arguments.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical_json(signed.model_dump(mode="json")) + b"\n")
    return {"status": "SIGNED_AND_VERIFIED", "manifest_id": signed.manifest_id, "output": str(output)}


def _verify(arguments: argparse.Namespace) -> dict[str, object]:
    manifest = GovernanceManifest.model_validate(_read_object(Path(arguments.manifest)))
    manifest_digest = verify_manifest(manifest, _registry(Path(arguments.registry)))
    evidence_digest = verify_evidence(manifest, Path(arguments.evidence))
    return {
        "status": "VERIFIED",
        "manifest_id": manifest.manifest_id,
        "manifest_digest": manifest_digest,
        "evidence_digest": evidence_digest,
    }


def _verify_receipt(arguments: argparse.Namespace) -> dict[str, object]:
    receipt = _read_object(Path(arguments.receipt))
    receipt_digest = verify_receipt(receipt, _registry(Path(arguments.registry)))
    return {"status": "VERIFIED", "promotion_id": receipt.get("promotion_id"), "receipt_digest": receipt_digest}


def _promote(arguments: argparse.Namespace) -> dict[str, object]:
    manifest_path = Path(os.environ.get("VMEC_GOVERNANCE_MANIFEST_PATH", ""))
    registry_path = Path(os.environ.get("VMEC_GOVERNANCE_PUBLIC_KEY_PATH", ""))
    receipt_key_path = Path(os.environ.get("VMEC_GOVERNANCE_RECEIPT_SIGNING_KEY_PATH", ""))
    evidence_path = Path(os.environ.get("VMEC_GOVERNANCE_EVIDENCE_PATH", ""))
    if not all((str(manifest_path), str(registry_path), str(receipt_key_path), str(evidence_path))):
        raise RuntimeError("required governance artifact paths are absent")
    database_url = arguments.database_url or os.environ.get("GOVERNANCE_DATABASE_URL", "")
    if not database_url.startswith(("postgresql://", "postgresql+")):
        raise RuntimeError("dedicated PostgreSQL governance database URL is absent")
    manifest = GovernanceManifest.model_validate(_read_object(manifest_path))
    registry = _registry(registry_path)
    engine = create_engine(database_url, pool_pre_ping=True)
    repository = GovernancePromotionRepository(sessionmaker(engine, expire_on_commit=False))
    receipt = repository.promote(manifest, registry, receipt_key_path=receipt_key_path, evidence_path=evidence_path)
    if arguments.receipt_output:
        output = Path(arguments.receipt_output).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(canonical_json(receipt) + b"\n")
    return {
        "status": "PROMOTED",
        "promotion_id": receipt["promotion_id"],
        "accepted_rows": receipt["accepted_rows"],
        "gold_rows": receipt["gold_rows"],
        "receipt_digest": __import__("hashlib").sha256(canonical_json(receipt)).hexdigest(),
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    draft = commands.add_parser("draft")
    draft.add_argument("--catalog", required=True)
    draft.add_argument("--release-id", required=True)
    draft.add_argument("--mode", choices=("development", "review"), required=True)
    draft.add_argument("--output", required=True)
    draft.set_defaults(handler=_draft)
    verify = commands.add_parser("verify")
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--registry", required=True)
    verify.add_argument("--evidence", required=True)
    verify.set_defaults(handler=_verify)
    verify_receipt = commands.add_parser("verify-receipt")
    verify_receipt.add_argument("--receipt", required=True)
    verify_receipt.add_argument("--registry", required=True)
    verify_receipt.set_defaults(handler=_verify_receipt)
    sign = commands.add_parser("sign")
    sign.add_argument("--input", required=True)
    sign.add_argument("--private-key", required=True)
    sign.add_argument("--registry", required=True)
    sign.add_argument("--evidence", required=True)
    sign.add_argument("--output", required=True)
    sign.set_defaults(handler=_sign)
    promote = commands.add_parser("promote")
    promote.add_argument("--database-url")
    promote.add_argument("--receipt-output")
    promote.set_defaults(handler=_promote)
    return result


def main() -> int:
    arguments = parser().parse_args()
    result = arguments.handler(arguments)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
