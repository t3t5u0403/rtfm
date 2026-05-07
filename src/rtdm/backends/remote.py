"""Remote backend — talks to the hosted rtdm.sh service.

Three thin wrappers around the corresponding ``/v1/*`` endpoints.
Each takes the user input, the API key, and the endpoint base URL
(usually ``https://rtdm.sh``) and returns the response text on success.

HTTP errors are translated to :class:`RemoteBackendError` with a
user-friendly message; the dispatcher prints those verbatim and exits
1.  Stack traces are reserved for the unexpected.

Streaming is intentionally not implemented in this phase: the hosted
endpoints return full JSON responses and the wait is short enough that
the UX win from streaming doesn't justify a server-side change.
"""

from __future__ import annotations

import httpx


class RemoteBackendError(Exception):
    """User-facing error from the remote backend.

    The string form is what gets printed to stderr; callers should
    not wrap it further.
    """


_TIMEOUT = httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)


def _post(path: str, payload: dict, api_key: str, endpoint: str) -> dict:
    """POST to ``endpoint + path`` with bearer auth; return parsed JSON.

    Maps every failure mode we care about (auth, quota, rate limit,
    backend errors, network) onto :class:`RemoteBackendError` with
    the message the user will see.  Other 4xx/5xx fall back to a
    generic "service error" line; this is intentional — we don't want
    to leak server-side error strings into the terminal verbatim.
    """
    url = endpoint.rstrip("/") + path
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            resp = client.post(url, json=payload, headers=headers)
    except httpx.ConnectError as exc:
        raise RemoteBackendError(
            "Couldn't reach rtdm.sh. Check your internet, or switch to local mode."
        ) from exc
    except httpx.TimeoutException as exc:
        raise RemoteBackendError(
            "rtdm.sh took too long to respond. Try again, or switch to local mode."
        ) from exc

    if resp.status_code == 200:
        return resp.json()

    # Try to parse a structured error body, but never trust it for
    # text we'll show — only known fields are safe to render.
    try:
        body = resp.json()
    except ValueError:
        body = {}

    if resp.status_code == 401:
        raise RemoteBackendError(
            "Invalid or revoked API key. "
            "Edit ~/.config/rtdm/config.toml or run 'rtdm config init'."
        )
    if resp.status_code == 402:
        resets = body.get("resets_at") if isinstance(body, dict) else None
        if isinstance(resets, str) and resets:
            raise RemoteBackendError(
                f"Monthly quota exceeded. Resets at {resets}. "
                "Visit rtdm.sh to manage."
            )
        raise RemoteBackendError(
            "Monthly quota exceeded. Visit rtdm.sh to manage."
        )
    if resp.status_code == 429:
        raise RemoteBackendError(
            "Slow down — too many requests. Try again in a few seconds."
        )
    if resp.status_code == 503:
        raise RemoteBackendError(
            "Service is busy. Try again in a moment."
        )
    if resp.status_code in (502, 504):
        raise RemoteBackendError(
            "Service error. Try again or contact privacy@rtdm.sh."
        )

    raise RemoteBackendError(
        f"Unexpected response from rtdm.sh (HTTP {resp.status_code}). "
        "Try again or contact privacy@rtdm.sh."
    )


def query(prompt: str, api_key: str, endpoint: str) -> str:
    """POST /v1/query and return the ``command`` field from the response."""
    data = _post("/v1/query", {"query": prompt}, api_key, endpoint)
    return _extract(data, "command")


def ask(question: str, api_key: str, endpoint: str) -> str:
    """POST /v1/ask and return the ``answer`` field from the response."""
    data = _post("/v1/ask", {"question": question}, api_key, endpoint)
    return _extract(data, "answer")


def explain(command: str, api_key: str, endpoint: str) -> str:
    """POST /v1/explain and return the ``explanation`` field."""
    data = _post("/v1/explain", {"command": command}, api_key, endpoint)
    return _extract(data, "explanation")


def _extract(data: dict, key: str) -> str:
    """Pull ``key`` out of a 200 response body, defending against shape drift."""
    if not isinstance(data, dict):
        raise RemoteBackendError(
            "Unexpected response shape from rtdm.sh. Try again or contact privacy@rtdm.sh."
        )
    value = data.get(key)
    if not isinstance(value, str):
        raise RemoteBackendError(
            "Unexpected response shape from rtdm.sh. Try again or contact privacy@rtdm.sh."
        )
    return value
