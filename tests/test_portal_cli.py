"""Tests for ``rtdm portal``.

The subcommand POSTs to /v1/auth/portal, opens a browser, and prints
the URL.  We pin: the auth header is sent correctly, the URL is
always printed (so headless users can copy it), and each error path
exits 1 with a useful stderr line.

httpx is mocked at the Client level so no socket is opened, and
``webbrowser.open`` is patched so CI doesn't try to launch Firefox.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from rtdm import portal_cli
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
    """Return a patcher that makes httpx.Client(...).post(...) return resp."""
    client_cm = MagicMock()
    client_cm.__enter__.return_value.post.return_value = resp
    client_cm.__exit__.return_value = False
    return patch("rtdm.portal_cli.httpx.Client", return_value=client_cm)


def test_local_mode_rejected(monkeypatch, capsys):
    """Local mode → exit 1, no network call."""
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _local_cfg())
    with patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()
    assert rc == 1
    assert "remote mode" in capsys.readouterr().err
    mock_open.assert_not_called()


def test_missing_api_key(monkeypatch, capsys):
    monkeypatch.setattr(
        portal_cli.config_module, "load_config", lambda: _remote_cfg(api_key=None)
    )
    rc = portal_cli.run()
    assert rc == 1
    assert "API key" in capsys.readouterr().err


def test_happy_path(monkeypatch, capsys):
    """200 + valid body → URL printed, browser opened, exit 0."""
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())

    portal_url = "https://billing.stripe.com/p/sess_abc"
    resp = _mock_response(200, {"portal_url": portal_url})

    with _patch_client(resp), \
         patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()

    assert rc == 0
    out = capsys.readouterr().out
    assert portal_url in out
    mock_open.assert_called_once_with(portal_url, new=2)


def test_auth_header_sent(monkeypatch):
    """Bearer token from config is forwarded as Authorization header."""
    monkeypatch.setattr(
        portal_cli.config_module, "load_config", lambda: _remote_cfg(api_key="rtdm_live_xyz")
    )
    resp = _mock_response(200, {"portal_url": "https://billing.stripe.com/p/x"})

    with _patch_client(resp) as client_patch, \
         patch("rtdm.portal_cli.webbrowser.open"):
        portal_cli.run()

    client_cm = client_patch.return_value
    post_call = client_cm.__enter__.return_value.post.call_args
    headers = post_call.kwargs["headers"]
    assert headers["Authorization"] == "Bearer rtdm_live_xyz"


def test_401_message(monkeypatch, capsys):
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    with _patch_client(_mock_response(401)):
        rc = portal_cli.run()
    assert rc == 1
    assert "invalid or revoked" in capsys.readouterr().err.lower()


def test_409_message(monkeypatch, capsys):
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    with _patch_client(_mock_response(409)):
        rc = portal_cli.run()
    assert rc == 1
    assert "stripe customer" in capsys.readouterr().err.lower()


def test_network_error(monkeypatch, capsys):
    """ConnectError → friendly offline message, no browser launch."""
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    bad_client = MagicMock()
    bad_client.__enter__.return_value.post.side_effect = httpx.ConnectError("down")
    bad_client.__exit__.return_value = False
    with patch("rtdm.portal_cli.httpx.Client", return_value=bad_client), \
         patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()
    assert rc == 1
    assert "internet" in capsys.readouterr().err.lower()
    mock_open.assert_not_called()


def test_non_https_url_rejected(monkeypatch, capsys):
    """A server-returned http:// URL must not be opened (audit #3)."""
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    resp = _mock_response(200, {"portal_url": "http://evil.example/x"})
    with _patch_client(resp), \
         patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()
    assert rc == 1
    assert "unexpected portal host" in capsys.readouterr().err.lower()
    mock_open.assert_not_called()


# ---------------------------------------------------------------------------
# Audit #3: portal-host allow-list
#
# A pre-fix startswith("https://") check would happily open
# ``https://stripe.com.evil.example/`` if a downstream proxy or
# compromised /v1/auth/portal response ever returned one.  The fix pins
# the redirect target to billing.stripe.com via a frozenset allow-list
# and refuses everything else (still printing the URL so the user can
# see what happened).
# ---------------------------------------------------------------------------


def test_portal_opens_billing_stripe_com(monkeypatch, capsys):
    """The exact host billing.stripe.com is the only one we open."""
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    portal_url = "https://billing.stripe.com/p/sess_real"
    resp = _mock_response(200, {"portal_url": portal_url})
    with _patch_client(resp), \
         patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()
    assert rc == 0
    mock_open.assert_called_once_with(portal_url, new=2)


def test_portal_rejects_phishing_subdomain(monkeypatch, capsys):
    """``https://stripe.com.evil.example/`` must not be opened.

    A naive startswith("https://") or endswith("stripe.com") check would
    let this through; the allow-list match on the parsed hostname
    blocks it.
    """
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    phishing = "https://billing.stripe.com.evil.example/p/sess_phish"
    resp = _mock_response(200, {"portal_url": phishing})
    with _patch_client(resp), \
         patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()
    assert rc == 1
    out = capsys.readouterr()
    # URL is printed for transparency, but the browser is not opened.
    assert phishing in out.out
    assert "unexpected portal host" in out.err.lower()
    mock_open.assert_not_called()


def test_portal_rejects_user_info_url(monkeypatch, capsys):
    """A URL with embedded user-info (``https://x@billing.stripe.com/``)
    is refused even though the trailing host is on the allow-list.

    Embedded credentials are a classic phishing-display trick (the
    ``x@`` part is invisible in some renderers and the user thinks the
    real host is the prefix).
    """
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    sneaky = "https://attacker.example@billing.stripe.com/p/x"
    resp = _mock_response(200, {"portal_url": sneaky})
    with _patch_client(resp), \
         patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()
    assert rc == 1
    mock_open.assert_not_called()


def test_portal_rejects_http_scheme(monkeypatch, capsys):
    """Even ``http://billing.stripe.com/`` is refused — must be https."""
    monkeypatch.setattr(portal_cli.config_module, "load_config", lambda: _remote_cfg())
    resp = _mock_response(200, {"portal_url": "http://billing.stripe.com/p/x"})
    with _patch_client(resp), \
         patch("rtdm.portal_cli.webbrowser.open") as mock_open:
        rc = portal_cli.run()
    assert rc == 1
    mock_open.assert_not_called()
