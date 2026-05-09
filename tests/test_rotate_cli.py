"""Tests for ``rtdm rotate`` and ``config.update_api_key``.

Rotate is the dangerous subcommand — losing the new key after the
server-side revoke locks the user out.  Pinned behaviour:

* refuses local mode and missing key (no network call)
* refuses without 'y' confirmation (no network call)
* atomic config write: tmp + os.replace + chmod 600
* config write failure after a successful rotation prints the new key
  prominently to stderr so the user can recover by hand
* network/HTTP errors surface as non-zero exits with useful messages
"""

from __future__ import annotations

import io
import os
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from rtdm import config as config_module
from rtdm import rotate_cli
from rtdm.config import Config, LocalConfig, RemoteConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _remote_cfg(api_key: str | None = "rtdm_live_old_key") -> Config:
    return Config(
        mode="remote",
        local=LocalConfig(),
        remote=RemoteConfig(api_key=api_key, endpoint="https://rtdm.sh"),
    )


def _local_cfg() -> Config:
    return Config(mode="local", local=LocalConfig(), remote=RemoteConfig())


def _mock_response(status: int, body: dict | None = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status
    resp.json.return_value = body if body is not None else {}
    return resp


def _patch_client(resp: MagicMock):
    cm = MagicMock()
    cm.__enter__.return_value.post.return_value = resp
    cm.__exit__.return_value = False
    return patch("rtdm.rotate_cli.httpx.Client", return_value=cm)


def _stdin(answer: str):
    """Replace sys.stdin so .readline() returns ``answer``."""
    return patch("sys.stdin", io.StringIO(answer))


# ---------------------------------------------------------------------------
# rotate_cli.run
# ---------------------------------------------------------------------------


def test_local_mode_rejected(monkeypatch, capsys):
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda: _local_cfg())
    rc = rotate_cli.run()
    assert rc == 1
    assert "remote mode" in capsys.readouterr().err.lower()


def test_missing_api_key(monkeypatch, capsys):
    monkeypatch.setattr(
        rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg(api_key=None)
    )
    rc = rotate_cli.run()
    assert rc == 1
    assert "api key" in capsys.readouterr().err.lower()


def test_user_says_no(monkeypatch, capsys):
    """A 'no' (or empty) confirmation aborts before any network call."""
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())
    with _stdin("n\n"), \
         patch("rtdm.rotate_cli.httpx.Client") as mock_client:
        rc = rotate_cli.run()
    assert rc == 0
    mock_client.assert_not_called()
    assert "aborted" in capsys.readouterr().out.lower()


def test_happy_path_writes_new_key(monkeypatch, tmp_path, capsys):
    """y → POST → 200 → new key written to config file with mode 0600."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text(
        'mode = "remote"\n[remote]\napi_key = "rtdm_live_old"\n'
        'endpoint = "https://rtdm.sh"\n[local]\nollama_url = "http://localhost:11434"\n'
        'model = "qwen2.5-coder:7b-instruct-q4_K_M"\n'
    )
    monkeypatch.setattr(config_module, "default_config_path", lambda: cfg_path)
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())

    new_key = "rtdm_live_brand_new_key_42"
    resp = _mock_response(200, {"api_key": new_key})

    with _stdin("y\n"), _patch_client(resp):
        rc = rotate_cli.run()

    assert rc == 0
    body = cfg_path.read_text()
    assert new_key in body
    assert "rtdm_live_old" not in body
    # File must be 0600 (best-effort on POSIX).
    if os.name == "posix":
        mode = stat.S_IMODE(cfg_path.stat().st_mode)
        assert mode == 0o600


def test_auth_header_is_old_key(monkeypatch, tmp_path):
    """Bearer header sent to the server is the *old* key."""
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('mode = "remote"\n[remote]\napi_key = "x"\n')
    monkeypatch.setattr(config_module, "default_config_path", lambda: cfg_path)
    monkeypatch.setattr(
        rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg(api_key="rtdm_live_OLD")
    )
    resp = _mock_response(200, {"api_key": "rtdm_live_NEW_xxxxxxxxxx"})

    with _stdin("y\n"), _patch_client(resp) as patcher:
        rotate_cli.run()

    post_call = patcher.return_value.__enter__.return_value.post.call_args
    assert post_call.kwargs["headers"]["Authorization"] == "Bearer rtdm_live_OLD"


def test_401_returns_error(monkeypatch, capsys):
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())
    with _stdin("y\n"), _patch_client(_mock_response(401)):
        rc = rotate_cli.run()
    assert rc == 1
    assert "invalid or revoked" in capsys.readouterr().err.lower()


def test_403_returns_error(monkeypatch, capsys):
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())
    with _stdin("y\n"), _patch_client(_mock_response(403)):
        rc = rotate_cli.run()
    assert rc == 1
    assert "subscription" in capsys.readouterr().err.lower()


def test_unexpected_status_does_not_touch_config(monkeypatch, tmp_path, capsys):
    """A non-200 response leaves the config file untouched."""
    cfg_path = tmp_path / "config.toml"
    original = 'mode = "remote"\n[remote]\napi_key = "rtdm_live_keep_me"\n'
    cfg_path.write_text(original)
    monkeypatch.setattr(config_module, "default_config_path", lambda: cfg_path)
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())

    with _stdin("y\n"), _patch_client(_mock_response(500)):
        rc = rotate_cli.run()

    assert rc == 1
    assert cfg_path.read_text() == original


def test_network_error_returns_1(monkeypatch, capsys):
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())
    bad = MagicMock()
    bad.__enter__.return_value.post.side_effect = httpx.ConnectError("down")
    bad.__exit__.return_value = False
    with _stdin("y\n"), patch("rtdm.rotate_cli.httpx.Client", return_value=bad):
        rc = rotate_cli.run()
    assert rc == 1
    assert "internet" in capsys.readouterr().err.lower()


def test_config_write_failure_prints_key_to_stderr(monkeypatch, capsys):
    """If update_api_key raises, the new key is printed prominently.

    This is the worst-case path: the server has already revoked the
    old key.  Failing silently would lock the user out.
    """
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())
    new_key = "rtdm_live_PANIC_save_me_xxxx"
    resp = _mock_response(200, {"api_key": new_key})

    with _stdin("y\n"), _patch_client(resp), \
         patch.object(
             rotate_cli.config_module,
             "update_api_key",
             side_effect=OSError("disk full"),
         ):
        rc = rotate_cli.run()

    assert rc == 1
    err = capsys.readouterr().err
    assert new_key in err
    assert "save" in err.lower() or "save this key" in err.lower()


def test_unexpected_body_shape_is_loud(monkeypatch, capsys):
    """200 with a missing api_key field surfaces a 'rotate again' message."""
    monkeypatch.setattr(rotate_cli.config_module, "load_config", lambda *a, **kw: _remote_cfg())
    resp = _mock_response(200, {"unexpected": "field"})
    with _stdin("y\n"), _patch_client(resp):
        rc = rotate_cli.run()
    assert rc == 1
    assert "rotate again" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# config.update_api_key
# ---------------------------------------------------------------------------


def test_update_api_key_writes_new_key(tmp_path):
    """update_api_key replaces only the api_key, preserves other fields."""
    p = tmp_path / "config.toml"
    p.write_text(
        'mode = "remote"\n'
        '[remote]\n'
        'api_key = "rtdm_live_oooooooooooooooooooooooooooooooo"\n'
        'endpoint = "https://example.com"\n'
        '[local]\nollama_url = "http://x:1"\nmodel = "custom-model"\n'
    )

    new_key = "rtdm_live_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn"
    out = config_module.update_api_key(new_key, path=p)

    assert out == p
    cfg = config_module.load_config(p)
    assert cfg.remote.api_key == new_key
    # Other fields preserved.
    assert cfg.remote.endpoint == "https://example.com"
    assert cfg.local.ollama_url == "http://x:1"
    assert cfg.local.model == "custom-model"


def test_update_api_key_uses_atomic_replace(tmp_path):
    """The actual write goes via os.replace (so a crash mid-write doesn't truncate)."""
    p = tmp_path / "config.toml"
    p.write_text(
        'mode = "remote"\n[remote]\n'
        'api_key = "rtdm_live_oooooooooooooooooooooooooooooooo"\n'
    )

    with patch("rtdm.config.os.replace") as mock_replace:
        config_module.update_api_key(
            "rtdm_live_nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn", path=p
        )

    mock_replace.assert_called_once()
    args = mock_replace.call_args.args
    assert str(args[0]).endswith(".toml.tmp")
    assert args[1] == p


def test_update_api_key_creates_parent(tmp_path):
    """Missing parent dir is created on first rotate."""
    p = tmp_path / "deep" / "nested" / "config.toml"
    config_module.update_api_key("rtdm_live_init_zzzzzzzzz", path=p)
    assert p.exists()


def test_update_api_key_sets_0600_on_posix(tmp_path):
    if os.name != "posix":
        pytest.skip("chmod 0o600 only meaningful on POSIX")
    p = tmp_path / "config.toml"
    config_module.update_api_key("rtdm_live_perms_test_aaaa", path=p)
    mode = stat.S_IMODE(p.stat().st_mode)
    assert mode == 0o600
