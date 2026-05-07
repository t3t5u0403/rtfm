"""Tests for ``rtdm whoami``.

Pure-local: no network mock needed.  Pin: the secret half of the API
key is never printed, the right fields show for each mode, and a
missing config file is surfaced honestly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from rtdm import whoami_cli
from rtdm.config import Config, LocalConfig, RemoteConfig


def _remote_cfg(api_key: str | None = "rtdm_live_abc123_xxxxxxxxxx_secrethere") -> Config:
    return Config(
        mode="remote",
        local=LocalConfig(),
        remote=RemoteConfig(api_key=api_key, endpoint="https://rtdm.sh"),
        source=Path("/tmp/fake/config.toml"),
    )


def _local_cfg(source: Path | None = Path("/tmp/fake/config.toml")) -> Config:
    return Config(
        mode="local",
        local=LocalConfig(ollama_url="http://localhost:11434", model="qwen2.5-coder:7b"),
        remote=RemoteConfig(),
        source=source,
    )


def test_whoami_remote_mode(monkeypatch, capsys):
    monkeypatch.setattr(whoami_cli.config_module, "load_config", lambda: _remote_cfg())
    rc = whoami_cli.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "remote" in out
    assert "https://rtdm.sh" in out
    # Prefix shown, secret half hidden.
    assert "rtdm_live_abc123" in out
    assert "secrethere" not in out


def test_whoami_local_mode_shows_local_fields(monkeypatch, capsys):
    monkeypatch.setattr(whoami_cli.config_module, "load_config", lambda: _local_cfg())
    rc = whoami_cli.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "local" in out
    assert "localhost:11434" in out
    assert "qwen2.5-coder" in out
    # No api_key line in local mode (it's irrelevant).
    assert "api_key" not in out


def test_whoami_no_config_file(monkeypatch, capsys):
    """Loading-from-defaults shows that explicitly."""
    monkeypatch.setattr(
        whoami_cli.config_module, "load_config", lambda: _local_cfg(source=None)
    )
    rc = whoami_cli.run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "no file on disk" in out.lower()


def test_whoami_no_network_call(monkeypatch, capsys):
    """whoami must NEVER touch httpx — fail loudly if it does."""
    import httpx

    def _explode(*_a, **_k):
        raise AssertionError("whoami must not make a network call")

    monkeypatch.setattr(httpx, "Client", _explode)
    monkeypatch.setattr(whoami_cli.config_module, "load_config", lambda: _remote_cfg())
    rc = whoami_cli.run()
    assert rc == 0


@pytest.mark.parametrize(
    "key,expected",
    [
        ("rtdm_live_abcdef_secret_xxx", "rtdm_live_abcdef…"),
        (None, "<unset>"),
        ("", "<unset>"),
        ("short", "short"),  # too short to mask; shown verbatim
    ],
)
def test_mask_key(key, expected):
    assert whoami_cli._mask_key(key) == expected
