"""Automated End-to-End Verification for VMEC Docker Stack."""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request


def check_url(name: str, url: str, expected_status: int = 200, timeout: float = 5.0) -> bool:
    print(f"[*] Checking {name} ({url})...", end=" ")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "VMEC-Stack-Verifier/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            body = resp.read().decode("utf-8")
            if status == expected_status:
                print(f"[OK] (HTTP {status})")
                return True
            else:
                print(f"[FAIL] (Unexpected HTTP {status})")
                return False
    except Exception as exc:
        print(f"[ERROR] ({exc})")
        return False


def main() -> int:
    print("=" * 60)
    print("VMEC-01 Docker Stack Verification")
    print("=" * 60)

    checks = [
        ("FastAPI Health Endpoint", "http://localhost:8000/health", 200),
        ("FastAPI Readiness & Persistence Endpoint", "http://localhost:8000/ready", 200),
        ("Next.js Frontend Web App", "http://localhost:3000", 200),
    ]

    all_passed = True
    for name, url, status in checks:
        if not check_url(name, url, expected_status=status):
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("[SUCCESS] All baseline services are active and responding!")
        return 0
    else:
        print("[WARNING] One or more endpoints are not reachable yet.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
