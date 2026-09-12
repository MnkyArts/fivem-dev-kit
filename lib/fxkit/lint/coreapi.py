"""`Core.*` call collection and verification (K013) for fxlint.

Mirrors natives.py: collect the candidate call sites with a regex, ask
`fxref core resolve --json` once per run (one subprocess for the whole batch),
and treat "no index" as "skip the rule", never as "everything is missing".
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fxkit import config

# `Core.Money.add(`, `Core.UI.menu.open(`, and the handle sugar
# `Core.Player(src):getInfo(` (which is really `Core.Player.getInfo`).
# A lower-case namespace is matched too, so a wrong-case call
# (`Core.money.add(...)`) is collected and reported by K013 instead of
# silently looking like nothing at all.
RE_CORE_CALL = re.compile(
    r"(?<![\w.])Core\.(\w+)(?:\.(\w+))?(?:\.(\w+))?\s*\("
)
RE_CORE_HANDLE = re.compile(r"(?<![\w.])Core\.(Player)\s*\([^()]*\)\s*:\s*(\w+)\s*\(")

# Definitions inside the resource being linted, so core's own internal APIs
# (`Core.DB.markDegraded`, assigned as `Core.DB = DB` + `function DB.x()`)
# are never reported as hallucinated.
RE_NS_ALIAS = re.compile(r"(?<![\w.])Core\.([A-Z]\w*)\s*=\s*([A-Za-z_]\w*)\b")
RE_TABLE_FN = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\.(\w+)\s*\(")
RE_TABLE_ASSIGN_FN = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\.(\w+)\s*=\s*function\b")
RE_CORE_DIRECT_FN = re.compile(r"\bfunction\s+Core\.([A-Z]\w*)\.(\w+)\s*\(")


def find_core_calls(clean_lines: list) -> list:
    """[(line, dotted_name), ...] for every `Core.*(` call site."""
    out = []
    seen = set()
    for i, line in enumerate(clean_lines, start=1):
        for m in RE_CORE_HANDLE.finditer(line):
            out.append((i, f"Core.{m.group(1)}.{m.group(2)}"))
        for m in RE_CORE_CALL.finditer(line):
            name = "Core." + ".".join(p for p in m.groups() if p)
            if (i, name) in seen:
                continue
            seen.add((i, name))
            out.append((i, name))
    return out


def collect_defined_core_names(texts: list) -> set:
    """`Core.<Ns>.<fn>` names the linted resource defines itself."""
    blob = "\n".join(texts)
    alias: dict[str, set] = {}
    for m in RE_NS_ALIAS.finditer(blob):
        alias.setdefault(m.group(2), set()).add(m.group(1))
    members: dict[str, set] = {}
    for rx in (RE_TABLE_FN, RE_TABLE_ASSIGN_FN):
        for m in rx.finditer(blob):
            members.setdefault(m.group(1), set()).add(m.group(2))
    defined = {f"Core.{ns}.{fn}" for m in RE_CORE_DIRECT_FN.finditer(blob) for ns, fn in [(m.group(1), m.group(2))]}
    for var, namespaces in alias.items():
        for ns in namespaces:
            for fn in members.get(var, ()):  # Core.DB = DB + function DB.markDegraded()
                defined.add(f"Core.{ns}.{fn}")
    return defined


SKIP_DIRS = frozenset({".git", "node_modules", "ui", "html", "dist", "build", "storybook-static"})
MAX_SCAN_BYTES = 1_000_000


def collect_defined_core_names_in_dir(resource_dir) -> set:
    """Same as collect_defined_core_names(), but over every Lua file of the
    resource rather than only the files being linted.

    Needed because fxlint is often pointed at ONE file (the post-edit hook):
    core's `Core.DB.markDegraded` is called in server/db_pg.lua and defined in
    server/db.lua, and K013 must not report it as hallucinated just because the
    defining file was not part of this run.
    """
    if resource_dir is None:
        return set()
    texts = []
    try:
        for f in sorted(Path(resource_dir).rglob("*.lua")):
            if SKIP_DIRS.intersection(f.relative_to(resource_dir).parts[:-1]):
                continue
            try:
                if f.stat().st_size > MAX_SCAN_BYTES:
                    continue
                texts.append(f.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    except (OSError, ValueError):
        return set()
    return collect_defined_core_names(texts)


# ---------------------------------------------------------------------------
# fxref core resolve
# ---------------------------------------------------------------------------
def fxref_bin_path() -> Path:
    return config.kit_root() / "bin" / "fxref"


def is_available() -> bool:
    """True when a core index can plausibly be queried (fxref + a database)."""
    try:
        if not fxref_bin_path().exists() or not config.db_path().exists():
            return False
    except OSError:
        return False
    return config.core_paths() is not None


def resolve_names(names, timeout: float = 15.0) -> Optional[dict]:
    """Batch-resolve `names` with ONE `fxref core resolve --json` subprocess.

    Returns {input: entry} or None when there is no core index / the call
    failed -- callers must then skip K013 entirely.
    """
    names = sorted(set(names))
    if not names:
        return {}
    if not is_available():
        return None
    bin_path = str(fxref_bin_path())
    cmd = [bin_path, "core", "resolve", "--json", *names]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        try:
            proc = subprocess.run([sys.executable, *cmd], capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
    if proc.returncode != 0 or not proc.stdout:
        return None      # exit 2 == "no core index": skip, never "all missing"
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return {e.get("input"): e for e in data if isinstance(e, dict)}
