#!/usr/bin/env python3
"""Test runner for fivem-dev-kit.

Discovers tests/test_*.py, runs each as a subprocess with the current
interpreter (streaming its output live), and prints a final PASS/FAIL table.

Also runs a built-in **hook self-test** against
hooks-handlers/post-edit-lint.py -- not a test_*.py file itself, since it
exercises the hook handler directly with fake PostToolUse stdin payloads and
asserts the JSON shape it must always emit (DESIGN.md section 7,
docs/claude-code-plugin-reference.md's hooks section).

Usage: python3 tests/run.py
Exit code: 1 if anything failed, 0 otherwise.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS_DIR = Path(__file__).resolve().parent
HOOK = ROOT / "hooks-handlers" / "post-edit-lint.py"
FIXTURES = TESTS_DIR / "fixtures"


def run_test_file(path: Path) -> tuple[bool, float, str]:
    print(f"\n=== {path.name} ===")
    t0 = time.perf_counter()
    proc = subprocess.run([sys.executable, str(path)], cwd=str(ROOT))
    elapsed = time.perf_counter() - t0
    return proc.returncode == 0, elapsed, f"exit {proc.returncode}"


def _hook_payload(file_path: Path) -> str:
    return json.dumps({
        "session_id": "fxkit-test",
        "transcript_path": "/dev/null",
        "cwd": str(ROOT),
        "permission_mode": "default",
        "hook_event_name": "PostToolUse",
        "tool_name": "Edit",
        "tool_input": {"file_path": str(file_path)},
        "tool_response": {},
        "tool_use_id": "fxkit-test",
    })


def _run_hook(file_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=_hook_payload(file_path),
        capture_output=True,
        text=True,
        timeout=30,
    )


def run_hook_self_test() -> tuple[bool, float, str]:
    """Call hooks-handlers/post-edit-lint.py directly (bypassing the actual
    hook dispatch machinery -- there is none to bypass in a test run) with a
    fake PostToolUse stdin payload, and assert its output JSON shape:
      - a file with real fxlint errors/warnings -> {"hookSpecificOutput":
        {"hookEventName": "PostToolUse", "additionalContext": "fxlint: ..."}}
      - a clean file, or one the hook should ignore entirely -> {}
    """
    print("\n=== hook self-test (post-edit-lint.py) ===")
    t0 = time.perf_counter()
    problems: list[str] = []

    if not HOOK.exists():
        return False, time.perf_counter() - t0, f"missing {HOOK}"

    # 1. A deliberately bad file under tests/fixtures/ -- must report findings.
    #    (tests/fixtures/ is carved out of the "never lint inside $KIT" rule
    #    specifically so this fixture can be linted for real.)
    bad_file = FIXTURES / "bad-resource" / "client" / "main.lua"
    proc = _run_hook(bad_file)
    print(proc.stdout.strip() or "(empty stdout)")
    if proc.returncode != 0:
        problems.append(f"bad-resource: exited {proc.returncode}: {proc.stderr.strip()}")
    else:
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            problems.append(f"bad-resource: stdout not JSON: {exc}")
            data = {}
        out = data.get("hookSpecificOutput", {})
        if out.get("hookEventName") != "PostToolUse":
            problems.append("bad-resource: hookSpecificOutput.hookEventName missing/wrong")
        ctx = out.get("additionalContext", "")
        if "fxlint:" not in ctx or "error(s)" not in ctx:
            problems.append("bad-resource: additionalContext missing the expected 'fxlint: N error(s)...' summary")

    # 2. A clean-ish file (only info-level findings) -- must be exactly {}.
    good_file = FIXTURES / "good-resource" / "client" / "main.lua"
    proc = _run_hook(good_file)
    if proc.returncode != 0:
        problems.append(f"good-resource: exited {proc.returncode}: {proc.stderr.strip()}")
    else:
        if proc.stdout.strip() != "{}":
            problems.append(f"good-resource: expected {{}}, got {proc.stdout.strip()!r}")

    # 3. A non-script file with no fxmanifest.lua nearby -- must be {} too
    #    (covers both the extension gate and the "no resource found" gate).
    unrelated = ROOT / "README.md"
    proc = _run_hook(unrelated)
    if proc.returncode != 0 or proc.stdout.strip() != "{}":
        problems.append(f"unrelated file: expected {{}}, got exit={proc.returncode} {proc.stdout.strip()!r}")

    # 4. Garbage stdin -- must never raise, must still exit 0 with {}.
    proc = subprocess.run(
        [sys.executable, str(HOOK)], input="not json {{{",
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0 or proc.stdout.strip() != "{}":
        problems.append(f"garbage stdin: expected exit 0 + {{}}, got exit={proc.returncode} {proc.stdout.strip()!r}")

    elapsed = time.perf_counter() - t0
    if problems:
        return False, elapsed, "; ".join(problems)
    return True, elapsed, "bad-resource -> additionalContext, good-resource/unrelated/garbage -> {}"


def main() -> int:
    results: list[tuple[str, bool, float, str]] = []

    test_files = sorted(TESTS_DIR.glob("test_*.py"))
    for path in test_files:
        ok, elapsed, detail = run_test_file(path)
        results.append((path.name, ok, elapsed, detail))

    ok, elapsed, detail = run_hook_self_test()
    results.append(("hook self-test", ok, elapsed, detail))

    print("\n" + "=" * 72)
    print(f"{'NAME':32} {'RESULT':8} {'TIME':>8}")
    print("-" * 72)
    any_failed = False
    for name, ok, elapsed, detail in results:
        status = "PASS" if ok else "FAIL"
        any_failed = any_failed or not ok
        print(f"{name:32} {status:8} {elapsed:7.2f}s")
        if not ok:
            print(f"    {detail}")
    print("=" * 72)

    if not test_files:
        print("warning: no tests/test_*.py files found", file=sys.stderr)

    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
