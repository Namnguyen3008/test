from pathlib import Path

import pytest

from src.main import validate_data_readiness


def test_production_data_mode_fails_closed_without_approved_corpus(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(RuntimeError, match="approved corpus"):
        validate_data_readiness("production")


def test_development_mode_can_run_without_approved_corpus(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    validate_data_readiness("development")
