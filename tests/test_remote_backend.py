"""Tests for the remote backend.

We mock httpx.Client at the module level so no network call ever
escapes the test harness.  The mocked request object captures the URL,
headers, and body so we can assert auth and routing in one place.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from rtdm.backends import remote


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_client(status_code: int, body: dict | None = None):
    """Build a context-manager mock returning a single canned response."""
    response = MagicMock(spec=httpx.Response)
    response.status_code = status_code
    response.json.return_value = body if body is not None else {}

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.post = MagicMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


def test_query_calls_correct_endpoint():
    """remote.query hits POST <endpoint>/v1/query."""
    client = _mock_client(200, {"command": "ls -la", "model": "m", "duration_ms": 1})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        out = remote.query("list files", "rtdm_live_x", "https://rtdm.sh")

    assert out == "ls -la"
    args, kwargs = client.post.call_args
    assert args[0] == "https://rtdm.sh/v1/query"
    assert kwargs["json"] == {"query": "list files"}


def test_ask_calls_correct_endpoint():
    client = _mock_client(200, {"answer": "pipes...", "model": "m", "duration_ms": 1})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        out = remote.ask("how do pipes work", "k", "https://rtdm.sh")
    args, _ = client.post.call_args
    assert args[0].endswith("/v1/ask")
    assert out == "pipes..."


def test_explain_calls_correct_endpoint():
    client = _mock_client(
        200, {"explanation": "lists files...", "model": "m", "duration_ms": 1}
    )
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        out = remote.explain("ls -la", "k", "https://rtdm.sh")
    args, _ = client.post.call_args
    assert args[0].endswith("/v1/explain")
    assert out == "lists files..."


def test_remote_includes_auth_header():
    """Bearer auth header travels with every request."""
    client = _mock_client(200, {"command": "x", "model": "m", "duration_ms": 1})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        remote.query("q", "rtdm_live_secret", "https://rtdm.sh")

    _, kwargs = client.post.call_args
    assert kwargs["headers"]["Authorization"] == "Bearer rtdm_live_secret"


def test_endpoint_trailing_slash_handled():
    """Trailing slashes on the endpoint don't double-up before /v1/*."""
    client = _mock_client(200, {"command": "x", "model": "m", "duration_ms": 1})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        remote.query("q", "k", "https://rtdm.sh/")
    args, _ = client.post.call_args
    assert args[0] == "https://rtdm.sh/v1/query"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


def test_401_returns_friendly_message():
    """A 401 raises with the config-pointer message, not a raw stack."""
    client = _mock_client(401, {"detail": "invalid api key"})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        with pytest.raises(remote.RemoteBackendError) as excinfo:
            remote.query("q", "bad", "https://rtdm.sh")
    msg = str(excinfo.value)
    assert "Invalid or revoked API key" in msg
    assert "rtdm config init" in msg


def test_402_includes_reset_date():
    """402 surfaces the resets_at date so the user knows when to retry."""
    client = _mock_client(
        402,
        {
            "error": "monthly quota exceeded",
            "quota": 500,
            "used": 500,
            "resets_at": "2026-06-01",
        },
    )
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        with pytest.raises(remote.RemoteBackendError) as excinfo:
            remote.query("q", "k", "https://rtdm.sh")
    msg = str(excinfo.value)
    assert "quota exceeded" in msg.lower()
    assert "2026-06-01" in msg


def test_429_returns_rate_limit_message():
    client = _mock_client(429, {"error": "rate limit exceeded", "retry_after": 5})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        with pytest.raises(remote.RemoteBackendError) as excinfo:
            remote.query("q", "k", "https://rtdm.sh")
    assert "Slow down" in str(excinfo.value)


def test_connection_error_falls_back_gracefully():
    """A network failure becomes a friendly switch-to-local hint."""

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, *args, **kwargs):
            raise httpx.ConnectError("network down")

    with patch("rtdm.backends.remote.httpx.Client", return_value=FakeClient()):
        with pytest.raises(remote.RemoteBackendError) as excinfo:
            remote.query("q", "k", "https://rtdm.sh")
    msg = str(excinfo.value)
    assert "Couldn't reach rtdm.sh" in msg
    assert "local mode" in msg


def test_malformed_response_body_raises():
    """A 200 with the wrong shape doesn't return None; it raises."""
    client = _mock_client(200, {"unexpected": "shape"})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        with pytest.raises(remote.RemoteBackendError):
            remote.query("q", "k", "https://rtdm.sh")


# ---------------------------------------------------------------------------
# Control-character stripping (audit #1: ANSI escape smuggling)
# ---------------------------------------------------------------------------


def test_remote_backend_strips_before_return():
    """A model response containing ANSI escapes must be scrubbed in _extract.

    A compromised upstream model could emit ESC sequences (e.g. cursor
    up + line erase) that overwrite the y/N confirmation prompt or the
    command shown to the user. The remote backend must strip these
    before returning.
    """
    poisoned = "ls -la\x1b[1F\x1b[2Krm -rf /"
    client = _mock_client(200, {"command": poisoned, "model": "m", "duration_ms": 1})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        out = remote.query("list files", "k", "https://rtdm.sh")
    assert "\x1b" not in out
    assert out == "ls -la[1F[2Krm -rf /"


def test_remote_backend_preserves_newlines_and_tabs():
    """Stripping must not eat \\t / \\n; commands and explanations need them."""
    body = "step 1\nstep 2\twith tab"
    client = _mock_client(200, {"answer": body, "model": "m", "duration_ms": 1})
    with patch("rtdm.backends.remote.httpx.Client", return_value=client):
        out = remote.ask("how", "k", "https://rtdm.sh")
    assert out == body
