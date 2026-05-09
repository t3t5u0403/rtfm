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
            api_key = "rtdm_live_abcdefghijklmnopqrstuvwxyz012345"
            endpoint = "https://example.invalid"

            [local]
            ollama_url = "http://10.0.0.5:11434"
            model = "custom-model"
            """
        ).strip()
    )
    cfg = load_config(p)

    assert cfg.mode == "remote"
    assert cfg.remote.api_key == "rtdm_live_abcdefghijklmnopqrstuvwxyz012345"
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
    p.write_text(
        'mode = "remote"\n[remote]\n'
        'api_key = "rtdm_live_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"\n'
    )
    monkeypatch.setenv("RTDM_MODE", "loopback")
    cfg = load_config(p)
    assert cfg.mode == "remote"


def test_default_path_honours_xdg(monkeypatch, tmp_path):
    """default_config_path uses XDG_CONFIG_HOME when set."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config_module.default_config_path() == tmp_path / "rtdm" / "config.toml"


def test_load_config_rejects_corrupted_api_key(tmp_path, monkeypatch):
    """An api_key that doesn't match the canonical shape raises a clear error.

    Defence in depth: even if the file is hand-edited or a byte gets
    flipped on disk, the next CLI invocation refuses to use the key
    instead of producing an opaque httpx encoding traceback later.
    """
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "corrupt.toml"
    p.write_text(
        'mode = "remote"\n[remote]\napi_key = "rtdm_live_too_short"\n'
    )
    with pytest.raises(ValueError, match="Invalid api_key in config"):
        load_config(p)


def test_load_config_accepts_valid_key(tmp_path, monkeypatch):
    """A canonical 42-char ``rtdm_live_<32 chars>`` key loads cleanly."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    valid = "rtdm_live_" + "z" * 32
    p = tmp_path / "valid.toml"
    p.write_text(f'mode = "remote"\n[remote]\napi_key = "{valid}"\n')

    cfg = load_config(p)
    assert cfg.remote.api_key == valid


# ---------------------------------------------------------------------------
# is_valid_endpoint + load-time enforcement (audit #2: cleartext bearer leak)
# ---------------------------------------------------------------------------


def test_https_endpoint_accepted(tmp_path, monkeypatch):
    """An ordinary https:// endpoint loads cleanly."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "ok.toml"
    p.write_text('mode = "remote"\n[remote]\nendpoint = "https://rtdm.sh"\n')
    cfg = load_config(p)
    assert cfg.remote.endpoint == "https://rtdm.sh"


def test_http_endpoint_rejected_in_load(tmp_path, monkeypatch):
    """A non-loopback http:// endpoint raises rather than ship a cleartext token."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "leaky.toml"
    p.write_text('mode = "remote"\n[remote]\nendpoint = "http://rtdm.sh"\n')
    with pytest.raises(ValueError, match="Invalid endpoint in config"):
        load_config(p)


def test_http_localhost_endpoint_accepted(tmp_path, monkeypatch):
    """http://localhost:8000 is allowed for self-hosted dev."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    for url in (
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://[::1]:8000",
    ):
        p = tmp_path / "loop.toml"
        p.write_text(f'mode = "remote"\n[remote]\nendpoint = "{url}"\n')
        cfg = load_config(p)
        assert cfg.remote.endpoint == url


def test_endpoint_with_path_rejected(tmp_path, monkeypatch):
    """A path-bearing endpoint would mangle the /v1/... join — refuse it."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "path.toml"
    p.write_text('mode = "remote"\n[remote]\nendpoint = "https://rtdm.sh/api"\n')
    with pytest.raises(ValueError, match="Invalid endpoint in config"):
        load_config(p)


def test_endpoint_with_query_rejected(tmp_path, monkeypatch):
    """A ``?token=...`` baked into the endpoint would leak on every request."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "query.toml"
    p.write_text(
        'mode = "remote"\n[remote]\nendpoint = "https://rtdm.sh?token=leak"\n'
    )
    with pytest.raises(ValueError, match="Invalid endpoint in config"):
        load_config(p)


def test_endpoint_with_userinfo_rejected(tmp_path, monkeypatch):
    """https://user:pass@host fights with Bearer auth — refuse."""
    monkeypatch.delenv("RTDM_MODE", raising=False)
    p = tmp_path / "userinfo.toml"
    p.write_text(
        'mode = "remote"\n[remote]\nendpoint = "https://u:p@rtdm.sh"\n'
    )
    with pytest.raises(ValueError, match="Invalid endpoint in config"):
        load_config(p)
