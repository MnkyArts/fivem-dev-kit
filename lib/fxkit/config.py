"""Configuration loading for fivem-dev-kit.

Resolution order for the config file:
  1. $FXKIT_CONFIG (explicit path)
  2. <kit root>/config.json
  3. <kit root>/config.example.json (last resort, paths will be wrong)

`kit_root()` follows symlinks so the CLIs work when the plugin directory is
symlinked into ~/.claude/skills/.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_ROOT = Path(os.path.realpath(__file__)).resolve().parent.parent.parent


def kit_root() -> Path:
    """Absolute path of the fivem-dev-kit directory (symlinks resolved)."""
    return _ROOT


def data_dir() -> Path:
    d = kit_root() / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_path() -> Path:
    return data_dir() / "fxref.sqlite"


def config_path() -> Path:
    env = os.environ.get("FXKIT_CONFIG")
    if env:
        return Path(env).expanduser()
    p = kit_root() / "config.json"
    if p.exists():
        return p
    return kit_root() / "config.example.json"


_cache: dict[str, Any] | None = None


def load() -> dict[str, Any]:
    """Load (and cache) the config as a dict. Raises FileNotFoundError if none exists."""
    global _cache
    if _cache is None:
        with open(config_path(), "r", encoding="utf-8") as fh:
            _cache = json.load(fh)
    return _cache


def get(*keys: str, default: Any = None) -> Any:
    """get('server', 'log_file') -> value or default."""
    node: Any = load()
    for k in keys:
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node


def path(*keys: str) -> Path:
    """Like get() but returns an expanded Path; raises KeyError when missing."""
    v = get(*keys)
    if v is None:
        raise KeyError("config key not set: " + ".".join(keys))
    return Path(str(v)).expanduser()


def core_paths() -> dict[str, Path] | None:
    """Absolute paths of Liam's `core` framework (DESIGN.md section 9.1).

    Returns a dict with the keys `path`, `example`, `types`, `template`, `ui`
    and `check` -- or None when the `core` block is absent from config.json or
    `core.path` does not exist on disk. Every core feature of the kit degrades
    silently to "no core configured" on None, so callers never have to care
    whether the framework is present.

    `example` is None when `core.example` is unset/missing; the other keys are
    always resolved relative to `core.path` (they may point at files that do
    not exist -- callers check what they actually need).
    """
    block = get("core")
    if not isinstance(block, dict):
        return None
    raw_path = block.get("path")
    if not raw_path:
        return None
    root = Path(str(raw_path)).expanduser()
    if not root.is_dir():
        return None

    def _under(key: str, default: str) -> Path:
        return root / str(block.get(key) or default)

    example: Path | None = None
    raw_example = block.get("example")
    if raw_example:
        cand = Path(str(raw_example)).expanduser()
        if cand.is_dir():
            example = cand

    return {
        "path": root,
        "example": example,
        "types": _under("types", "types/core.lua"),
        "template": _under("template", "templates/plugin"),
        "ui": _under("ui_dir", "ui"),
        "check": _under("check_script", "scripts/check.sh"),
    }


def server_paths() -> dict[str, Path]:
    data = path("server", "data_dir")
    return {
        "root": path("server", "root"),
        "data_dir": data,
        "local_resources": data / get("server", "local_resources_dir", default="resources/[local]"),
        "server_cfg": data / get("server", "server_cfg", default="server.cfg"),
        "log_file": path("server", "log_file"),
    }
