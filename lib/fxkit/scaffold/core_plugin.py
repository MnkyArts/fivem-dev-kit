"""`fxnew --framework core`: scaffold a plugin for Liam's `core` framework by
copying `core/templates/plugin` and rewriting its placeholders exactly the way
`core/scripts/new-plugin.sh` does (DESIGN.md section 9.4).

The template is the single source of truth -- nothing about a plugin's shape is
duplicated here, so a change to `core/templates/plugin` reaches `fxnew`
immediately. core itself is never written to.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# The placeholder substitutions, LONGEST FIRST so `my_plugin` cannot eat the
# `MyPluginPage` / `MY_PLUGIN` forms (new-plugin.sh's sed order).
PLACEHOLDERS = ("MyPluginPage", "MY_PLUGIN", "my_plugin")

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TEXT_SUFFIXES = {
    ".lua", ".js", ".ts", ".json", ".vue", ".css", ".html", ".md", ".cfg", ".example", ".txt", ".yml", ".yaml",
}


class PluginExistsError(FileExistsError):
    pass


@dataclass
class CorePluginOptions:
    name: str
    dest_dir: Path
    template_dir: Path
    author: str = "you"
    desc: str = ""
    version: str = "1.0.0"
    keep_ui: bool = True          # --no-ui sets this to False
    force: bool = False
    core_name: str = "core"


def camel_name(name: str) -> str:
    """shop_robbery -> ShopRobbery (new-plugin.sh's awk one-liner)."""
    return "".join(part[:1].upper() + part[1:] for part in name.split("_") if part)


def validate_name(name: str, core_name: str = "core") -> None:
    if not NAME_RE.match(name):
        raise ValueError(
            f"invalid plugin name {name!r} -- lower-case letters, digits and underscores only, "
            "starting with a letter (an FXServer resource name)"
        )
    if name == core_name:
        raise ValueError(f"{name!r} is the framework itself")
    if name == "my_plugin":
        raise ValueError("'my_plugin' is the placeholder the template uses -- pick a real name")


def substitutions(name: str) -> list:
    return [
        ("MyPluginPage", camel_name(name) + "Page"),
        ("MY_PLUGIN", name.upper()),
        ("my_plugin", name),
    ]


def rewrite_text(text: str, name: str) -> str:
    for needle, replacement in substitutions(name):
        text = text.replace(needle, replacement)
    return text


RE_AUTHOR = re.compile(r"^author\s+'[^']*'", re.MULTILINE)
RE_DESC = re.compile(r"^description\s+'[^']*'", re.MULTILINE)
RE_VERSION = re.compile(r"^version\s+'[^']*'", re.MULTILINE)


def _lua_str(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def apply_manifest_metadata(text: str, author: str, desc: str, version: str) -> str:
    """Fill in author / description / version in the copied fxmanifest.lua."""
    text = RE_AUTHOR.sub(f"author '{_lua_str(author)}'", text, count=1)
    if desc:
        text = RE_DESC.sub(f"description '{_lua_str(desc)}'", text, count=1)
    text = RE_VERSION.sub(f"version '{_lua_str(version)}'", text, count=1)
    return text


def generate(opts: CorePluginOptions) -> tuple[Path, int]:
    """Copy + rewrite the template. Returns (resource_dir, files_rewritten)."""
    validate_name(opts.name, opts.core_name)
    template = opts.template_dir
    if not template.is_dir():
        raise ValueError(f"core plugin template not found at {template}")

    target = opts.dest_dir / opts.name
    if target.exists():
        if not opts.force:
            raise PluginExistsError(
                f"{target} already exists -- delete it first, pick another name, or pass --force"
            )
        shutil.rmtree(target)

    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(template, target)

    if not opts.keep_ui:
        ui_dir = target / "ui"
        if ui_dir.is_dir():
            shutil.rmtree(ui_dir)

    rewritten = 0
    for p in sorted(target.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            original = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue        # binary or unreadable: leave it exactly as copied
        text = rewrite_text(original, opts.name)
        if p.name == "fxmanifest.lua":
            text = apply_manifest_metadata(text, opts.author, opts.desc, opts.version)
        if text != original:
            p.write_text(text, encoding="utf-8")
            rewritten += 1
    return target, rewritten


def has_page(resource_dir: Path) -> bool:
    return (resource_dir / "ui" / "src" / "index.js").is_file()


def next_steps(resource_dir: Path, core_dir: Optional[Path], core_name: str = "core") -> str:
    """The hand-off text of core/scripts/new-plugin.sh, adapted to this run."""
    name = resource_dir.name
    workspace = resource_dir.parent
    core_path = core_dir or (workspace / core_name)
    page = has_page(resource_dir)
    lines = [
        "next steps:",
        "",
        "  1. server.cfg -- start it after core:",
        f"       ensure {core_name}",
        f"       ensure {name}",
        "",
        f"  2. Write the plugin ({name}/):",
        "       shared/config.lua   the Config global (both VMs)",
        "       client/main.lua     keys/net/callbacks at file scope, registrations in Core.onReady",
        "       server/main.lua     Core.Net.on / Core.Callback.register / Core.Commands.register",
        "       locales/en.json     Core.Locale.t strings ({{var}} placeholders)",
        "",
    ]
    if page:
        lines += [
            f"  3. The page in {name}/ui/src is compiled into CORE's shell -- this plugin ships no UI files.",
            f"       uncomment Core.UI.registerPage('{name}', {{ type = 'page' }}) in client/main.lua",
            f"       cd {workspace} && npm install      # once, or after adding a ui dependency",
            f"       cd {core_path}/ui && npm run build",
            f"       server console: refresh; restart {core_name}",
            f"     No page? Delete {name}/ui -- a plugin without a page ships no UI files at all.",
            "",
            f"  4. refresh; ensure {name}",
        ]
    else:
        lines += [
            f"  3. refresh; ensure {name}",
            "",
            f"     (no ui/ -- if this plugin grows a page later, copy {core_path}/templates/plugin/ui",
            f"      back in and rebuild core's shell: cd {core_path}/ui && npm run build; refresh; restart {core_name})",
        ]
    lines += ["", f"  docs: {resource_dir}/README.md, {core_path}/README.md, {core_path}/DESIGN.md"]
    return "\n".join(lines)
