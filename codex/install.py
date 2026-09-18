#!/usr/bin/env python3
"""Install fivem-dev-kit into Codex with live, conflict-safe symlinks.

Links the seven skills into the global skills directory (``~/.agents/skills``,
read by Codex CLI/IDE/app), the six custom agents into
``~/.codex/agents/``, and merges the post-edit ``fxlint`` hook into
``~/.codex/hooks.json``. The ``fxref`` database, kit ``config.json``, FiveM
CLIs, and rulebook stay in this checkout.

Nothing here edits ``~/.codex/config.toml``; model profiles from
``codex/config.example.toml`` are applied manually (see codex/README.md).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys


KIT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = KIT_ROOT / "codex"
HOOK_HANDLER = KIT_ROOT / "hooks-handlers" / "post-edit-lint.py"

SKILL_NAMES = (
    "fivem-build",
    "fivem-review",
    "fivem-reference",
    "fivem-scripting",
    "fivem-server",
    "fivem-client",
    "fivem-core",
)
AGENT_NAMES = (
    "fivem",
    "fivem-core",
    "fivem-native-scout",
    "fivem-implementer",
    "fivem-reviewer",
    "fivem-deep-reviewer",
)
HOOK_DESCRIPTION = (
    "After Codex writes or edits a FiveM script file, run fxlint and surface findings as context."
)


def hook_command() -> str:
    return f"python3 {KIT_ROOT / 'hooks-handlers' / 'post-edit-lint.py'}"


def hook_entry() -> dict:
    return {
        "type": "command",
        "command": hook_command(),
        "timeout": 15,
        "statusMessage": "Running fxlint on edited FiveM files",
    }


def skill_sources() -> list[tuple[str, Path]]:
    """(name, source_dir) — adapter override wins, else the shared kit skill."""
    result = []
    for name in SKILL_NAMES:
        adapter_skill = ADAPTER / "skills" / name
        if adapter_skill.is_dir():
            result.append((name, adapter_skill))
        else:
            result.append((name, KIT_ROOT / "skills" / name))
    return result


def owned_link(source: Path, target: Path) -> bool:
    return target.is_symlink() and (target.parent / os.readlink(target)).resolve() == source.resolve()


def link_state(source: Path, target: Path) -> str:
    if owned_link(source, target):
        return "installed"
    if target.exists() or target.is_symlink():
        return "conflict"
    return "missing"


def link_source_target(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(Path(os.path.relpath(source, target.parent)), target_is_directory=source.is_dir())


def read_hooks(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def hook_installed(data: dict) -> bool:
    groups = (data.get("hooks") or {}).get("PostToolUse") or []
    for group in groups:
        for hook in group.get("hooks") or []:
            if hook.get("command") == hook_command():
                return True
    return False


def add_hook(data: dict) -> dict:
    data = {k: v for k, v in data.items()}
    hooks = dict(data.get("hooks") or {})
    groups = list(hooks.get("PostToolUse") or [])
    for group in groups:
        matcher = group.get("matcher") or ""
        if "apply_patch" in matcher and any(
            h.get("command") == hook_command() for h in group.get("hooks") or []
        ):
            return {"hooks": hooks, **{k: v for k, v in data.items() if k != "hooks"}}
    groups.append({"matcher": "apply_patch|Edit|Write", "hooks": [hook_entry()]})
    hooks["PostToolUse"] = groups
    if "description" not in data:
        data["description"] = HOOK_DESCRIPTION
    data["hooks"] = hooks
    return data


def remove_hook(data: dict) -> dict:
    hooks = dict(data.get("hooks") or {})
    groups = []
    for group in hooks.get("PostToolUse") or []:
        kept = [h for h in group.get("hooks") or [] if h.get("command") != hook_command()]
        if kept:
            group = dict(group)
            group["hooks"] = kept
            groups.append(group)
    if groups:
        hooks["PostToolUse"] = groups
    else:
        hooks.pop("PostToolUse", None)
    data = dict(data)
    if hooks:
        data["hooks"] = hooks
    else:
        data.pop("hooks", None)
        if data.get("description") == HOOK_DESCRIPTION:
            data.pop("description", None)
    return data


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="show installed/missing/conflicting entries")
    group.add_argument("--uninstall", action="store_true", help="remove only symlinks/hook installed by this script")
    default_codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    parser.add_argument("--codex-home", type=Path, default=default_codex_home,
                        help=f"Codex home directory (default: {default_codex_home})")
    parser.add_argument("--skills-dir", type=Path, default=Path.home() / ".agents" / "skills",
                        help="global skills directory (default: ~/.agents/skills)")
    args = parser.parse_args()
    codex_home = args.codex_home.expanduser()
    skills_dir = args.skills_dir.expanduser()
    hooks_path = codex_home / "hooks.json"

    links = [(src, skills_dir / name) for name, src in skill_sources()]
    links += [(ADAPTER / "agents" / f"{name}.toml", codex_home / "agents" / f"{name}.toml")
              for name in AGENT_NAMES]

    if args.check:
        good = True
        for source, target in links:
            state = link_state(source, target)
            good &= state == "installed"
            print(f"{state:9} {target}")
        hook_state = "installed" if hook_installed(read_hooks(hooks_path)) else "missing"
        good &= hook_state == "installed"
        print(f"{hook_state:9} {hooks_path} (PostToolUse fxlint hook)")
        return 0 if good else 1

    if args.uninstall:
        for source, target in links:
            if owned_link(source, target):
                target.unlink()
                print(f"removed   {target}")
        data = read_hooks(hooks_path)
        if hook_installed(data):
            data = remove_hook(data)
            if data:
                hooks_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            else:
                hooks_path.unlink()
            print(f"removed   {hooks_path} (PostToolUse fxlint hook)")
        return 0

    conflicts = [target for source, target in links
                 if (target.exists() or target.is_symlink()) and not owned_link(source, target)]
    if conflicts:
        print("Refusing to replace existing files or links:", file=sys.stderr)
        for target in conflicts:
            print(f"  {target}", file=sys.stderr)
        return 2

    for source, target in links:
        if owned_link(source, target):
            continue
        if not source.exists():
            print(f"missing source, skipping: {source}", file=sys.stderr)
            return 2
        link_source_target(source, target)
        print(f"linked    {target} -> {source}")

    data = read_hooks(hooks_path)
    if hook_installed(data):
        print(f"installed {hooks_path} (PostToolUse fxlint hook already present)")
    else:
        hooks_path.parent.mkdir(parents=True, exist_ok=True)
        hooks_path.write_text(json.dumps(add_hook(data), indent=2) + "\n", encoding="utf-8")
        print(f"installed {hooks_path} (PostToolUse fxlint hook)")

    print()
    print("Add the kit CLIs to Codex's shell environment, e.g. in ~/.bashrc:")
    print(f"  export FIVEM_DEV_KIT_ROOT={KIT_ROOT}")
    print(f"  export CLAUDE_PLUGIN_ROOT=$FIVEM_DEV_KIT_ROOT  # shared skill text also uses this name")
    print(f"  export PATH=\"$FIVEM_DEV_KIT_ROOT/bin:$PATH\"")
    print("Then restart Codex and copy codex/AGENTS.md into the FiveM workspace root AGENTS.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
