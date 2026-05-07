"""Tests for the config loader."""

from __future__ import annotations

import textwrap

import pytest

from rtdm import config as config_module
from rtdm.config import (
    DEFAULT_OLLAMA_MODEL,
    DEFAULT_OLLAMA_URL,
    DEFAULT_REMOTE_ENDPOINT,
    load_config,
)


def test_load_config_default_when_no_file_exists(tmp_path, monkeypatch):
    """A missing file returns all defaults; mode is 'local'."""
    # Make sure no env override leaks in from the developer's shell.
    monkeypatch.delenv("RTDM_MODE", raising=False)
    cfg = load_config(tmp_path / "does-not-exist.toml")

    assert cfg.mode == "local"
    assert cfg.source is None
    assert cfg.local.ollama_url == DEFAULT_OLLAMA_URL
    assert cfg.local.model == DEFAULT_OLLAMA_MODEL
    assert cfg.remote.endpoint == DEFAULT_REMOTE_ENDPOINT
    assert cfg.remote.api_key is None


def test_load_config_reads_toml_correctly(tmp_path, monkeypatch):
    """A fully-populated config is reflected verbatim in the result."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "config.toml"
    p.write_text(
        textwrap.dedent(
            """
            mode = "remote"

            [remote]
            api_key = "rtdm_live_abc"
            endpoint = "https://example.invalid"

            [local]
            ollama_url = "http://10.0.0.5:11434"
            model = "custom-model"
            """
        ).strip()
    )
    cfg = load_config(p)

    assert cfg.mode == "remote"
    assert cfg.remote.api_key == "rtdm_live_abc"
    assert cfg.remote.endpoint == "https://example.invalid"
    assert cfg.local.ollama_url == "http://10.0.0.5:11434"
    assert cfg.local.model == "custom-model"
    assert cfg.source == p


def test_load_config_applies_defaults_for_missing_keys(tmp_path, monkeypatch):
    """A partial config inherits defaults for everything it omits."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "partial.toml"
    # Mode is set, but neither [remote] nor [local] sections exist.
    p.write_text('mode = "remote"\n')
    cfg = load_config(p)

    assert cfg.mode == "remote"
    assert cfg.remote.endpoint == DEFAULT_REMOTE_ENDPOINT
    assert cfg.remote.api_key is None
    assert cfg.local.ollama_url == DEFAULT_OLLAMA_URL
    assert cfg.local.model == DEFAULT_OLLAMA_MODEL


def test_env_var_overrides_mode(tmp_path, monkeypatch):
    """RTDM_MODE wins over whatever the file says."""
    p = tmp_path / "config.toml"
    p.write_text('mode = "local"\n')

    monkeypatch.setenv("RTDM_MODE", "remote")
    cfg = load_config(p)
    assert cfg.mode == "remote"

    monkeypatch.setenv("RTDM_MODE", "local")
    cfg = load_config(p)
    assert cfg.mode == "local"


def test_invalid_mode_falls_back_to_local(tmp_path, monkeypatch):
    """Garbage in 'mode' shouldn't crash; we fall back to 'local'."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "weird.toml"
    p.write_text('mode = "swarm"\n')
    cfg = load_config(p)
    assert cfg.mode == "local"


def test_unknown_env_mode_ignored(tmp_path, monkeypatch):
    """RTDM_MODE=garbage is silently ignored; the file's mode stands."""
    p = tmp_path / "config.toml"
    p.write_text('mode = "remote"\n[remote]\napi_key = "x"\n')
    monkeypatch.setenv("RTDM_MODE", "loopback")
    cfg = load_config(p)
    assert cfg.mode == "remote"


def test_default_path_honours_xdg(monkeypatch, tmp_path):
    """default_config_path uses XDG_CONFIG_HOME when set."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_module.default_config_path() == tmp_path / "rtdm" / "config.toml"
