"""Tests for the control-character scrubber (audit #1: ANSI escape smuggling).

The helper lives in ``rtdm.backends`` because both backends call it on
every byte that flows from the model into the user's terminal or into
``confirm_and_execute``.  Without this scrub a malicious model could
emit cursor-manipulation escapes that hide the real command behind a
benign-looking line, defeating the y/N prompt.
"""

from __future__ import annotations

import http.client
import io
import json
from unittest.mock import MagicMock

from rtdm.backends import strip_control_chars
from rtdm.backends import local


def test_strip_control_chars_removes_ansi_escapes():
    """ESC (0x1B) and the other C0/C1 control bytes must be removed."""
    poisoned = "ls -la\x1b[1F\x1b[2Krm -rf /"
    cleaned = strip_control_chars(poisoned)
    assert "\x1b" not in cleaned
    # The visible text remains; only the ESC byte itself is stripped.
    assert cleaned == "ls -la[1F[2Krm -rf /"


def test_strip_control_chars_preserves_newlines_and_tabs():
    """\\t (\\x09), \\n (\\x0A), \\r (\\x0D) are explicitly preserved."""
    text = "line1\nline2\twith tab\rcarriage"
    assert strip_control_chars(text) == text


def test_strip_control_chars_preserves_normal_unicode():
    """Printable ASCII and non-ASCII unicode (emoji, accents) are untouched."""
    text = "café — naïve résumé 🚀 ✓"
    assert strip_control_chars(text) == text


def test_strip_control_chars_removes_c1_range():
    """C1 controls (0x80–0x9F) are stripped too — they're rarer but equally dangerous."""
    text = "before\x85\x9bafter"
    assert strip_control_chars(text) == "beforeafter"


def test_local_backend_strips_before_print(capsys):
    """_stream_response must scrub each token before print() and in the return value.

    We simulate Ollama's NDJSON stream with one chunk containing an
    ANSI escape.  Both stdout *and* the returned string must be
    scrub-clean — the returned string is what gets passed to
    ``confirm_and_execute``.
    """
    chunks = [
        {"message": {"content": "ls -la\x1b[1F\x1b[2K"}, "done": False},
        {"message": {"content": "rm -rf /"}, "done": False},
        {"done": True},
    ]
    raw = b"".join(json.dumps(c).encode() + b"\n" for c in chunks)
    fake_resp = MagicMock(spec=http.client.HTTPResponse)
    # Drive readline() off a BytesIO so we get one JSON object per call.
    buf = io.BytesIO(raw)
    fake_resp.readline = buf.readline

    out = local._stream_response(fake_resp)

    captured = capsys.readouterr()
    assert "\x1b" not in captured.out
    assert "\x1b" not in out
    assert out == "ls -la[1F[2Krm -rf /"
