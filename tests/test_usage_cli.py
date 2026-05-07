"""Tests for ``rtdm usage``.

Pin: local mode is rejected, the bar reflects used/quota correctly,
and each error path exits 1 with a useful stderr message.  We also
sanity-check the rendering helper directly so we don't have to fake
HTTP for every layout permutation.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from rtdm import usage_cli
from rtdm.config import Config, LocalConfig, RemoteConfig


def _remote_cfg(api_key: str | None = "rtdm_live_test_key") -> Config:
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
    cm.__enter__.return_value.get.return_value = resp
    cm.__exit__.return_value = False
    return patch("rtdm.usage_cli.httpx.Client", return_value=cm)


# ---------------------------------------------------------------------------
# run()
# ---------------------------------------------------------------------------


def test_local_mode_rejected(monkeypatch, capsys):
    monkeypatch.setattr(usage_cli.config_module, "load_config", lambda: _local_cfg())
    rc = usage_cli.run()
    assert rc == 1
    assert "remote mode" in capsys.readouterr().err.lower()


def test_missing_api_key(monkeypatch, capsys):
    monkeypatch.setattr(
        usage_cli.config_module, "load_config", lambda: _remote_cfg(api_key=None)
    )
    rc = usage_cli.run()
    assert rc == 1
    assert "api key" in capsys.readouterr().err.lower()


def test_happy_path(monkeypatch, capsys):
    monkeypatch.setattr(usage_cli.config_module, "load_config", lambda: _remote_cfg())
    resp = _mock_response(
        200, {"used": 123, "quota": 500, "resets_at": "2026-06-01T00:00:00+00:00"}
    )
    with _patch_client(resp):
        rc = usage_cli.run()

    assert rc == 0
    out = capsys.readouterr().out
    assert "123/500" in out
    assert "2026-06-01" in out
    # Some sort of bar with = and -.
    assert "=" in out
    assert "-" in out


def test_auth_header_sent(monkeypatch):
    monkeypatch.setattr(
        usage_cli.config_module, "load_config", lambda: _remote_cfg(api_key="rtdm_live_xyz")
    )
    resp = _mock_response(200, {"used": 0, "quota": 500, "resets_at": "2026-06-01T00:00:00+00:00"})
    with _patch_client(resp) as patcher:
        usage_cli.run()
    get_call = patcher.return_value.__enter__.return_value.get.call_args
    assert get_call.kwargs["headers"]["Authorization"] == "Bearer rtdm_live_xyz"


def test_401_message(monkeypatch, capsys):
    monkeypatch.setattr(usage_cli.config_module, "load_config", lambda: _remote_cfg())
    with _patch_client(_mock_response(401)):
        rc = usage_cli.run()
    assert rc == 1
    assert "invalid or revoked" in capsys.readouterr().err.lower()


def test_unexpected_body(monkeypatch, capsys):
    """200 with garbage body → exit 1, no crash."""
    monkeypatch.setattr(usage_cli.config_module, "load_config", lambda: _remote_cfg())
    resp = _mock_response(200, {"unexpected": "shape"})
    with _patch_client(resp):
        rc = usage_cli.run()
    assert rc == 1
    assert "unexpected response shape" in capsys.readouterr().err.lower()


def test_network_error(monkeypatch, capsys):
    monkeypatch.setattr(usage_cli.config_module, "load_config", lambda: _remote_cfg())
    bad = MagicMock()
    bad.__enter__.return_value.get.side_effect = httpx.ConnectError("down")
    bad.__exit__.return_value = False
    with patch("rtdm.usage_cli.httpx.Client", return_value=bad):
        rc = usage_cli.run()
    assert rc == 1
    assert "internet" in capsys.readouterr().err.lower()


# ---------------------------------------------------------------------------
# _render()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "used,quota,expect_pct",
    [
        (0, 500, "0%"),
        (250, 500, "50%"),
        (500, 500, "100%"),
        (600, 500, "100%"),  # over-quota clamps to 100%
    ],
)
def test_render_pct(used, quota, expect_pct):
    out = usage_cli._render(used, quota, "2026-06-01T00:00:00+00:00")
    assert expect_pct in out


def test_render_singular_remaining():
    """1 remaining → 'request' (singular), not 'requests'."""
    out = usage_cli._render(499, 500, "2026-06-01T00:00:00+00:00")
    assert "1 request remaining" in out


def test_render_zero_quota_no_div_by_zero():
    out = usage_cli._render(7, 0, "—")
    # No exception; output is something coherent.
    assert "used: 7" in out
