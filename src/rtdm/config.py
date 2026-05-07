"""Configuration loader for the rtdm CLI.

Layers, in increasing order of precedence:

1. Hard-coded defaults (mode = "local", local-Ollama URL/model,
   ``https://rtdm.sh`` for the remote endpoint).
2. ``~/.config/rtdm/config.toml`` if it exists.
3. ``RTDM_MODE`` environment variable, which overrides only the mode
   (not the credentials in ``[remote]``) — power-user escape hatch.

Everything is loaded into a small, immutable :class:`Config` value
object that the dispatcher and backends pass around.  We intentionally
keep this module dependency-free so importing it is cheap; the CLI
runs once per invocation and we don't want startup overhead.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

DEFAULT_OLLAMA_URL = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b-instruct-q4_K_M"
DEFAULT_REMOTE_ENDPOINT = "https://rtdm.sh"

VALID_MODES = ("local", "remote")


def default_config_path() -> Path:
    """Return the platform-conventional config location.

    Honours ``XDG_CONFIG_HOME`` if set; otherwise ``~/.config``.  We do
    not search system-wide locations — rtdm is a per-user tool.
    """
    base = os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / "rtdm" / "config.toml"
    return Path.home() / ".config" / "rtdm" / "config.toml"


@dataclass(frozen=True)
class RemoteConfig:
    api_key: str | None = None
    endpoint: str = DEFAULT_REMOTE_ENDPOINT


@dataclass(frozen=True)
class LocalConfig:
    ollama_url: str = DEFAULT_OLLAMA_URL
    model: str = DEFAULT_OLLAMA_MODEL


@dataclass(frozen=True)
class Config:
    mode: str = "local"
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    local: LocalConfig = field(default_factory=LocalConfig)
    source: Path | None = None  # None when loaded from defaults only


def _coerce_mode(value: object | None) -> str:
    """Validate the mode string; fall back to ``"local"`` on garbage.

    We deliberately don't raise here — a typo in the config shouldn't
    make ``rtdm config show`` blow up before the user can fix it.
    """
    if isinstance(value, str) and value in VALID_MODES:
        return value
    return "local"


def load_config(path: Path | None = None) -> Config:
    """Load the user's config, applying defaults for everything missing.

    If ``path`` is omitted, :func:`default_config_path` is used.
    A missing file is treated as "all defaults"; this is the
    out-of-the-box behaviour for self-hosters who run ``ollama serve``
    locally and don't care about the hosted service.

    The ``RTDM_MODE`` environment variable, if set to ``local`` or
    ``remote``, takes precedence over whatever is on disk.  An
    unrecognised value is silently ignored.
    """
    cfg_path = path if path is not None else default_config_path()

    raw: dict[str, object] = {}
    source: Path | None = None
    if cfg_path.exists():
        # tomllib reads bytes; reading "rb" keeps us encoding-agnostic.
        with cfg_path.open("rb") as f:
            raw = tomllib.load(f)
        source = cfg_path

    mode = _coerce_mode(raw.get("mode"))

    remote_section = raw.get("remote") or {}
    if not isinstance(remote_section, dict):
        remote_section = {}
    api_key = remote_section.get("api_key")
    endpoint = remote_section.get("endpoint") or DEFAULT_REMOTE_ENDPOINT
    remote = RemoteConfig(
        api_key=api_key if isinstance(api_key, str) and api_key else None,
        endpoint=endpoint if isinstance(endpoint, str) else DEFAULT_REMOTE_ENDPOINT,
    )

    local_section = raw.get("local") or {}
    if not isinstance(local_section, dict):
        local_section = {}
    ollama_url = local_section.get("ollama_url") or DEFAULT_OLLAMA_URL
    model = local_section.get("model") or DEFAULT_OLLAMA_MODEL
    local = LocalConfig(
        ollama_url=ollama_url if isinstance(ollama_url, str) else DEFAULT_OLLAMA_URL,
        model=model if isinstance(model, str) else DEFAULT_OLLAMA_MODEL,
    )

    # Env override, last so it wins.  Anything other than "local" /
    # "remote" is ignored rather than rejected — keeps shells with
    # stale exports quiet.
    env_mode = os.environ.get("RTDM_MODE")
    if env_mode in VALID_MODES:
        mode = env_mode

    return Config(mode=mode, remote=remote, local=local, source=source)


def update_api_key(new_key: str, path: Path | None = None) -> Path:
    """Atomically rewrite the config file with a new ``[remote] api_key``.

    Used by ``rtdm rotate`` to persist the post-rotation key.  We can't
    afford a half-written config here — losing the file mid-write
    would leave the user without their *new* key (the old one is
    already revoked server-side).

    Strategy: write to a sibling temp file in the same directory,
    fsync, rename over the destination, then chmod 600.  os.replace is
    atomic on POSIX and on Windows.

    All other fields are preserved by re-reading the on-disk values
    (or falling back to defaults if the file doesn't exist yet) and
    re-rendering the document.  This avoids depending on a TOML writer.

    Returns the absolute path that was written, for the caller to
    surface in a success message.
    """
    cfg_path = path if path is not None else default_config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)

    existing = load_config(cfg_path)
    body = _render_remote_focused_toml(
        mode=existing.mode if existing.source is not None else "remote",
        api_key=new_key,
        endpoint=existing.remote.endpoint,
        ollama_url=existing.local.ollama_url,
        model=existing.local.model,
    )

    tmp = cfg_path.with_suffix(cfg_path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        f.write(body)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, cfg_path)
    try:
        cfg_path.chmod(0o600)
    except OSError:
        # Non-POSIX FS (e.g. some Windows mounts); best-effort.
        pass
    return cfg_path


def _toml_escape(value: str) -> str:
    """Quote a string for emission as a TOML basic string literal."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _render_remote_focused_toml(
    *,
    mode: str,
    api_key: str,
    endpoint: str,
    ollama_url: str,
    model: str,
) -> str:
    """Render a config TOML preserving everything except api_key.

    Mirrors the layout that ``rtdm config init`` produces, so the file
    keeps looking the same after a rotation.  We accept the duplication
    with config_cli._render_toml because the bodies are tiny and a
    shared helper would couple two modules that don't otherwise need
    to know about each other.
    """
    s = _toml_escape
    lines: Iterable[str] = (
        "# rtdm config — written by `rtdm rotate` (api_key updated).",
        "# Edit by hand if you prefer; see `rtdm config show` for the effective values.",
        "",
        f"mode = {s(mode)}",
        "",
        "[remote]",
        f"api_key = {s(api_key)}",
        f"endpoint = {s(endpoint)}",
        "",
        "[local]",
        f"ollama_url = {s(ollama_url)}",
        f"model = {s(model)}",
        "",
    )
    return "\n".join(lines)
