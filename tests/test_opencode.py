#!/usr/bin/env python3
"""Smoke tests for the OpenCode adapter. Run with python3 tests/test_opencode.py."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
INSTALL = ROOT / "opencode" / "install.py"
PLUGIN = ROOT / "opencode" / "plugins" / "fivem-dev-kit.js"
BAD_FILE = ROOT / "tests" / "fixtures" / "bad-resource" / "client" / "main.lua"
GOOD_FILE = ROOT / "tests" / "fixtures" / "good-resource" / "client" / "main.lua"


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"PASS {message}")


def install_test() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "opencode"
        command = [sys.executable, str(INSTALL), "--config-dir", str(config)]
        first = subprocess.run(command, capture_output=True, text=True)
        check(first.returncode == 0, f"install symlinks: {first.stderr.strip()}")
        check((config / "agents" / "fivem.md").is_symlink(), "primary agent linked")
        check((config / "agents" / "fivem-core.md").is_symlink(), "core agent linked")
        check((config / "skills" / "fivem-build" / "SKILL.md").is_file(), "OpenCode build skill linked")
        check((config / "skills" / "fivem-scripting" / "SKILL.md").is_file(), "shared rulebook linked")
        check((config / "skills" / "fivem-core" / "SKILL.md").is_file(), "core skill linked")
        check((config / "commands" / "fivem-core.md").is_symlink(), "core command linked")
        check((config / "plugins" / "fivem-dev-kit.js").is_symlink(), "lint plugin linked")
        check(subprocess.run(command, capture_output=True).returncode == 0, "install is idempotent")
        check(subprocess.run(command + ["--check"], capture_output=True).returncode == 0, "check passes")

        # An unrelated file must not be overwritten or removed.
        conflict = config / "agents" / "fivem-reviewer.md"
        conflict.unlink()
        conflict.write_text("owned by user\n")
        check(subprocess.run(command, capture_output=True).returncode == 2, "conflict blocks installation")
        check(conflict.read_text() == "owned by user\n", "conflict preserved")
        check(subprocess.run(command + ["--uninstall"], capture_output=True).returncode == 0,
              "uninstall succeeds")
        check(conflict.read_text() == "owned by user\n", "uninstall preserves user file")
        check(not (config / "agents" / "fivem.md").exists(), "uninstall removes owned link")


def plugin_test() -> None:
    bun = shutil.which("bun")
    if not bun:
        print("SKIP plugin runtime test (bun not installed)")
        return
    # Import through a symlink: the plugin must still derive the real kit root.
    with tempfile.TemporaryDirectory() as tmp:
        link = Path(tmp) / "fivem-dev-kit.js"
        link.symlink_to(PLUGIN)
        script = f"""
import {{ FiveMDevKit }} from {json.dumps(link.as_uri())};
const plugin = await FiveMDevKit({{ directory: {json.dumps(str(ROOT))} }});
const shell = {{ env: {{}} }};
await plugin['shell.env']({{}}, shell);
const bad = {{ title: '', output: 'edited', metadata: {{}} }};
await plugin['tool.execute.after']({{ tool: 'edit', args: {{ filePath: {json.dumps(str(BAD_FILE))} }}, sessionID: 'test', callID: '1' }}, bad);
const good = {{ title: '', output: 'edited', metadata: {{}} }};
await plugin['tool.execute.after']({{ tool: 'write', args: {{ filePath: {json.dumps(str(GOOD_FILE))} }}, sessionID: 'test', callID: '2' }}, good);
const patch = {{ title: '', output: 'edited', metadata: {{}} }};
await plugin['tool.execute.after']({{ tool: 'apply_patch', args: {{ patch: '*** Update File: {BAD_FILE}\\n' }}, sessionID: 'test', callID: '3' }}, patch);
const outside = {{}};
await plugin.config(outside);
const workspace = {{}};
await (await FiveMDevKit({{ directory: {json.dumps(str(ROOT.parent))} }})).config(workspace);
const resources = {{}};
await (await FiveMDevKit({{ directory: {json.dumps(str(ROOT.parent / 'resources'))} }})).config(resources);
const core = {{}};
await (await FiveMDevKit({{ directory: {json.dumps(str(ROOT.parent / 'resources' / 'core'))} }})).config(core);
const custom = {{ default_agent: 'build' }};
await (await FiveMDevKit({{ directory: {json.dumps(str(ROOT.parent))} }})).config(custom);
console.log(JSON.stringify({{ root: shell.env.FIVEM_DEV_KIT_ROOT, path: shell.env.PATH, bad: bad.output, good: good.output, patch: patch.output, outside, workspace, resources, core, custom }}));
"""
        proc = subprocess.run([bun, "-e", script], cwd=ROOT, capture_output=True, text=True, timeout=90)
        check(proc.returncode == 0, f"plugin runs: {proc.stderr.strip()}")
        result = json.loads(proc.stdout.strip().splitlines()[-1])
        check(result["root"] == str(ROOT), "plugin resolves kit root through symlink")
        check(result["path"].startswith(str(ROOT / "bin") + ":"), "shell PATH includes kit bin")
        check("fxlint:" in result["bad"], "edit surfaces lint findings")
        check(result["good"] == "edited", "clean write remains silent")
        check("fxlint:" in result["patch"], "apply_patch surfaces lint findings")
        check("default_agent" not in result["outside"], "non-FiveM projects keep their default agent")
        check(result["workspace"]["default_agent"] == "fivem", "workspace defaults to fivem agent")
        check(result["resources"]["default_agent"] == "fivem", "resources default to fivem agent")
        check(result["core"]["default_agent"] == "fivem-core", "core defaults to core agent")
        check("instructions" not in result["core"], "core's local AGENTS.md is not injected twice")
        check(result["custom"]["default_agent"] == "build", "explicit default agent is preserved")
        rules = str(ROOT.parent / "resources" / "core" / "AGENTS.md")
        check(rules in result["workspace"]["instructions"], "workspace loads core agreement")


if __name__ == "__main__":
    install_test()
    plugin_test()
    print("OpenCode adapter tests passed")
