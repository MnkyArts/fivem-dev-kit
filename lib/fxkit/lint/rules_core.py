"""K001-K017: conventions of Liam's `core` framework (DESIGN.md section 9.3).

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
    "Core.UI.registerPage", "Core.UI.onRequest",
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
    ".core-ui",
})

# --- UI plugins (core DESIGN section 38) -----------------------------------
# A plugin owns its frontend: `core_ui '<dir>'` + `files { '<dir>/**' }` opt the
# resource in, `<dir>` is a COMMITTED build of `ui/src/index.ts`, and core reads
# `<dir>/manifest.json` and imports the module at runtime. K014/K015 mirror the
# start-up validation of `core/server/ui_plugins.lua` and `core/shared/ui_manifest.lua`.
UI_DIST_DEFAULT = "ui/dist"
UI_ENTRY_SOURCES = ("ui/src/index.ts", "ui/src/index.js")
UI_SOURCE_SUFFIXES = (".vue", ".js", ".ts", ".jsx", ".tsx", ".mjs")
API_VERSION_FALLBACK = 1
MAX_VFS_PATH = 255          # FiveM cuts `resources:/<res>/<path>` at 255 (core DESIGN 38.1)
MAX_CSS, MAX_PRELOAD, MAX_PAGES, MAX_BUILD, MAX_ID, MAX_DIR = 8, 16, 64, 64, 64, 128
RE_UI_PATH = re.compile(r"^[A-Za-z0-9._/-]+$")       # Lua's `^[%w%._%-/]+$`
RE_UI_PLAIN_ID = re.compile(r"^[A-Za-z0-9_-]+$")     # Lua's `^[%w_%-]+$`
RE_API_VERSION = re.compile(r"local\s+API_VERSION\s*(?:<const>)?\s*=\s*(\d+)")

RE_K016_CALL = re.compile(r"(?<![\w.])Core\.UI\.registerPage\s*\(")
RE_K016_OPTION = re.compile(r"(?<![\w.])(script|style)\s*=")
RE_K017_COREUI = re.compile(r"(?<![\w.])(?:window\.CoreUI|CoreUI)\s*[.\[]")
RE_K017_CREATEAPP = re.compile(r"(?<![\w.$])createApp\s*\(")
RE_K017_PARENT = re.compile(r"(?<![\w.])GetParentResourceName\b")
# `fetch('https://<resource>/<cb>')` / `fetch(`https://${GetParentResourceName()}/…`)`:
# a dotless host (or an interpolation) is a NUI callback, not a real URL.
# `https://cfx-nui-<resource>/...` is the opposite: the resource's OWN file host
# (core DESIGN section 38.1), which is exactly how a page fetches an asset its
# `files {}` ships -- never a callback, so it is excluded here.
RE_K017_NUI_FETCH = re.compile(
    r"""fetch\s*\(\s*[`'"]https://(?:\$\{|(?!cfx-nui-)[A-Za-z0-9_-]+/)""")
# whole-line comments in a UI source -- a rule that reads prose reports nonsense
RE_UI_COMMENT_LINE = re.compile(r"^\s*(?://|/\*|\*|<!--)")


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


def _call_text(pf, line: int, col: int, max_lines: int = 60) -> str:
    """The source of one call, from its `(` at `col` to the matching `)`.

    Reads `clean_lines`, so a parenthesis inside a string can never unbalance
    the scan and an option key is always real code.
    """
    depth = 0
    out = []
    for ln in range(line, min(pf.line_count(), line + max_lines) + 1):
        text = pf.clean(ln)
        start = col if ln == line else 0
        for ch in text[start:]:
            out.append(ch)
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth <= 0:
                    return "".join(out)
        out.append("\n")
    return "".join(out)


# --- UI plugins: the pieces K014/K015 share --------------------------------
def _api_version() -> int:
    """core's `UIManifest.API_VERSION` (core DESIGN section 38.4), read from the
    checkout so the kit can never drift from the core it lints against."""
    root = _core_root()
    if root is not None:
        try:
            m = RE_API_VERSION.search((root / "shared" / "ui_manifest.lua").read_text(
                encoding="utf-8", errors="replace"))
            if m:
                return int(m.group(1))
        except (OSError, ValueError):
            pass
    return API_VERSION_FALLBACK


def _strip_trailing_comment(line: str) -> str:
    """Cut a `// ...` tail that is not inside a string literal.

    Cheap single-pass quote tracking, not a JS parser: enough so that a comment
    *mentioning* an API (`usePage()   // was window.CoreUI.usePage`) is not read
    as a use of it, while `'https://x'` keeps its slashes.
    """
    quote = ""
    i, n = 0, len(line)
    while i < n:
        ch = line[i]
        if quote:
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = ""
        elif ch in "'\"`":
            quote = ch
        elif ch == "/" and i + 1 < n and line[i + 1] == "/":
            return line[:i]
        i += 1
    return line


def _glob_prefix(glob: str) -> str:
    """Everything before the first `*`: the literal part of a manifest glob."""
    star = glob.find("*")
    return glob[:star] if star >= 0 else glob


def _glob_covers(glob: str, directory: str) -> bool:
    """Does `glob` reach into `directory`? `core/server/ui_plugins.lua`'s
    globCovers: compared both ways, because 'ui/dist/**' has the prefix
    'ui/dist/' while the folder itself is 'ui/dist'."""
    prefix = _glob_prefix(glob.strip())
    if prefix == "":
        return True
    return directory.startswith(prefix) or prefix.startswith(directory)


def _dir_ok(value) -> bool:
    """`UIManifest.dirOk`: a relative folder inside the resource. An absolute URL
    or a traversal would let a plugin point the CEF at an arbitrary origin."""
    return (isinstance(value, str) and value != "" and len(value) <= MAX_DIR
            and RE_UI_PATH.match(value) is not None
            and ".." not in value
            and not value.startswith("/") and not value.endswith("/")
            and "://" not in value)


def _path_problem(path, suffixes: tuple, label: str, prefix: str):
    """`UIManifest.pathProblem` + the 255-char vfs budget, or None when fine."""
    if not isinstance(path, str) or path == "":
        return f"{label} must be a string"
    if len(path) > MAX_VFS_PATH or RE_UI_PATH.match(path) is None:
        return f"{label} '{path}' is not a relative path of [A-Za-z0-9._-/]"
    if ".." in path or path.startswith("/"):
        return f"{label} '{path}' must not be absolute or contain '..'"
    if not path.endswith(suffixes):
        return f"{label} '{path}' does not end in {' or '.join(suffixes)}"
    if len(prefix + path) >= MAX_VFS_PATH:
        return f"'{path}' is longer than {MAX_VFS_PATH} characters inside the CEF"
    return None


def _read_paths(value, label: str, suffixes: tuple, maximum: int, prefix: str):
    """An optional array of shippable paths -> (list, problem)."""
    if value is None:
        return [], None
    if not isinstance(value, list):
        return None, f"'{label}' must be an array"
    if len(value) > maximum:
        return None, f"'{label}' has more than {maximum} entries"
    for i, entry in enumerate(value, start=1):
        problem = _path_problem(entry, suffixes, f"'{label}[{i}]'", prefix)
        if problem:
            return None, problem
    return list(value), None


def validate_ui_manifest(resource: str, data, directory: str) -> tuple:
    """Port of `UIManifest.validate` (core `shared/ui_manifest.lua`, DESIGN
    section 38.4). Returns (problems, wanted_files): every rule the game applies
    at start-up, in the same order and with the same wording, plus the files
    `manifest.json` promises are on disk."""
    problems: list = []
    if not isinstance(data, dict):
        return ["manifest.json is not a JSON object"], []
    if data.get("id") != resource:
        problems.append(f"'id' must be the resource name ('{resource}'), got {data.get('id')!r}")
    api = data.get("apiVersion")
    expected = _api_version()
    if not isinstance(api, int) or isinstance(api, bool):
        problems.append(f"'apiVersion' must be an integer, got {api!r}")
    elif api != expected:
        problems.append(f"{resource} was built for core UI API {api}, this core provides {expected} "
                        "-- rebuild the plugin with this core's @core/ui or update core")

    prefix = f"resources:/{resource}/{directory + '/' if directory else ''}"
    wanted: list = []
    problem = _path_problem(data.get("entry"), (".js", ".mjs"), "'entry'", prefix)
    if problem:
        problems.append(problem)
    else:
        wanted.append(data["entry"])

    css, problem = _read_paths(data.get("css"), "css", (".css",), MAX_CSS, prefix)
    if problem:
        problems.append(problem)
    else:
        wanted.extend(css)
    _preload, problem = _read_paths(data.get("preload"), "preload", (".js", ".mjs"), MAX_PRELOAD, prefix)
    if problem:
        problems.append(problem)

    build = data.get("build")
    if build is not None and (not isinstance(build, str) or len(build) > MAX_BUILD):
        problems.append(f"'build' must be a string of at most {MAX_BUILD} characters")
    load = data.get("load", "eager")
    if load not in ("eager", "lazy"):
        problems.append(f"'load' must be 'eager' or 'lazy', got {load!r}")

    pages = data.get("pages")
    if pages is not None:
        if not isinstance(pages, list):
            problems.append("'pages' must be an array")
        elif len(pages) > MAX_PAGES:
            problems.append(f"'pages' has more than {MAX_PAGES} entries")
        else:
            for i, page in enumerate(pages, start=1):
                if (not isinstance(page, str) or not 1 <= len(page) <= MAX_ID
                        or RE_UI_PLAIN_ID.match(page) is None):
                    problems.append(f"'pages[{i}]' is not a plain id ({page!r})")
    return problems, wanted


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
            "UI dependencies belong in <plugin>/ui/package.json, a member of the npm workspace next to "
            "core (never 'vue': the shell hands the plugin its one Vue at runtime); bundle server-side "
            "Node code instead (AGENTS section 3, 'Server files')",
        ))
    return out


# ---------------------------------------------------------------------------
# K008 -- a core plugin never owns a NUI page (plugin only)
# ---------------------------------------------------------------------------
def check_k008(resource_dir: Path, manifest, scope) -> list:
    if not scope.is_plugin or manifest is None or getattr(manifest, "path", None) is None:
        return []
    if not getattr(manifest, "ui_page", None):
        return []
    return [Finding(
        manifest.path.name, 1, "K008", "warn",
        f"ui_page '{manifest.ui_page}' in a core plugin -- core owns the one CEF page, one Vue, "
        "one kit and one focus stack",
        "drop ui_page and ship a UI plugin instead (DESIGN section 38): core_ui 'ui/dist' + "
        "files { 'ui/dist/**' } in the manifest, ui/src/index.ts default-exporting "
        "defineUIPlugin({ pages, setup }), built with `npm run build` in ui/ -- core imports it at "
        "runtime and Core.UI.registerPage(id, { type = ... }) stays the authority on the page id",
    )]


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
            "use Core.UI: registerPage/open/close/send/on for pages, update/patch/feed for their state, "
            "Core.UI.onRequest for the page's nui.invoke, and notify / textUI / menu / input / alert / "
            "progress for the built-ins; focus is a stack core alone owns -- a plugin that calls "
            "SetNuiFocus fights it (DESIGN section 38.8, section 38.9)",
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
# K014 -- the UI-plugin manifest wiring (plugin only, resource level)
# ---------------------------------------------------------------------------
def check_k014(resource_dir: Path, manifest, scope) -> list:
    if not scope.is_plugin or resource_dir is None:
        return []
    if manifest is None or getattr(manifest, "path", None) is None:
        return []
    mname = manifest.path.name
    files = [f.strip() for f in getattr(manifest, "files", []) if f and f.strip()]
    client = [s.strip() for s in getattr(manifest, "client_scripts", []) if s and s.strip()]
    directory = getattr(manifest, "core_ui", None)
    out = []

    if directory is None:
        # The reverse wiring errors: something IS built, or something is there to
        # build, but core never learns about it (it only probes resources with the key).
        if (resource_dir / UI_DIST_DEFAULT / "manifest.json").is_file():
            out.append(Finding(
                mname, 1, "K014", "warn",
                f"{UI_DIST_DEFAULT}/manifest.json is built but the manifest has no core_ui line -- "
                "core never probes this resource",
                f"add core_ui '{UI_DIST_DEFAULT}' and files {{ '{UI_DIST_DEFAULT}/**' }}: the metadata "
                "key is the whole opt-in core reads with GetResourceMetadata (DESIGN section 38.4)",
            ))
        elif any((resource_dir / rel).is_file() for rel in UI_ENTRY_SOURCES):
            out.append(Finding(
                mname, 1, "K014", "warn",
                "ui/src is a UI plugin entry but the manifest has neither core_ui nor a built "
                f"{UI_DIST_DEFAULT} -- the page can never load",
                f"build it (`npm run build` in ui/) and add core_ui '{UI_DIST_DEFAULT}' + "
                f"files {{ '{UI_DIST_DEFAULT}/**' }} (DESIGN section 38.3)",
            ))
        return out

    if not _dir_ok(directory):
        # Everything below reads `<dir>`; with a broken one there is nothing to say.
        return [Finding(
            mname, 1, "K014", "error",
            f"core_ui '{directory}' is not a relative folder inside the resource",
            "core_ui names a folder of THIS resource (charset [A-Za-z0-9._-/], no '..', no leading or "
            "trailing '/', no '://') -- core_ui 'ui/dist'; an absolute URL would point the CEF at a "
            "foreign origin (DESIGN section 38.4)",
        )]

    if not any(_glob_covers(f, directory) for f in files):
        out.append(Finding(
            mname, 1, "K014", "error",
            f"core_ui '{directory}' but no files {{}} entry covers it -- the client cannot download "
            "the plugin and the CEF gets a 404",
            f"add files {{ '{directory}/**' }}: only files packed for the client are reachable under "
            "https://cfx-nui-<resource>/ (DESIGN section 38.1)",
        ))

    for entry in files:
        prefix = _glob_prefix(entry)
        if prefix.startswith(directory):
            continue
        if prefix == "" or prefix == "ui" or prefix.startswith("ui/"):
            out.append(Finding(
                mname, 1, "K014", "warn",
                f"files {{ '{entry}' }} ships more of ui/ than the build -- sources, the dev host and "
                "the build caches go to every player",
                f"list '{directory}/**' only: ui/src, ui/dev and ui/.core-ui are developer files, and "
                "the CEF never fetches them (DESIGN section 38.3)",
            ))

    for glob in client:
        # a glob that can only ever match .lua never reaches a dist of js/css/json,
        # and `client_scripts { '**/*.lua' }` is an ordinary, harmless manifest
        if not glob.endswith(".lua") and _glob_covers(glob, directory):
            out.append(Finding(
                mname, 1, "K014", "warn",
                f"client_script '{glob}' overlaps '{directory}' -- FiveM serves a client_script that is "
                "not also a file as gameconfig.xml",
                f"narrow the glob so it stays out of {directory} (client/*.lua, or name the files one "
                "by one) -- core's server-side check prints the same warning at start-up "
                "(DESIGN section 38.1, section 38.4)",
            ))
    return out


# ---------------------------------------------------------------------------
# K015 -- the built UI plugin (plugin only, resource level)
# ---------------------------------------------------------------------------
def check_k015(resource_dir: Path, manifest, scope) -> list:
    if not scope.is_plugin or resource_dir is None or manifest is None:
        return []
    directory = getattr(manifest, "core_ui", None)
    if not directory or not _dir_ok(directory):
        return []                       # K014 already reported the wiring
    resource = resource_dir.name
    mname = manifest.path.name if getattr(manifest, "path", None) else "fxmanifest.lua"
    rel = f"{directory}/manifest.json"
    built = resource_dir / directory / "manifest.json"
    sources = [resource_dir / r for r in UI_ENTRY_SOURCES]
    entry_src = next((p for p in sources if p.is_file()), None)
    out = []

    if not built.is_file():
        if entry_src is not None:
            # The normal state right after `fxnew`/`new-plugin.sh`: sources are there,
            # the build has not run yet. Info, not warn -- a fresh scaffold lints 0/0.
            out.append(Finding(
                entry_src.relative_to(resource_dir).as_posix(), 1, "K015", "info",
                f"core_ui '{directory}' but nothing is built there yet",
                f"npm run build -w {resource}-ui (from the resources folder, after one `npm install` "
                f"there) writes {directory}; it is committed like core/html because that is what "
                "players download (DESIGN section 38.3)",
            ))
        else:
            out.append(Finding(
                mname, 1, "K015", "warn",
                f"core_ui '{directory}' but there is neither a build nor a ui/src entry to build it "
                "from -- core logs a loud error for this resource on every start",
                "either ship the plugin's frontend (ui/src/index.ts + `npm run build` in ui/) or drop "
                "the core_ui line (DESIGN section 38.4)",
            ))
        return out

    try:
        data = json.loads(built.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError) as exc:
        return [Finding(
            rel, 1, "K015", "error",
            f"{rel} is not valid JSON ({exc})",
            f"it is generated -- never hand-edit it; npm run build -w {resource}-ui writes it "
            "(DESIGN section 38.13)",
        )]

    problems, wanted = validate_ui_manifest(resource, data, directory)
    for problem in problems:
        out.append(Finding(
            rel, 1, "K015", "error", problem,
            "core runs this exact validator on the client (discovery) and on the server (start-up): "
            "a rejected manifest means the plugin never loads (DESIGN section 38.4)",
        ))
    for name in wanted:
        if not (resource_dir / directory / name).is_file():
            out.append(Finding(
                rel, 1, "K015", "error",
                f"{directory}/{name} is listed in manifest.json but is not on disk",
                f"rebuild the plugin (npm run build -w {resource}-ui) -- the output is content-hashed, "
                "so a stale manifest points at a URL that 404s",
            ))

    if entry_src is not None:
        try:
            newest = max((p.stat().st_mtime for p in (resource_dir / "ui" / "src").rglob("*")
                          if p.is_file()), default=0.0)
            # 2 s of slack: a checkout can give dist and src near-identical mtimes
            if newest > built.stat().st_mtime + 2:
                out.append(Finding(
                    rel, 1, "K015", "info",
                    f"{directory} is older than ui/src -- the committed build does not match the sources",
                    f"npm run build -w {resource}-ui, then restart {resource}: the browser pins a module "
                    "by URL, so only a new hash runs new code (DESIGN section 38.1)",
                ))
        except OSError:
            pass
        try:
            if "defineUIPlugin" not in entry_src.read_text(encoding="utf-8", errors="replace"):
                out.append(Finding(
                    entry_src.relative_to(resource_dir).as_posix(), 1, "K015", "warn",
                    "the UI plugin entry has no defineUIPlugin(...) -- the shell rejects the module",
                    "export default defineUIPlugin({ pages, setup }) from '@core/ui'; module scope is "
                    "for definitions only, every side effect belongs in setup(ctx) "
                    "(DESIGN section 38.2, section 38.7)",
                ))
        except OSError:
            pass
    return out


# ---------------------------------------------------------------------------
# K016 -- registerPage { script, style } was removed with section 38 (plugin only)
# ---------------------------------------------------------------------------
def check_k016(pf, scope) -> list:
    if not scope.is_plugin or pf.lang != "lua":
        return []
    out = []
    for i, line in enumerate(pf.clean_lines, start=1):
        for m in RE_K016_CALL.finditer(line):
            option = RE_K016_OPTION.search(_call_text(pf, i, m.end() - 1))
            if not option:
                continue
            out.append(Finding(
                pf.rel_path, i, "K016", "error",
                f"Core.UI.registerPage(..., {{ {option.group(1)} = ... }}) -- the option was removed "
                "with the runtime UI platform and the registration fails",
                "a page's code is no longer a URL core loads: the resource ships its own frontend "
                "(core_ui 'ui/dist' + files { 'ui/dist/**' }) and registerPage only declares the id, "
                "its type ('page' | 'overlay' | 'modal') and its owner (DESIGN section 38.16)",
            ))
            break
    return out


# ---------------------------------------------------------------------------
# K017 -- the plugin's own UI sources (plugin only, resource level)
# ---------------------------------------------------------------------------
def check_k017(resource_dir: Path, scope) -> list:
    if not scope.is_plugin or resource_dir is None:
        return []
    src = resource_dir / "ui" / "src"
    if not src.is_dir():
        return []
    out = []
    for p in sorted(src.rglob("*")):
        if not p.is_file() or p.suffix not in UI_SOURCE_SUFFIXES:
            continue
        rel = p.relative_to(resource_dir)
        if UI_SKIP_DIRS.intersection(rel.parts) or "dev" in rel.parts:
            continue
        try:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        name = rel.as_posix()
        for i, raw in enumerate(lines, start=1):
            if RE_UI_COMMENT_LINE.match(raw):
                continue        # prose about CoreUI is not a use of it
            line = _strip_trailing_comment(raw)      # nor is a trailing `// ...`
            if RE_K017_COREUI.search(line):
                out.append(Finding(
                    name, i, "K017", "info",
                    "window.CoreUI in a plugin page -- that is the legacy surface core keeps for its "
                    "own tests and stories",
                    "import from '@core/ui' instead (usePage, useNui, useScope, useFeed, useHud, t, "
                    "notify): everything it hands out is tied to the page or plugin scope and is "
                    "disposed with it, while a CoreUI.on at module scope is never cleaned up "
                    "(DESIGN section 38.7, section 38.12)",
                ))
            if RE_K017_CREATEAPP.search(line):
                out.append(Finding(
                    name, i, "K017", "warn",
                    "createApp(...) in a plugin page -- there is exactly one Vue app, core's",
                    "export the component through defineUIPlugin({ pages }) and let the shell mount "
                    "it; the kit tags resolve against core's app at render time, so a second app "
                    "would have neither them nor the focus stack (DESIGN section 38.3)",
                ))
            if RE_K017_PARENT.search(line) or RE_K017_NUI_FETCH.search(line):
                out.append(Finding(
                    name, i, "K017", "warn",
                    "a NUI-callback fetch in a plugin page -- a plugin resource has no NUI callbacks; "
                    "its page lives inside core's frame",
                    "talk to Lua through the SDK: nui.emit / page.emit (fire and forget) and "
                    "nui.invoke(name, data) answered by Core.UI.onRequest(name, fn) "
                    "(DESIGN section 38.8)",
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
    findings += check_k016(pf, scope)
    if pf.lang == "lua":
        calls = coreapi.find_core_calls(pf.clean_lines)
        findings += check_k010(pf, scope, calls)
        findings += check_k013(pf, scope, calls)
    return [f for f in findings if not pf.is_suppressed(f.line, f.rule)]


def run_resource(resource_dir, manifest, scope, parsed_files: list) -> list:
    """Resource-level K rules (K006-K009, K011, K014, K015, K017)."""
    if not scope.active:
        return []
    findings = []
    findings += check_k006(resource_dir, scope)
    findings += check_k007(resource_dir, scope)
    findings += check_k008(resource_dir, manifest, scope)
    findings += check_k009(resource_dir, manifest, scope, parsed_files)
    findings += check_k011(resource_dir, manifest, scope, parsed_files)
    findings += check_k014(resource_dir, manifest, scope)
    findings += check_k015(resource_dir, manifest, scope)
    findings += check_k017(resource_dir, scope)
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
