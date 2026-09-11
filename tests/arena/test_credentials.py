"""Tests for safe credential resolution (env var first, then git-ignored key file)."""

import pytest

from src.arena import credentials
from src.arena.credentials import resolve_credential

ENV = "OPENROUTER_API_KEY"


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setattr(credentials, "_SECRETS_DIR", tmp_path)
    monkeypatch.setenv(ENV, "  sk-from-env  ")
    assert resolve_credential(ENV, "openrouter.key") == "sk-from-env"  # stripped


def test_falls_back_to_keyfile(monkeypatch, tmp_path):
    monkeypatch.setattr(credentials, "_SECRETS_DIR", tmp_path)
    monkeypatch.delenv(ENV, raising=False)
    (tmp_path / "openrouter.key").write_text("# my key\n\nsk-from-file\n", encoding="utf-8")
    assert resolve_credential(ENV, "openrouter.key") == "sk-from-file"  # skips comment/blank


def test_env_takes_precedence_over_keyfile(monkeypatch, tmp_path):
    monkeypatch.setattr(credentials, "_SECRETS_DIR", tmp_path)
    monkeypatch.setenv(ENV, "sk-env")
    (tmp_path / "openrouter.key").write_text("sk-file", encoding="utf-8")
    assert resolve_credential(ENV, "openrouter.key") == "sk-env"


def test_missing_everywhere_raises_clear_error(monkeypatch, tmp_path):
    monkeypatch.setattr(credentials, "_SECRETS_DIR", tmp_path)
    monkeypatch.delenv(ENV, raising=False)
    with pytest.raises(RuntimeError, match=ENV):
        resolve_credential(ENV, "openrouter.key")
