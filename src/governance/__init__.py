"""Fail-closed signed governance approval and promotion bridge."""

from .manifest import GovernanceManifest, TrustRegistry, verify_manifest

__all__ = ["GovernanceManifest", "TrustRegistry", "verify_manifest"]
