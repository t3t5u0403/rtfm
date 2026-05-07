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
