#!/usr/bin/env python3
"""Install fivem-dev-kit into OpenCode with live, conflict-safe symlinks."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys


KIT_ROOT = Path(__file__).resolve().parents[1]
ADAPTER = KIT_ROOT / "opencode"


def entries(config_dir: Path) -> list[tuple[Path, Path]]:
    result = []
    for kind, pattern in (("agents", "*.md"), ("commands", "*.md"), ("plugins", "*.js")):
        for source in sorted((ADAPTER / kind).glob(pattern)):
            result.append((source, config_dir / kind / source.name))
    for source in sorted((KIT_ROOT / "skills").glob("*/SKILL.md")):
        name = source.parent.name
        adapter_skill = ADAPTER / "skills" / name
        result.append((adapter_skill if adapter_skill.is_dir() else source.parent,
                       config_dir / "skills" / name))
    return result


def owned_link(source: Path, target: Path) -> bool:
    return target.is_symlink() and (target.parent / os.readlink(target)).resolve() == source.resolve()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--check", action="store_true", help="show installed/missing/conflicting entries")
    group.add_argument("--uninstall", action="store_true", help="remove only symlinks installed by this script")
    default_config = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"
    parser.add_argument("--config-dir", type=Path, default=default_config,
                        help=f"OpenCode config directory (default: {default_config})")
    args = parser.parse_args()
    links = entries(args.config_dir.expanduser())

    if args.check:
        good = True
        for source, target in links:
            state = "installed" if owned_link(source, target) else "conflict" if target.exists() or target.is_symlink() else "missing"
            good &= state == "installed"
            print(f"{state:9} {target}")
        return 0 if good else 1

    if args.uninstall:
        for source, target in links:
            if owned_link(source, target):
                target.unlink()
                print(f"removed   {target}")
        return 0

    conflicts = [target for source, target in links
                 if (target.exists() or target.is_symlink()) and not owned_link(source, target)]
    if conflicts:
        print("Refusing to replace existing OpenCode files or links:", file=sys.stderr)
        for target in conflicts:
            print(f"  {target}", file=sys.stderr)
        return 2

    for source, target in links:
        if owned_link(source, target):
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(Path(os.path.relpath(source, target.parent)), target_is_directory=source.is_dir())
        print(f"linked    {target} -> {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
