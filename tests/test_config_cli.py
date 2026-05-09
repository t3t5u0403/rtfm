"""Tests for ``rtdm config init`` API key validation.

The wizard must refuse to persist a malformed key: the loader will
later reject it on the next CLI invocation, but failing at the
prompt instead of writing-then-rejecting saves the user an extra
round trip and avoids leaving a known-bad credential on disk.
"""

from __future__ import annotations

from unittest.mock import patch

from rtdm import config_cli


def _stub_mode_remote(monkeypatch) -> None:
    """Make _ask_choice return 'remote' without an interactive prompt."""
    monkeypatch.setattr("builtins.input", lambda _prompt="": "remote")


def _point_config_at(tmp_path, monkeypatch):
    """Redirect default_config_path so a failed init can't touch real config."""
    target = tmp_path / "config.toml"
    monkeypatch.setattr(config_cli, "default_config_path", lambda: target)
    return target


def test_config_init_rejects_short_key(tmp_path, monkeypatch, capsys):
    """A key shorter than the canonical 32-char body must be rejected.

    Three attempts, then exit 1.  No config file is written.
    """
    target = _point_config_at(tmp_path, monkeypatch)
    _stub_mode_remote(monkeypatch)

    with patch("getpass.getpass", side_effect=["rtdm_live_abc"] * 3) as mock_pw:
        rc = config_cli.run_init()

    assert rc == 1
    assert mock_pw.call_count == 3
    err = capsys.readouterr().err
    assert "API key looks invalid" in err
    assert not target.exists()


def test_config_init_rejects_non_ascii_key(tmp_path, monkeypatch, capsys):
    """A 32-char key containing non-base64url characters must be rejected.

    Catches paste-from-non-terminal scenarios (e.g. a typographic dash
    sneaks in) that would silently corrupt the credential.
    """
    target = _point_config_at(tmp_path, monkeypatch)
    _stub_mode_remote(monkeypatch)

    bogus = "rtdm_live_" + "ñ" * 32  # right length, wrong alphabet
    with patch("getpass.getpass", side_effect=[bogus] * 3) as mock_pw:
        rc = config_cli.run_init()

    assert rc == 1
    assert mock_pw.call_count == 3
    assert "API key looks invalid" in capsys.readouterr().err
    assert not target.exists()


def test_config_init_rejects_duplicated_key(tmp_path, monkeypatch, capsys):
    """A key pasted twice (over the 32-char body) must be rejected.

    Mirrors the common mistake of double-clicking and pasting the
    full key including the surrounding text.
    """
    target = _point_config_at(tmp_path, monkeypatch)
    _stub_mode_remote(monkeypatch)

    valid = "rtdm_live_" + "x" * 32
    duped = valid + valid  # 84 chars: blows past the {32} bound
    with patch("getpass.getpass", side_effect=[duped] * 3) as mock_pw:
        rc = config_cli.run_init()

    assert rc == 1
    assert mock_pw.call_count == 3
    assert "API key looks invalid" in capsys.readouterr().err
    assert not target.exists()
