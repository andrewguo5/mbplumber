"""Tests for the data-source resolution ladder (resolve_data_source).

Precedence, highest first: CLI value > MBPLUMBER_DATA env var > config
input.data_source > DEFAULT_DATA_SOURCE.
"""

from __future__ import annotations

from pathlib import Path

from mbplumber.config import (
    DATA_SOURCE_ENV_VAR,
    DEFAULT_DATA_SOURCE,
    Config,
    resolve_data_source,
)


def _config_with_source(source: str | None) -> Config:
    cfg = Config()
    cfg.input.data_source = source
    return cfg


def test_cli_value_wins_over_everything(monkeypatch):
    monkeypatch.setenv(DATA_SOURCE_ENV_VAR, "/from/env")
    cfg = _config_with_source("/from/config")
    assert resolve_data_source("/from/cli", cfg) == Path("/from/cli")


def test_env_var_used_when_no_cli_value(monkeypatch):
    monkeypatch.setenv(DATA_SOURCE_ENV_VAR, "/from/env")
    cfg = _config_with_source("/from/config")
    assert resolve_data_source(None, cfg) == Path("/from/env")


def test_config_used_when_no_cli_or_env(monkeypatch):
    monkeypatch.delenv(DATA_SOURCE_ENV_VAR, raising=False)
    cfg = _config_with_source("/from/config")
    assert resolve_data_source(None, cfg) == Path("/from/config")


def test_default_used_when_nothing_set(monkeypatch):
    monkeypatch.delenv(DATA_SOURCE_ENV_VAR, raising=False)
    assert resolve_data_source(None, Config()) == DEFAULT_DATA_SOURCE


def test_user_home_is_expanded(monkeypatch):
    monkeypatch.delenv(DATA_SOURCE_ENV_VAR, raising=False)
    resolved = resolve_data_source("~/hands", Config())
    assert "~" not in str(resolved)
    assert resolved == Path("~/hands").expanduser()
