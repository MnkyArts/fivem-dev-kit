#!/usr/bin/env python3
"""PostToolUse hook handler: fxlint a FiveM script file right after the agent
writes or edits it, and feed findings back as additionalContext.

Wired up by hooks/hooks.json on Write|Edit|MultiEdit (Claude Code) and by
codex/hooks.json on apply_patch|Edit|Write (Codex CLI). PostToolUse hooks
cannot block a tool call -- this only ever adds context, or stays silent.
See docs/claude-code-plugin-reference.md's hooks section and DESIGN.md
section 7.

Contract: read the PostToolUse JSON payload on stdin, print exactly one
JSON object on stdout, and ALWAYS exit 0. Never raise -- any unexpected
failure degrades to printing "{}" so a bug in this hook can never break the
calling session (this plugin is loaded in every project, not just FiveM
ones, so it must fail silently and cheaply everywhere else).
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
LINT_EXTENSIONS = {".lua", ".js", ".ts"}
MAX_REPORTED_LINES = 12
MAX_LINTED_FILES = 8
FXLINT_TIMEOUT_SECONDS = 10
# Codex reports file edits as tool_name "apply_patch" with the patch text in
# tool_input; the same markers the OpenCode adapter parses.
_PATCH_FILE_RE = re.compile(r"^\*\*\* (?:Add|Update) File: (.+)$", re.MULTILINE)


def _load_config() -> dict:
    """Best-effort config.json, falling back to config.example.json, then
    {} -- a missing/broken config must never stop the hook from running."""
    for name in ("config.json", "config.example.json"):
        candidate = KIT_ROOT / name
        try:
            if candidate.exists():
                with open(candidate, "r", encoding="utf-8") as fh:
                    return json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
    return {}


KIT_TESTS_DIR = KIT_ROOT / "tests"


def _source_repo_roots() -> list[Path]:
    """The raw FiveM/nativedb/docs source checkouts named in config.json --
    huge trees that are never FiveM resources themselves."""
    roots = []
    sources = _load_config().get("sources") or {}
    for key in ("nativedb", "fivem", "fivem_docs"):
        value = sources.get(key)
        if value:
            roots.append(Path(str(value)).expanduser())
    resolved = []
    for root in roots:
        try:
            resolved.append(root.resolve())
        except OSError:
            pass
    return resolved


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _is_excluded(file_path: Path) -> bool:
    """True for anything that must never be linted: the rest of the kit
    itself (its own skills/patterns/templates contain .lua files, including
    literal fxmanifest.lua *templates*, that are not real resources) and the
    raw FiveM source checkouts -- EXCEPT `tests/`, whose fixtures/ directory
    holds deliberately-fake resources that the test suite (and this hook's
    own self-test in tests/run.py) needs to actually lint on purpose."""
    if _is_under(file_path, KIT_ROOT) and not _is_under(file_path, KIT_TESTS_DIR):
        return True
    return any(_is_under(file_path, root) for root in _source_repo_roots())


def _find_resource_dir(file_path: Path) -> Path | None:
    """The file's own directory, or up to 3 parent directories above it,
    whichever first contains an fxmanifest.lua."""
    candidates = [file_path.parent, *list(file_path.parent.parents)[:3]]
    for directory in candidates:
        if (directory / "fxmanifest.lua").is_file():
            return directory
    return None


def _emit(obj: dict) -> None:
    print(json.dumps(obj))


def _candidate_paths(payload: dict) -> list[str]:
    """File paths from Claude-style (file_path) and Codex-style hook input.

    Claude sends {"tool_input": {"file_path": ...}} for Write/Edit. Codex
    sends tool_name "apply_patch" with the patch text inside tool_input
    (key varies: patch/command/edits), so file paths are parsed out of the
    `*** Add/Update File:` markers as well.
    """
    tool_input = payload.get("tool_input") or {}
    candidates: list[str] = []
    if isinstance(tool_input, dict):
        for key in ("file_path", "filePath", "path", "filename"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())
        for key in ("patch", "command", "edits", "diff"):
            value = tool_input.get(key)
            if isinstance(value, str):
                candidates.extend(m.strip() for m in _PATCH_FILE_RE.findall(value))
    seen: set[str] = set()
    ordered = [c for c in candidates if not (c in seen or seen.add(c))]
    return ordered[:MAX_LINTED_FILES]


def _lint_file(raw_path: str, cwd: str) -> str:
    """fxlint one edited file; return the additionalContext message or ""."""
    file_path = Path(raw_path)
    if not file_path.is_absolute():
        file_path = Path(cwd or ".") / file_path
    file_path = file_path.resolve()

    if file_path.suffix not in LINT_EXTENSIONS:
        return ""

    if _is_excluded(file_path):
        return ""

    resource_dir = _find_resource_dir(file_path)
    if resource_dir is None:
        return ""

    fxlint = KIT_ROOT / "bin" / "fxlint"
    proc = subprocess.run(
        [str(fxlint), "--json", str(file_path)],
        capture_output=True,
        text=True,
        timeout=FXLINT_TIMEOUT_SECONDS,
    )
    report = json.loads(proc.stdout)

    rel_key = str(file_path.relative_to(resource_dir)).replace("\\", "/")
    findings = report.get("files", {}).get(rel_key, [])
    errors = sum(1 for f in findings if f.get("level") == "error")
    warns = sum(1 for f in findings if f.get("level") == "warn")

    if errors == 0 and warns == 0:
        return ""

    lines = [
        f"{f.get('line')}: {f.get('rule')} {f.get('msg')}"
        for f in findings[:MAX_REPORTED_LINES]
    ]
    return (
        f"fxlint: {errors} error(s), {warns} warning(s) in {rel_key}:\n"
        + "\n".join(lines)
        + f"\nRun `fxlint {resource_dir}` for details."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        cwd = payload.get("cwd") or "."
        messages = [
            message
            for raw in _candidate_paths(payload)
            if (message := _lint_file(raw, cwd))
        ]
        if not messages:
            _emit({})
            return 0
        _emit({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": "\n\n".join(messages),
            }
        })
        return 0
    except Exception:
        _emit({})
        return 0


if __name__ == "__main__":
    sys.exit(main())
