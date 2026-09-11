#!/usr/bin/env python3
"""PostToolUse hook handler: fxlint a FiveM script file right after Claude
writes or edits it, and feed findings back as additionalContext.

Wired up by hooks/hooks.json on Write|Edit|MultiEdit. PostToolUse hooks
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
import subprocess
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
LINT_EXTENSIONS = {".lua", ".js", ".ts"}
MAX_REPORTED_LINES = 12
FXLINT_TIMEOUT_SECONDS = 10


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


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        tool_input = payload.get("tool_input") or {}
        raw_path = tool_input.get("file_path")
        if not raw_path:
            _emit({})
            return 0

        file_path = Path(raw_path)
        if not file_path.is_absolute():
            file_path = Path(payload.get("cwd") or ".") / file_path
        file_path = file_path.resolve()

        if file_path.suffix not in LINT_EXTENSIONS:
            _emit({})
            return 0

        if _is_excluded(file_path):
            _emit({})
            return 0

        resource_dir = _find_resource_dir(file_path)
        if resource_dir is None:
            _emit({})
            return 0

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
            _emit({})
            return 0

        lines = [
            f"{f.get('line')}: {f.get('rule')} {f.get('msg')}"
            for f in findings[:MAX_REPORTED_LINES]
        ]
        message = (
            f"fxlint: {errors} error(s), {warns} warning(s) in {rel_key}:\n"
            + "\n".join(lines)
            + f"\nRun `fxlint {resource_dir}` for details."
        )
        _emit({
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": message,
            }
        })
        return 0
    except Exception:
        _emit({})
        return 0


if __name__ == "__main__":
    sys.exit(main())
