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
# `MyPlugin` / `MY_PLUGIN` forms (new-plugin.sh's sed order). `MyPlugin` (not
# `MyPluginPage`) is the camel placeholder: the template's TypeScript carries
# `MyPluginProps`, `MyPluginEvents`, `MyPluginIncoming`, `MyPluginRpc`.
PLACEHOLDERS = ("MyPlugin", "MY_PLUGIN", "my_plugin")

NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
TEXT_SUFFIXES = {
    ".lua", ".js", ".ts", ".json", ".vue", ".css", ".html", ".md", ".cfg", ".example", ".txt", ".yml", ".yaml",
}
# Text files the template ships that have no suffix at all (`Path('.gitignore').suffix == ''`).
TEXT_NAMES = {".gitignore", ".npmrc", ".editorconfig"}


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
        ("MyPlugin", camel_name(name)),
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


# ---------------------------------------------------------------------------
# --no-ui: take the UI back out of the copy
#
# The template is a UI plugin (core DESIGN section 38.3): it opts in with
# `core_ui 'ui/dist'` + a `files { 'ui/dist/**' }` entry and its client/main.lua
# talks about the page. Deleting ui/ alone would leave a manifest that promises
# core a frontend that is not there (fxlint K014/K015 say so, and core prints an
# error on every start), so the two manifest lines and the page paragraph go too.
# Every transformation below is a no-op when the template stops looking like this.
# ---------------------------------------------------------------------------
RE_CORE_UI_LINE = re.compile(r"^\s*core_ui\s")
RE_COMMENT_LINE = re.compile(r"^\s*--")
RE_FILES_ENTRY = re.compile(r"^\s*'([^']+)'\s*,?\s*$")
UI_DIR_HINTS = ("ui/dist", "core_ui", "cfx-nui-")
SENTENCE_END = (".", ":", "!", "?", "—", ")")


def _is_blank(line: str) -> bool:
    return line.strip() == ""


def _drop_comment_run_above(lines: list, index: int) -> int:
    """Delete the contiguous `--` comment paragraph directly above `lines[index]`.
    Returns the new index of that line."""
    start = index
    while start > 0 and RE_COMMENT_LINE.match(lines[start - 1]):
        start -= 1
    del lines[start:index]
    return start


def strip_ui_from_manifest(text: str, ui_dir: str = "ui/dist") -> str:
    """Remove the `core_ui` opt-in, its comment paragraph, the `files {}` entry
    that ships the build, and the comment lines that only explain them."""
    out: list = []
    for line in text.splitlines():
        if RE_CORE_UI_LINE.match(line):
            _drop_comment_run_above(out, len(out))      # the opt-in's own paragraph
            continue
        m = RE_FILES_ENTRY.match(line)
        if m and (m.group(1).startswith(ui_dir) or m.group(1).startswith("ui/")):
            continue
        if RE_COMMENT_LINE.match(line) and any(h in line for h in UI_DIR_HINTS):
            # ... and the lead-in line above it, when that sentence ran on into this one
            while (out and RE_COMMENT_LINE.match(out[-1])
                   and not out[-1].rstrip().endswith(SENTENCE_END)):
                out.pop()
            continue
        out.append(line)
    kept = [line for i, line in enumerate(out)            # never two blank lines in a row
            if not (_is_blank(line) and i and _is_blank(out[i - 1]))]
    return "\n".join(kept).rstrip("\n") + "\n"


RE_REGISTER_PAGE = re.compile(r"Core\.UI\.registerPage")
NO_UI_NOTE = (
    "-- This plugin has no page (scaffolded with --no-ui). To add one later, copy\n"
    "{i}-- core/templates/plugin/ui/ back in and put `core_ui 'ui/dist'` and the\n"
    "{i}-- 'ui/dist/**' files entry back into fxmanifest.lua (core DESIGN §38.3)."
)


def strip_ui_from_client(text: str) -> str:
    """Replace the template's page paragraph in client/main.lua with a pointer to
    the way back. The paragraph is commented out already, so this is about not
    leaving instructions for a ui/ folder that is no longer there."""
    lines = text.splitlines()
    hit = next((i for i, line in enumerate(lines)
                if RE_COMMENT_LINE.match(line) and RE_REGISTER_PAGE.search(line)), None)
    if hit is None:
        return text
    start, end = hit, hit + 1
    while start > 0 and RE_COMMENT_LINE.match(lines[start - 1]):
        start -= 1
    while end < len(lines) and RE_COMMENT_LINE.match(lines[end]):
        end += 1
    indent = lines[start][:len(lines[start]) - len(lines[start].lstrip())]
    lines[start:end] = (indent + NO_UI_NOTE.format(i=indent)).splitlines()
    return "\n".join(lines) + "\n"


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

    ui_dir_name = ui_dir_of(target)
    if not opts.keep_ui:
        ui_dir = target / "ui"
        if ui_dir.is_dir():
            shutil.rmtree(ui_dir)

    rewritten = 0
    for p in sorted(target.rglob("*")):
        if not p.is_file():
            continue
        if p.suffix.lower() not in TEXT_SUFFIXES and p.name not in TEXT_NAMES:
            continue
        try:
            original = p.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue        # binary or unreadable: leave it exactly as copied
        text = rewrite_text(original, opts.name)
        if p.name == "fxmanifest.lua":
            text = apply_manifest_metadata(text, opts.author, opts.desc, opts.version)
            if not opts.keep_ui:
                text = strip_ui_from_manifest(text, ui_dir_name)
        elif not opts.keep_ui and p.name == "main.lua" and p.parent.name == "client":
            text = strip_ui_from_client(text)
        if text != original:
            p.write_text(text, encoding="utf-8")
            rewritten += 1
    return target, rewritten


RE_MANIFEST_CORE_UI = re.compile(r"^\s*core_ui\s+'([^']+)'", re.MULTILINE)


def ui_dir_of(resource_dir: Path, default: str = "ui/dist") -> str:
    """The `core_ui '<dir>'` folder the copied manifest opts into (core DESIGN
    section 38.4), so --no-ui and the next steps never hard-code it twice."""
    try:
        m = RE_MANIFEST_CORE_UI.search((resource_dir / "fxmanifest.lua").read_text(encoding="utf-8"))
    except OSError:
        return default
    return m.group(1) if m else default


def has_page(resource_dir: Path) -> bool:
    """A UI plugin ships `ui/src/index.ts` (the template) or `index.js`."""
    src = resource_dir / "ui" / "src"
    return (src / "index.ts").is_file() or (src / "index.js").is_file()


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
        dist = ui_dir_of(resource_dir)
        lines += [
            f"  3. This plugin OWNS its frontend ({name}/ui): it is built here and shipped in",
            f"     {name}/{dist}, which core imports at runtime -- core is never rebuilt for it.",
            f"       uncomment Core.UI.registerPage('{name}', {{ type = 'page' }}) in client/main.lua",
            f"       cd {workspace} && npm install          # once, and after adding a ui dependency",
            f"       npm run build -w {name}-ui             # -> {name}/{dist} (commit it, like core/html)",
            f"       npm run dev -w {name}-ui               # or: the real shell + a fake Lua, in a browser",
            f"     After every UI change: build again, then `restart {name}` in the server console.",
            f"     No core rebuild, no `restart {core_name}`, no CEF reload.",
            "",
            f"  4. refresh; ensure {name}",
        ]
    else:
        lines += [
            f"  3. refresh; ensure {name}",
            "",
            "     (no ui/ -- to give this plugin a page later, copy",
            f"      {core_path}/templates/plugin/ui back in, put `core_ui 'ui/dist'` and the",
            "      'ui/dist/**' files entry back into fxmanifest.lua, then",
            f"      cd {workspace} && npm install && npm run build -w {name}-ui; restart {name})",
        ]
    lines += ["", f"  docs: {resource_dir}/README.md, {core_path}/README.md, {core_path}/DESIGN.md §38"]
    return "\n".join(lines)
