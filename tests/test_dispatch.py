"""Tests for the dispatcher in rtdm.main.

We patch the two backends at their module-level functions so the
dispatcher logic can be exercised without ever opening a socket.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from rtdm import main as rtdm_main
from rtdm.config import Config, LocalConfig, RemoteConfig


def _local_cfg(**overrides) -> Config:
    return Config(
        mode=overrides.get("mode", "local"),
        local=LocalConfig(),
        remote=RemoteConfig(api_key=overrides.get("api_key")),
    )


def test_local_mode_uses_local_backend(monkeypatch, capsys):
    """In local mode the local backend is called and the remote one isn't."""
    cfg = _local_cfg(mode="local")
    monkeypatch.setattr(rtdm_main.config_module, "load_config", lambda: cfg)

    with patch("rtdm.main.local_backend.query", return_value="ls -la") as mock_local, \
         patch("rtdm.main.remote_backend.query") as mock_remote:
        rc = rtdm_main.main(["list", "files"])

    assert rc == 0
    mock_local.assert_called_once()
    mock_remote.assert_not_called()
    # Local backend is responsible for streaming; main does NOT
    # double-print in local mode.
    captured = capsys.readouterr()
    assert "ls -la" not in captured.out


def test_remote_mode_uses_remote_backend(monkeypatch, capsys):
    cfg = _local_cfg(mode="remote", api_key="rtdm_live_x")
    monkeypatch.setattr(rtdm_main.config_module, "load_config", lambda: cfg)

    with patch("rtdm.main.remote_backend.query", return_value="ls -la") as mock_remote, \
         patch("rtdm.main.local_backend.query") as mock_local:
        rc = rtdm_main.main(["list", "files"])

    assert rc == 0
    mock_remote.assert_called_once_with("list files", "rtdm_live_x", "https://rtdm.sh")
    mock_local.assert_not_called()
    # Remote mode prints the response (no streaming on the wire).
    captured = capsys.readouterr()
    assert "ls -la" in captured.out


def test_remote_mode_without_api_key_fails(monkeypatch, capsys):
    """Remote mode + no API key prints the config-init pointer and exits 1."""
    cfg = _local_cfg(mode="remote", api_key=None)
    monkeypatch.setattr(rtdm_main.config_module, "load_config", lambda: cfg)

    rc = rtdm_main.main(["list", "files"])
    captured = capsys.readouterr()
    assert rc == 1
    assert "remote mode is enabled but api_key is missing" in captured.err


def test_q_flag_routes_to_ask(monkeypatch):
    cfg = _local_cfg(mode="local")
    monkeypatch.setattr(rtdm_main.config_module, "load_config", lambda: cfg)
    with patch("rtdm.main.local_backend.ask", return_value="answer") as mock_ask, \
         patch("rtdm.main.local_backend.query") as mock_query:
        rc = rtdm_main.main(["-q", "how", "does", "find", "work"])
    assert rc == 0
    mock_ask.assert_called_once()
    mock_query.assert_not_called()
    assert mock_ask.call_args.args[0] == "how does find work"


def test_e_flag_routes_to_explain(monkeypatch):
    cfg = _local_cfg(mode="local")
    monkeypatch.setattr(rtdm_main.config_module, "load_config", lambda: cfg)
    with patch("rtdm.main.local_backend.explain", return_value="...") as mock_explain:
        # Note: a real user would quote a command containing dashes
        # ("rtdm -e 'ls -la'") so argparse doesn't treat -la as a flag.
        # We mirror that here.
        rc = rtdm_main.main(["-e", "ls -la"])
    assert rc == 0
    mock_explain.assert_called_once()
    assert mock_explain.call_args.args[0] == "ls -la"


def test_x_with_q_rejected(capsys):
    """-x only makes sense in cmd mode; combining is a hard error."""
    rc = rtdm_main.main(["-x", "-q", "what"])
    assert rc == 1
    err = capsys.readouterr().err
    assert "command mode" in err


def test_no_query_prints_help(capsys):
    """Bare invocation prints help and exits 1, like the original."""
    rc = rtdm_main.main([])
    assert rc == 1
    out = capsys.readouterr().out
    assert "usage:" in out.lower()


def test_env_var_override_works(monkeypatch, tmp_path):
    """RTDM_MODE flips the dispatch path even if config says otherwise.

    We exercise this through load_config rather than patching it, to
    catch a regression where the dispatcher reads from the env directly
    (it shouldn't — the override lives in config.load_config).
    """
    p = tmp_path / "cfg.toml"
    p.write_text('mode = "local"\n[remote]\napi_key = "x"\n')
    monkeypatch.setenv("RTDM_MODE", "remote")

    # Stub default_config_path so load_config reads our temp file.
    monkeypatch.setattr(
        "rtdm.config.default_config_path", lambda: p
    )

    with patch("rtdm.main.remote_backend.query", return_value="cmd") as mock_remote:
        rc = rtdm_main.main(["something"])
    assert rc == 0
    mock_remote.assert_called_once()
