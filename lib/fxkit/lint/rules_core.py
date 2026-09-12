"""K001-K013: conventions of Liam's `core` framework (DESIGN.md section 9.3).

These rules only run for a *core plugin* (a resource whose manifest declares
`dependency 'core'` / `'@core/import.lua'`, or that calls the `Core` API) and,
where marked "both", for core itself. Rules marked "plugin" never run inside
core -- core legitimately uses raw natives, raw events and its own internals.

Scoping lives in `classify()`; every check takes the resulting `CoreScope` so
one place decides what runs where.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .model import Finding

CORE_IMPORT = "@core/import.lua"

# K004: calls that register something *inside* core and are replayed by
# Core.onReady after a core restart (DESIGN section 9.3).
REGISTRATION_CALLS = (
    "Core.Markers.add", "Core.Markers.addGlobal", "Core.Markers.addFor",
    "Core.TextLabels.add", "Core.TextLabels.addGlobal", "Core.TextLabels.addFor",
    "Core.Blips.add", "Core.Blips.addGlobal", "Core.Blips.addFor",
    "Core.Interactions.add", "Core.Interactions.addGlobal", "Core.Interactions.addFor",
    "Core.Doors.add", "Core.Doors.register",
    "Core.UI.registerPage",
    "Core.Cron.every", "Core.Cron.at", "Core.Cron.daily",
)
RE_REGISTRATION = re.compile(
    r"(?<![\w.])(" + "|".join(re.escape(c) for c in REGISTRATION_CALLS) + r")\s*\("
)

RE_K001 = re.compile(r"type\s*\([^()]*\)\s*[=~]==?\s*['\"]function['\"]"
                      r"|['\"]function['\"]\s*[=~]==?\s*type\s*\(")
RE_K002_USE = re.compile(r"\b(NetworkGetEntityFromNetworkId|GetEntityFromStateBagName)\s*\(")
RE_K002_GUARD = re.compile(r"\bNetworkDoesEntityExistWithNetworkId\s*\(")
RE_K003_EVENT = re.compile(r"(?<![\w.])(RegisterNetEvent|RegisterServerEvent)\s*\(")
RE_K003_ADD = re.compile(r"(?<![\w.])AddEventHandler\s*\(\s*['\"]([^'\"]+)['\"]")
RE_K003_CMD = re.compile(r"(?<![\w.])RegisterCommand\s*\(")
RE_K003_TRIGGER = re.compile(r"(?<![\w.])(TriggerServerEvent|TriggerClientEvent|TriggerLatentClientEvent|TriggerLatentServerEvent)\s*\(")
RE_K003_KEYMAP = re.compile(r"(?<![\w.])RegisterKeyMapping\s*\(")
RE_K005_CLEANUP = re.compile(
    r"(?<![\w.])Core\.[A-Z]\w*(?:\.\w+)?\.(remove|removeAll|removeGlobal|unregister\w*|off|hide|clear\w*)\s*\("
)
RE_K005_CALL = re.compile(r"[A-Za-z_][\w.:]*\s*\(")
RE_K006 = re.compile(r"backdrop-filter|-webkit-backdrop-filter|backdrop-blur|backdropFilter")
RE_K011_USE = re.compile(r"(?<![\w.])Core\.Locale\.t\s*\(")
RE_K012 = re.compile(r"(?<![\w.])(SendNUIMessage|SendNuiMessage|RegisterNUICallback|RegisterNuiCallback"
                      r"|RegisterRawNuiCallback|SetNuiFocus|SetNuiFocusKeepInput)\s*\(")
RE_USES_CORE = re.compile(r"(?<![\w.])Core\.([A-Z]\w*\.\w+|on|onReady|onPlayerLoaded|isReady|emitHook)\s*[\(.]")

UI_SUFFIXES = (".vue", ".css", ".js", ".ts")
# generated/vendored UI output -- never plugin or core *sources*
UI_SKIP_DIRS = frozenset({
    "node_modules", "dist", "build", "storybook-static", "coverage", ".vite", ".nuxt", "out",
})


@dataclass
class CoreScope:
    """What the K rules may do for one resource."""
    kind: str = ""                       # '' (not a core resource) | 'plugin' | 'core'
    resource_dir: Optional[Path] = None
    manifest: object = None
    defined_core_names: set = field(default_factory=set)
    resolved: Optional[dict] = None      # fxref core resolve result, None = skip K013

    @property
    def active(self) -> bool:
        return self.kind in ("plugin", "core")

    @property
    def is_plugin(self) -> bool:
        return self.kind == "plugin"


def _core_root() -> Optional[Path]:
    try:
        from fxkit import config
        paths = config.core_paths()
    except Exception:                     # noqa: BLE001 - config is optional
        return None
    if not paths:
        return None
    try:
        return paths["path"].resolve()
    except OSError:
        return None


def manifest_declares_core(manifest) -> bool:
    if manifest is None or getattr(manifest, "path", None) is None:
        return False
    if any(d.strip().lower() == "core" for d in getattr(manifest, "dependencies", [])):
        return True
    return any(s.strip() == CORE_IMPORT for s in getattr(manifest, "shared_scripts", []))


def classify(resource_dir: Optional[Path], manifest, parsed_files: list) -> CoreScope:
    """Decide whether this resource is core itself, a core plugin, or neither."""
    scope = CoreScope(resource_dir=resource_dir, manifest=manifest)
    if resource_dir is None:
        return scope

    root = _core_root()
    try:
        here = resource_dir.resolve()
    except OSError:
        here = resource_dir
    is_core = bool(root and here == root)
    if not is_core and manifest is not None and getattr(manifest, "path", None) is not None:
        # a checkout of core somewhere else: its manifest ships import.lua itself
        if "import.lua" in getattr(manifest, "shared_scripts", []) and here.name == "core":
            is_core = True

    uses_core = any(RE_USES_CORE.search("\n".join(pf.clean_lines)) for pf in parsed_files)
    if is_core:
        scope.kind = "core"
    elif manifest_declares_core(manifest) or uses_core:
        scope.kind = "plugin"
    return scope


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _enclosing_functions(pf, line: int) -> list:
    return [f for f in pf.open_frames(line) if f.kind == "function" and f.start_line != line]


def _at_file_scope(pf, line: int) -> bool:
    """True when `line` sits in the main chunk (no enclosing function literal)."""
    return not _enclosing_functions(pf, line) and pf.table_depth_start.get(line, 0) == 0


def _end(pf, frame) -> int:
    return frame.end_line if frame.end_line > 0 else pf.line_count()


# ---------------------------------------------------------------------------
# K001 -- callbacks across the export hop are callable tables
# ---------------------------------------------------------------------------
def check_k001(pf, scope) -> list:
    # Deviation from a literal reading of DESIGN section 9.3's "(both)": inside
    # core every `type(fn) ~= 'function'` guard validates a value from its OWN
    # VM (the libs are compiled into the caller's VM, so a handler passed to
    # Core.Net.on/Keys.register/Registry.onOwnerStop really is a function) --
    # running it there produced 39 findings on correct code. The callable-table
    # problem only exists for a value that actually crossed the export hop,
    # which is the plugin side of the boundary.
    if not scope.is_plugin:
        return []
    out = []
    for i, line in enumerate(pf.code_lines, start=1):
        if RE_K001.search(line):
            out.append(Finding(
                pf.rel_path, i, "K001", "warn",
                "type(x) == 'function' -- a callback that crossed core's export hop is a callable *table*",
                "use Core.Utils.isCallable(v) (DESIGN/AGENTS section 3); type(v) == 'function' is false for proxied callbacks",
            ))
    return out


# ---------------------------------------------------------------------------
# K002 -- netId must be checked before it is dereferenced
# ---------------------------------------------------------------------------
def check_k002(pf, scope) -> list:
    # NETWORK_DOES_ENTITY_EXIST_WITH_NETWORK_ID is a client-only native (fxref:
    # apiset client), and the "GetNetworkObject: no object by ID" spam it
    # prevents is a client symptom -- so this only applies to client code.
    if pf.side == "server":
        return []
    out = []
    for i, line in enumerate(pf.clean_lines, start=1):
        m = RE_K002_USE.search(line)
        if not m:
            continue
        funcs = _enclosing_functions(pf, i)
        start = funcs[-1].start_line if funcs else 1
        before = pf.range_text(start, i)
        if RE_K002_GUARD.search(before):
            continue
        out.append(Finding(
            pf.rel_path, i, "K002", "warn",
            f"{m.group(1)}(...) without a NetworkDoesEntityExistWithNetworkId() check earlier in this function",
            "guard with `if not NetworkDoesEntityExistWithNetworkId(netId) then return end` -- FiveM logs "
            "'GetNetworkObject: no object by ID' for every id this client does not hold (DESIGN section 30.1)",
        ))
    return out


# ---------------------------------------------------------------------------
# K003 -- prefer core's wrappers over the raw Cfx API (plugin only)
# ---------------------------------------------------------------------------
_K003_HINTS = (
    (RE_K003_EVENT, "RegisterNetEvent/RegisterServerEvent", "Core.Net.on(name, schema, handler, opts)"),
    (RE_K003_CMD, "RegisterCommand", "Core.Commands.register(name, opts, handler)"),
    (RE_K003_TRIGGER, "TriggerServerEvent/TriggerClientEvent", "Core.Net.emit(...) / Core.Net.broadcast(...)"),
    (RE_K003_KEYMAP, "RegisterKeyMapping", "Core.Keys.register({ name, key, description, onPress })"),
)


def check_k003(pf, scope, ctx) -> list:
    if not scope.is_plugin:
        return []
    out = []
    for i, line in enumerate(pf.code_lines, start=1):
        for rx, what, better in _K003_HINTS:
            m = rx.search(line)
            if not m:
                continue
            out.append(Finding(
                pf.rel_path, i, "K003", "info",
                f"raw {what} in a core plugin -- core has a validated wrapper for this",
                f"use {better} (DESIGN section 3.5-3.8); the wrapper adds schema validation, cooldown, "
                "permission and distance checks and is cleaned up with the resource",
            ))
        m = RE_K003_ADD.search(line)
        if m and m.group(1) in getattr(ctx, "net_event_names", set()):
            out.append(Finding(
                pf.rel_path, i, "K003", "info",
                f"AddEventHandler('{m.group(1)}') for a net event -- core plugins use Core.Net.on",
                "Core.Net.on(name, schema, handler, opts) registers and validates the event in one place",
            ))
    return out


# ---------------------------------------------------------------------------
# K004 -- registrations into core belong in Core.onReady (plugin only)
# ---------------------------------------------------------------------------
def check_k004(pf, scope) -> list:
    if not scope.is_plugin:
        return []
    out = []
    for i, line in enumerate(pf.clean_lines, start=1):
        m = RE_REGISTRATION.search(line)
        if not m or not _at_file_scope(pf, i):
            continue
        out.append(Finding(
            pf.rel_path, i, "K004", "warn",
            f"{m.group(1)}(...) at file scope -- core forgets it when core restarts",
            "wrap registrations into core in Core.onReady(function() ... end): it runs once core is up "
            "and again after every core restart (DESIGN section 2.4)",
        ))
    return out


# ---------------------------------------------------------------------------
# K005 -- core's owner registry already cleans up (plugin only)
# ---------------------------------------------------------------------------
def check_k005(pf, scope) -> list:
    if not scope.is_plugin:
        return []
    out = []
    for frame in pf.frames:
        if not frame.is_handler or not frame.handler_name:
            continue
        if "resourcestop" not in frame.handler_name.lower():
            continue
        cleanup = 0
        other = 0
        for ln in range(frame.start_line + 1, _end(pf, frame) + 1):
            text = pf.code(ln)
            for call in RE_K005_CALL.finditer(text):
                name = call.group(0).rstrip("( ").strip()
                if name in ("if", "for", "while", "function", "return", "and", "or", "not", "end", "elseif"):
                    continue
                if RE_K005_CLEANUP.search(text):
                    cleanup += 1
                    break
                if name in ("GetCurrentResourceName", "type", "tostring", "pairs", "ipairs"):
                    continue
                other += 1
                break
        if cleanup and not other:
            out.append(Finding(
                pf.rel_path, frame.start_line, "K005", "info",
                "onResourceStop handler only removes core registrations -- core's owner registry does that already",
                "core's Core.Registry removes every marker/blip/label/interaction/page this resource "
                "registered when it stops (DESIGN section 2.3); the handler can go",
            ))
    return out


# ---------------------------------------------------------------------------
# K006 -- backdrop-filter paints a black box in the CEF (resource level, both)
# ---------------------------------------------------------------------------
def check_k006(resource_dir: Path, scope) -> list:
    if not scope.active or resource_dir is None:
        return []
    ui_dir = resource_dir / "ui"
    if not ui_dir.is_dir():
        return []
    out = []
    for p in sorted(ui_dir.rglob("*")):
        if not p.is_file() or p.suffix not in UI_SUFFIXES:
            continue
        if UI_SKIP_DIRS.intersection(p.relative_to(resource_dir).parts):
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        rel = p.relative_to(resource_dir).as_posix()
        for i, line in enumerate(lines, start=1):
            if RE_K006.search(line):
                out.append(Finding(
                    rel, i, "K006", "error",
                    "backdrop filter in a core UI file -- FiveM's CEF paints the filtered area solid black",
                    "put `data-core-blur` on the panel instead: core draws a live, blurred copy of the game "
                    "frame behind every element carrying it (core README, 'Game blur')",
                ))
    return out


# ---------------------------------------------------------------------------
# K007 -- no Node packages inside a resource (plugin only)
# ---------------------------------------------------------------------------
def check_k007(resource_dir: Path, scope) -> list:
    if not scope.is_plugin or resource_dir is None:
        return []
    out = []
    for rel in ("package.json", "node_modules", "server/package.json", "server/node_modules"):
        p = resource_dir / rel
        if not p.exists():
            continue
        out.append(Finding(
            rel, 1, "K007", "warn",
            f"{rel} inside the resource -- FXServer's Node sandbox cannot read modules behind the "
            "symlinked resource path and its yarn builder would run on every start",
            "UI dependencies belong to the npm workspace next to core (ui/package.json.example is the "
            "template); bundle server-side Node code instead (AGENTS section 3, 'Server files')",
        ))
    return out


# ---------------------------------------------------------------------------
# K008 -- plugins ship no UI files (plugin only)
# ---------------------------------------------------------------------------
def check_k008(resource_dir: Path, manifest, scope) -> list:
    if not scope.is_plugin or manifest is None or getattr(manifest, "path", None) is None:
        return []
    out = []
    mname = manifest.path.name
    if getattr(manifest, "ui_page", None):
        out.append(Finding(
            mname, 1, "K008", "info",
            f"ui_page '{manifest.ui_page}' in a core plugin -- pages are compiled into core's shell",
            "drop ui_page: <plugin>/ui/src/index.js is bundled into core/html when core/ui is built "
            "(DESIGN section 7.4); register it with Core.UI.registerPage(id, opts)",
        ))
    for entry in getattr(manifest, "files", []):
        e = entry.strip().lower()
        if e.startswith("ui/") or e.startswith("html/"):
            out.append(Finding(
                mname, 1, "K008", "info",
                f"files {{ '{entry}' }} in a core plugin -- plugins ship no UI files",
                "remove the entry: players download core/html only; keep files {} for assets the CEF "
                "must fetch from this resource (images, sounds) and for locales/*.json",
            ))
    return out


# ---------------------------------------------------------------------------
# K009 -- the manifest has to wire core in (plugin only)
# ---------------------------------------------------------------------------
def check_k009(resource_dir: Path, manifest, scope, parsed_files: list) -> list:
    if not scope.is_plugin:
        return []
    if not any(RE_USES_CORE.search("\n".join(pf.clean_lines)) for pf in parsed_files):
        return []
    mname = manifest.path.name if (manifest is not None and getattr(manifest, "path", None)) else "fxmanifest.lua"
    deps = [d.strip().lower() for d in getattr(manifest, "dependencies", [])] if manifest else []
    shared = [s.strip() for s in getattr(manifest, "shared_scripts", [])] if manifest else []
    out = []
    if "core" not in deps:
        out.append(Finding(
            mname, 1, "K009", "warn",
            "this resource uses the Core API but fxmanifest.lua has no dependency 'core'",
            "add dependency 'core' so FXServer starts core first (AGENTS section 4)",
        ))
    if CORE_IMPORT not in shared:
        out.append(Finding(
            mname, 1, "K009", "warn",
            f"'{CORE_IMPORT}' is missing from shared_scripts -- there is no Core global without it",
            f"shared_scripts {{ '{CORE_IMPORT}', 'shared/config.lua' }} -- the import has to come first",
        ))
    elif shared[0] != CORE_IMPORT:
        out.append(Finding(
            mname, 1, "K009", "warn",
            f"'{CORE_IMPORT}' is not the first shared_scripts entry (it is #{shared.index(CORE_IMPORT) + 1})",
            f"put '{CORE_IMPORT}' first: every later file needs the Core global at load time",
        ))
    return out


# ---------------------------------------------------------------------------
# K011 -- Core.Locale.t needs its locales shipped (plugin only)
# ---------------------------------------------------------------------------
def check_k011(resource_dir: Path, manifest, scope, parsed_files: list) -> list:
    if not scope.is_plugin:
        return []
    hits = [(pf, i) for pf in parsed_files
            for i, line in enumerate(pf.clean_lines, start=1) if RE_K011_USE.search(line)]
    if not hits:
        return []
    files = [f.strip().lower() for f in getattr(manifest, "files", [])] if manifest else []
    if any(f.startswith("locales/") for f in files):
        return []
    pf, line = hits[0]
    return [Finding(
        pf.rel_path, line, "K011", "warn",
        "Core.Locale.t(...) is used but fxmanifest.lua does not ship locales/*.json",
        "add files { 'locales/*.json' }: Core.Locale.t reads locales/<lang>.json of the CALLING resource "
        "with LoadResourceFile, which only sees files listed in the manifest (DESIGN section 26)",
    )]


# ---------------------------------------------------------------------------
# K012 -- NUI goes through Core.UI (plugin only)
# ---------------------------------------------------------------------------
def check_k012(pf, scope) -> list:
    if not scope.is_plugin:
        return []
    out = []
    for i, line in enumerate(pf.clean_lines, start=1):
        m = RE_K012.search(line)
        if not m:
            continue
        out.append(Finding(
            pf.rel_path, i, "K012", "warn",
            f"{m.group(1)}(...) -- core owns the single CEF page, a plugin never talks to NUI directly",
            "use Core.UI: registerPage/open/close/send/on for pages, Core.UI.notify / textUI / menu / "
            "input / alert / progress for the built-ins (DESIGN section 6.10, section 7.4)",
        ))
    return out


# ---------------------------------------------------------------------------
# K010 / K013 -- resolved against `fxref core resolve --json`
# ---------------------------------------------------------------------------
def check_k010(pf, scope, calls: list) -> list:
    """A proxy-namespace call at file scope of the main chunk (plugin only)."""
    if not scope.is_plugin or scope.resolved is None:
        return []
    out = []
    for line, name in calls:
        entry = scope.resolved.get(name)
        if not entry or not entry.get("found"):
            continue
        matches = entry.get("matches") or []
        if not matches or matches[0].get("access") != "proxy":
            continue
        if not _at_file_scope(pf, line):
            continue
        out.append(Finding(
            pf.rel_path, line, "K010", "info",
            f"{name}(...) at file scope -- proxy calls need a coroutine and a started core",
            "move it into Core.onReady(function() ... end), a thread or an event handler: the call hops "
            "through core's export, which yields and raises while core is not started (DESIGN section 2.2)",
        ))
    return out


def check_k013(pf, scope, calls: list) -> list:
    """`Core.<Ns>.<fn>(` that the core index does not know (both)."""
    if scope.resolved is None:
        return []
    out = []
    for line, name in calls:
        if name in scope.defined_core_names:
            continue
        entry = scope.resolved.get(name)
        if entry is None:
            continue
        if not entry.get("found"):
            out.append(Finding(
                pf.rel_path, line, "K013", "warn",
                f"{name}(...) is not in core's API index -- probably a hallucinated or renamed API",
                f"check it with `fxref core search {name.split('.')[-1]}`; core's public API is "
                "types/core.lua (README 'API cheat sheet')",
            ))
        elif not entry.get("case_exact"):
            canonical = (entry.get("matches") or [{}])[0].get("name", name)
            out.append(Finding(
                pf.rel_path, line, "K013", "warn",
                f"{name}(...) is spelled with the wrong case -- core's API is {canonical}",
                f"Lua is case-sensitive: write {canonical}",
            ))
    return out


# ---------------------------------------------------------------------------
# runners
# ---------------------------------------------------------------------------
def run(pf, scope, ctx) -> list:
    """Per-file K rules. Resource-level ones are in run_resource()."""
    if not scope.active:
        return []
    from . import coreapi

    findings = []
    findings += check_k001(pf, scope)
    findings += check_k002(pf, scope)
    findings += check_k003(pf, scope, ctx)
    findings += check_k004(pf, scope)
    findings += check_k005(pf, scope)
    findings += check_k012(pf, scope)
    if pf.lang == "lua":
        calls = coreapi.find_core_calls(pf.clean_lines)
        findings += check_k010(pf, scope, calls)
        findings += check_k013(pf, scope, calls)
    return [f for f in findings if not pf.is_suppressed(f.line, f.rule)]


def run_resource(resource_dir, manifest, scope, parsed_files: list) -> list:
    """Resource-level K rules (K006-K009, K011)."""
    if not scope.active:
        return []
    findings = []
    findings += check_k006(resource_dir, scope)
    findings += check_k007(resource_dir, scope)
    findings += check_k008(resource_dir, manifest, scope)
    findings += check_k009(resource_dir, manifest, scope, parsed_files)
    findings += check_k011(resource_dir, manifest, scope, parsed_files)
    return findings


def core_call_names(parsed_files: list) -> set:
    """Every `Core.*(` name the resource calls -- one batched resolve per run."""
    from . import coreapi

    names: set = set()
    for pf in parsed_files:
        if pf.lang != "lua":
            continue
        for _line, name in coreapi.find_core_calls(pf.clean_lines):
            names.add(name)
    return names
