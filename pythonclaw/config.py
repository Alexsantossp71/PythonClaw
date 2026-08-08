"""
Centralised configuration for PythonClaw.

All runtime data lives under ``~/.pythonclaw/`` (the *home* directory):

    ~/.pythonclaw/
      pythonclaw.json          ← config file
      context/                 ← sessions, logs, memory, skills, …
      daemon.log               ← daemon output
      pythonclaw.pid           ← daemon PID

Load order (later sources override earlier ones):
  1. ~/.pythonclaw/pythonclaw.json
  2. Environment variables (highest priority)
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

PYTHONCLAW_HOME = Path(os.environ.get("PYTHONCLAW_HOME", Path.home() / ".pythonclaw"))

_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")

_config: dict | None = None
_config_path: Path | None = None


def home() -> Path:
    """Return the PythonClaw home directory (``~/.pythonclaw`` by default)."""
    return PYTHONCLAW_HOME


def _strip_json5(text: str) -> str:
    """Strip // comments and trailing commas so standard json.loads works.

    String literals are never modified — both // sequences and ",}"/",]"
    inside quoted values are preserved (the trailing-comma cleanup runs
    only on the structural text between strings).
    """
    segments: list[tuple[bool, str]] = []  # (is_string_literal, chunk)
    buf: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            # Consume the entire string literal (including escaped chars)
            j = i + 1
            while j < n:
                if text[j] == '\\':
                    j += 2
                elif text[j] == '"':
                    j += 1
                    break
                else:
                    j += 1
            if buf:
                segments.append((False, "".join(buf)))
                buf = []
            segments.append((True, text[i:j]))
            i = j
        elif ch == '/' and i + 1 < n and text[i + 1] == '/':
            # Line comment — skip until end of line
            while i < n and text[i] != '\n':
                i += 1
        else:
            buf.append(ch)
            i += 1
    if buf:
        segments.append((False, "".join(buf)))

    return "".join(
        chunk if is_string else _TRAILING_COMMA_RE.sub(r"\1", chunk)
        for is_string, chunk in segments
    )


def _find_config_file() -> Path | None:
    candidates = [
        PYTHONCLAW_HOME / "pythonclaw.json",
        Path.cwd() / "pythonclaw.json",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def _deep_get(data: dict, *keys: str, default: Any = None) -> Any:
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return current


def load(path: str | Path | None = None, *, force: bool = False) -> dict:
    """Load and cache configuration.  Safe to call multiple times.

    Parameters
    ----------
    path   : explicit path to a JSON config file (overrides auto-discovery)
    force  : if True, reload even if already cached
    """
    global _config, _config_path

    if _config is not None and not force:
        return _config

    config_path = Path(path) if path else _find_config_file()
    _config_path = config_path
    raw: dict = {}

    if config_path and config_path.is_file():
        text = config_path.read_text(encoding="utf-8")
        text = _strip_json5(text)
        raw = json.loads(text)

    _config = raw
    return _config


def get(*keys: str, env: str | None = None, default: Any = None) -> Any:
    """Get a config value.  Env var takes priority over JSON.

    Examples
    --------
    config.get("llm", "provider", env="LLM_PROVIDER", default="deepseek")
    config.get("channels", "telegram", "token", env="TELEGRAM_BOT_TOKEN")
    """
    if _config is None:
        load()

    if env:
        env_val = os.environ.get(env)
        if env_val is not None:
            return env_val

    val = _deep_get(_config, *keys, default=default)
    return val


def get_int(*keys: str, env: str | None = None, default: int = 0) -> int:
    """Get an integer config value; malformed values fall back to *default*."""
    val = get(*keys, env=env, default=default)
    if val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        logging.getLogger(__name__).warning(
            "Config value %s=%r is not an integer — using default %r",
            ".".join(keys), val, default,
        )
        return default


def get_str(*keys: str, env: str | None = None, default: str = "") -> str:
    """Get a string config value."""
    val = get(*keys, env=env, default=default)
    return str(val) if val is not None else default


def get_list(*keys: str, env: str | None = None, default: list | None = None) -> list:
    """Get a list value.  Env var is parsed as comma-separated."""
    if _config is None:
        load()

    if env:
        env_val = os.environ.get(env)
        if env_val is not None and env_val.strip():
            return [v.strip() for v in env_val.split(",") if v.strip()]

    val = _deep_get(_config, *keys)
    if isinstance(val, list):
        return val
    return default or []


def get_int_list(*keys: str, env: str | None = None) -> list[int]:
    """Get a list of integers.  Env var is parsed as comma-separated ints.

    Non-numeric entries are skipped with a warning instead of crashing
    channel startup (e.g. a username typed where a numeric ID belongs).
    """
    raw = get_list(*keys, env=env)
    out: list[int] = []
    for v in raw or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            logging.getLogger(__name__).warning(
                "Ignoring non-integer entry %r in config list %s", v, ".".join(keys),
            )
    return out


def config_path() -> Path | None:
    """Return the path to the loaded config file, or None."""
    return _config_path


def as_dict() -> dict:
    """Return a copy of the full loaded config dict."""
    if _config is None:
        load()
    return dict(_config)


def get_bool(*keys: str, env: str | None = None, default: bool = False) -> bool:
    """Get a boolean config value."""
    val = get(*keys, env=env, default=default)
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.lower() in ("1", "true", "yes")
    return bool(val) if val is not None else default


def per_group_isolation() -> bool:
    """Return True if per-group context isolation is enabled."""
    return get_bool("isolation", "perGroup", default=False)


def group_context_dir(session_id: str) -> Path:
    """Return the per-group context directory for *session_id*.

    Maps ``session_id`` (e.g. ``telegram:123``) to a safe filesystem path
    under ``~/.pythonclaw/context/groups/<safe_id>/``.
    """
    safe = re.sub(r"[^\w\-]", "_", session_id)
    return PYTHONCLAW_HOME / "context" / "groups" / safe


def files_dir() -> Path:
    """Return the shared files directory (``~/.pythonclaw/context/files/``)."""
    d = PYTHONCLAW_HOME / "context" / "files"
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear_files() -> int:
    """Delete all files in the shared files directory. Returns count removed."""
    d = files_dir()
    count = 0
    for entry in d.iterdir():
        try:
            if entry.is_file():
                entry.unlink()
                count += 1
            elif entry.is_dir():
                import shutil
                shutil.rmtree(entry)
                count += 1
        except OSError:
            pass
    return count


def reset() -> None:
    """Clear the cached config (mainly for testing)."""
    global _config, _config_path
    _config = None
    _config_path = None
