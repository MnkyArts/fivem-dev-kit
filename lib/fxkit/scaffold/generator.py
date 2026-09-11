"""fxnew's resource scaffolder: fills in the template files under
lib/fxkit/scaffold/templates/ and assembles fxmanifest.lua (which has too
much conditional structure -- client/server/nui/framework/ox_lib all toggle
independent chunks of it -- to stay readable as one flat template).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

FRAMEWORKS = ("standalone", "esx", "qb", "qbox", "ox")
LANGUAGES = ("lua", "js")

FRAMEWORK_DEPENDENCY = {"esx": "es_extended", "qb": "qb-core", "qbox": "qbx_core", "ox": "ox_core"}

FRAMEWORK_BOOTSTRAP = {
    "lua": {
        "esx": "\nESX = exports['es_extended']:getSharedObject()\n",
        "qb": "\nQBCore = exports['qb-core']:GetCoreObject()\n",
        "qbox": "\nQBCore = exports.qbx_core:GetCoreObject()\n",
        "ox": "\nOx = require '@ox_core.lib.init'\n",
    },
    "js": {
        "esx": "\nglobalThis.ESX = exports['es_extended'].getSharedObject();\n",
        "qb": "\nglobalThis.QBCore = exports['qb-core'].GetCoreObject();\n",
        "qbox": "\nglobalThis.QBCore = exports.qbx_core.GetCoreObject();\n",
        # unverified -- ox_core's JS-side bootstrap isn't documented anywhere fxref/fxref's
        # sources cover; flagged rather than guessed at silently.
        "ox": "\n// TODO: verify the ox_core bootstrap for JS -- 'require' is Lua-only sugar,\n"
              "// ox_core's JS API (if any) needs checking against the ox_core source/docs.\n",
    },
}


class ResourceExistsError(FileExistsError):
    pass


@dataclass
class ScaffoldOptions:
    name: str
    dest_dir: Path
    lang: str = "lua"
    framework: str = "standalone"
    ox_lib: bool = False
    no_client: bool = False
    no_server: bool = False
    nui: bool = False
    author: str = "you"
    desc: str = ""
    force: bool = False

    @property
    def ext(self) -> str:
        return "lua" if self.lang == "lua" else "js"


def sanitize_name(raw: str) -> str:
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    s = re.sub(r"-{2,}", "-", s).strip("-_")
    return s or "myresource"


def _load(template_name: str) -> str:
    return (TEMPLATES_DIR / template_name).read_text(encoding="utf-8")


def _fill(text: str, values: dict) -> str:
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def _block(key: str, items: list) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return f"{key} {{ '{items[0]}' }}"
    inner = "\n".join(f"    '{it}'," for it in items)
    return f"{key} {{\n{inner}\n}}"


def _manifest_text(opts: ScaffoldOptions) -> str:
    ext = opts.ext
    lines = [
        "fx_version 'cerulean'",
        "game 'gta5'",
        "",
        f"author '{opts.author}'",
        f"description '{opts.desc}'",
        "version '1.0.0'",
    ]

    shared = []
    if opts.ox_lib:
        shared.append("@ox_lib/init.lua")
    shared.append(f"shared/config.{ext}")
    lines += ["", _block("shared_scripts", shared)]

    if not opts.no_client:
        lines += ["", _block("client_scripts", [f"client/*.{ext}"])]
    if not opts.no_server:
        lines += ["", _block("server_scripts", [f"server/*.{ext}"])]

    deps = []
    if opts.ox_lib:
        deps.append("ox_lib")
    if opts.framework != "standalone":
        deps.append(FRAMEWORK_DEPENDENCY[opts.framework])
    if deps:
        lines += ["", _block("dependencies", deps)]

    if opts.nui:
        lines += ["", "ui_page 'html/index.html'", "", _block("files", ["html/**"])]

    return "\n".join(lines).rstrip() + "\n"


def _nui_block(opts: ScaffoldOptions) -> str:
    if not opts.nui or opts.no_client:
        return ""
    frag = _load(f"nui_client.{opts.ext}.tmpl")
    return _fill(frag, {"name": opts.name})


def _readme_text(opts: ScaffoldOptions) -> str:
    ext = opts.ext
    tree_lines = []
    checklist_lines = []
    if opts.nui:
        tree_lines.append(f"  html/index.html\n  html/style.css\n  html/script.js")
        checklist_lines.append(
            f"- [ ] `/{opts.name}_ui` opens the NUI, Escape/close button closes it and returns focus to the game.\n"
        )
    values = {
        "name": opts.name,
        "description": opts.desc,
        "lang": opts.lang,
        "framework": opts.framework,
        "ext": ext,
        "nui_suffix": ", NUI" if opts.nui else "",
        "nui_tree": ("\n" + "\n".join(tree_lines)) if tree_lines else "",
        "nui_checklist": "".join(checklist_lines),
    }
    return _fill(_load("README.md.tmpl"), values)


def generate(opts: ScaffoldOptions) -> Path:
    if opts.lang not in LANGUAGES:
        raise ValueError(f"unknown --lang {opts.lang!r}, expected one of {LANGUAGES}")
    if opts.framework not in FRAMEWORKS:
        raise ValueError(f"unknown --framework {opts.framework!r}, expected one of {FRAMEWORKS}")
    if opts.no_client and opts.no_server:
        raise ValueError("--no-client and --no-server together would generate an empty resource")
    if opts.nui and opts.no_client:
        raise ValueError("--nui needs a client (don't pass --no-client)")

    resource_dir = opts.dest_dir / opts.name
    if resource_dir.exists():
        if not opts.force:
            raise ResourceExistsError(f"{resource_dir} already exists (use --force to overwrite)")
    resource_dir.mkdir(parents=True, exist_ok=True)

    ext = opts.ext
    framework_bootstrap = FRAMEWORK_BOOTSTRAP[opts.lang].get(opts.framework, "") if opts.framework != "standalone" else ""

    (resource_dir / "fxmanifest.lua").write_text(_manifest_text(opts), encoding="utf-8")

    shared_dir = resource_dir / "shared"
    shared_dir.mkdir(exist_ok=True)
    (shared_dir / f"config.{ext}").write_text(
        _fill(_load(f"config.{ext}.tmpl"), {"framework_bootstrap": framework_bootstrap}), encoding="utf-8"
    )

    if not opts.no_client:
        client_dir = resource_dir / "client"
        client_dir.mkdir(exist_ok=True)
        (client_dir / f"main.{ext}").write_text(
            _fill(_load(f"client_main.{ext}.tmpl"), {"name": opts.name, "nui_block": _nui_block(opts)}),
            encoding="utf-8",
        )

    if not opts.no_server:
        server_dir = resource_dir / "server"
        server_dir.mkdir(exist_ok=True)
        (server_dir / f"main.{ext}").write_text(
            _fill(_load(f"server_main.{ext}.tmpl"), {"name": opts.name}), encoding="utf-8"
        )

    if opts.nui:
        html_dir = resource_dir / "html"
        html_dir.mkdir(exist_ok=True)
        (html_dir / "index.html").write_text(_fill(_load("nui_index.html.tmpl"), {"name": opts.name}), encoding="utf-8")
        (html_dir / "style.css").write_text(_load("nui_style.css.tmpl"), encoding="utf-8")
        (html_dir / "script.js").write_text(
            _fill(_load("nui_script.js.tmpl"), {"name": opts.name, "ext": ext}), encoding="utf-8"
        )

    (resource_dir / "README.md").write_text(_readme_text(opts), encoding="utf-8")
    (resource_dir / ".fxlintrc.json").write_text(_load("fxlintrc.json.tmpl"), encoding="utf-8")

    return resource_dir
