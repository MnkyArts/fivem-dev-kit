#!/usr/bin/env python3
"""Smoke tests for the Codex adapter. Run with python3 tests/test_codex.py."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "codex" / "install.py"
HOOK = ROOT / "hooks-handlers" / "post-edit-lint.py"
BAD_FILE = ROOT / "tests" / "fixtures" / "bad-resource" / "client" / "main.lua"
GOOD_FILE = ROOT / "tests" / "fixtures" / "good-resource" / "client" / "main.lua"

EXPECTED_AGENTS = {
    "fivem": ("gpt-5.6-terra", "high", "workspace-write"),
    "fivem-core": ("gpt-5.6-terra", "high", "workspace-write"),
    "fivem-native-scout": ("gpt-5.6-luna", "medium", "read-only"),
    "fivem-implementer": ("gpt-5.6-terra", "high", "workspace-write"),
    "fivem-reviewer": ("gpt-5.6-terra", "high", "read-only"),
    "fivem-deep-reviewer": ("gpt-6-astra", "high", "read-only"),
}
EXPECTED_SKILLS = (
    "fivem-build", "fivem-review", "fivem-reference", "fivem-scripting",
    "fivem-server", "fivem-client", "fivem-core",
)


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS {message}")


def base_command(tmp: str) -> list[str]:
    return [sys.executable, str(INSTALL), "--codex-home", f"{tmp}/codex",
            "--skills-dir", f"{tmp}/skills"]


def install_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        command = base_command(tmp)
        first = subprocess.run(command, capture_output=True, text=True)
        check(first.returncode == 0, f"install symlinks+hook: {first.stderr.strip()}")
        for name in EXPECTED_SKILLS:
            check((Path(tmp) / "skills" / name / "SKILL.md").is_file(), f"skill linked: {name}")
        build_skill = (Path(tmp) / "skills" / "fivem-build" / "SKILL.md").resolve()
        check(build_skill == ROOT / "codex" / "skills" / "fivem-build" / "SKILL.md",
              "Codex build skill override wins over kit skill")
        scripting_skill = (Path(tmp) / "skills" / "fivem-scripting" / "SKILL.md").resolve()
        check(scripting_skill == ROOT / "skills" / "fivem-scripting" / "SKILL.md",
              "shared rulebook falls back to kit skill")
        for name in EXPECTED_AGENTS:
            check((Path(tmp) / "codex" / "agents" / f"{name}.toml").is_symlink(), f"agent linked: {name}")
        hooks_data = json.loads((Path(tmp) / "codex" / "hooks.json").read_text())
        groups = hooks_data["hooks"]["PostToolUse"]
        check(any("post-edit-lint.py" in h.get("command", "")
                  for g in groups for h in g.get("hooks", [])),
              "PostToolUse fxlint hook merged")
        check(subprocess.run(command, capture_output=True).returncode == 0, "install is idempotent")
        check(subprocess.run(command + ["--check"], capture_output=True).returncode == 0, "check passes")

        conflict = Path(tmp) / "codex" / "agents" / "fivem-reviewer.toml"
        conflict.unlink()
        conflict.write_text("owned by user\n")
        check(subprocess.run(command, capture_output=True).returncode == 2, "conflict blocks installation")
        check(conflict.read_text() == "owned by user\n", "conflict preserved")
        check(subprocess.run(command + ["--uninstall"], capture_output=True).returncode == 0,
              "uninstall succeeds")
        check(conflict.read_text() == "owned by user\n", "uninstall preserves user file")
        check(not (Path(tmp) / "skills" / "fivem-build").exists(), "uninstall removes owned link")
        remaining = json.loads((Path(tmp) / "codex" / "hooks.json").read_text()) if \
            (Path(tmp) / "codex" / "hooks.json").exists() else {}
        check("post-edit-lint.py" not in json.dumps(remaining), "uninstall removes owned hook")


def agent_config_test() -> None:
    for name, (model, effort, sandbox) in EXPECTED_AGENTS.items():
        with open(ROOT / "codex" / "agents" / f"{name}.toml", "rb") as fh:
            data = tomllib.load(fh)
        check(data["name"] == name, f"agent name matches file: {name}")
        check(bool(data.get("description")), f"agent has description: {name}")
        check(data["model"] == model, f"agent model {model}: {name}")
        check(data["model_reasoning_effort"] == effort, f"agent effort {effort}: {name}")
        check(data["sandbox_mode"] == sandbox, f"agent sandbox {sandbox}: {name}")
        check(bool(data.get("developer_instructions")), f"agent has instructions: {name}")


def codex_hook_payload_test() -> None:
    # Codex-style apply_patch payload: patch markers must resolve to linted files.
    payload = json.dumps({
        "session_id": "fxkit-test",
        "cwd": str(ROOT),
        "hook_event_name": "PostToolUse",
        "tool_name": "apply_patch",
        "tool_input": {"command": f"*** Update File: {BAD_FILE}\n@@\n+--x\n"},
        "tool_response": {},
        "tool_use_id": "fxkit-test",
    })
    proc = subprocess.run([sys.executable, str(HOOK)], input=payload,
                          capture_output=True, text=True, timeout=30)
    check(proc.returncode == 0, "Codex apply_patch payload exits 0")
    data = json.loads(proc.stdout)
    check("fxlint:" in data.get("hookSpecificOutput", {}).get("additionalContext", ""),
          "Codex apply_patch payload surfaces lint findings")

    # Claude-style file_path payload still works after the refactor.
    claude = json.dumps({
        "cwd": str(ROOT), "tool_input": {"file_path": str(BAD_FILE)},
    })
    proc = subprocess.run([sys.executable, str(HOOK)], input=claude,
                          capture_output=True, text=True, timeout=30)
    check("fxlint:" in json.loads(proc.stdout).get("hookSpecificOutput", {})
          .get("additionalContext", ""), "Claude file_path payload still works")


if __name__ == "__main__":
    install_test()
    agent_config_test()
    codex_hook_payload_test()
    print("Codex adapter tests passed")
