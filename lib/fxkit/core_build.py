"""Parser for `core/types/core.lua` -- the LuaLS (`---@meta`) definition file
that documents Liam's `core` framework (DESIGN.md section 9.2).

Everything in here is a pure function over text: `parse_types(text)` turns the
definition file into `ParsedApi` (functions, classes, aliases, hooks,
namespaces) and `build_rows(...)` turns that into the dict rows `fxref core
build` inserts into `core_api`. Nothing touches the filesystem except the two
thin `read_*` helpers at the bottom, so the parser is unit-testable against a
small inline sample.

What the file looks like (see core/types/core.lua):

    ---@class CoreMarkerOptions
    ---@field coords vector3 required world position
    ---@field type? integer marker type (default 1)

    ---@alias CoreMoneyAccount '"cash"' | '"bank"' | string

    ---@alias CoreHook
    ---| '"ready"'   # core started on this side -- server: () / client: ()

    ---@class Core.Money
    Core.Money = {}

    ---(server) Adds a positive amount; false when it would pass the cap.
    ---@param src integer
    ---@param amount integer > 0
    ---@return boolean ok
    function Core.Money.add(src, account, amount, reason) end

Sub-namespaces are written as a local table with the dotted class name above
it (`---@class Core.UI.menu` / `local CoreUIMenu = {}` / `function
CoreUIMenu.open(...) end`), so the local variable name has to be mapped back
to the dotted namespace before a function name can be built.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# --- LuaLS line shapes ------------------------------------------------------
RE_CLASS = re.compile(r"^---@class\s+([A-Za-z_][\w.]*)")
RE_ALIAS = re.compile(r"^---@alias\s+([A-Za-z_][\w.]*)\s*(.*)$")
RE_ALIAS_VALUE = re.compile(r"^---\|\s*(.*)$")
RE_FIELD = re.compile(r"^---@field\s+([A-Za-z_][\w]*)(\??)\s+(.*)$")
RE_PARAM = re.compile(r"^---@param\s+([A-Za-z_][\w]*|\.\.\.)(\??)\s*(.*)$")
RE_RETURN = re.compile(r"^---@return\s+(.*)$")
RE_OVERLOAD = re.compile(r"^---@overload\s+(.*)$")
RE_GENERIC = re.compile(r"^---@generic\b")
RE_DOC = re.compile(r"^---(?!@|\|)\s?(.*)$")
RE_FUNCTION = re.compile(r"^function\s+([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*\(([^)]*)\)\s*end")
RE_NS_ASSIGN = re.compile(r"^(?:local\s+)?([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*)\s*=\s*\{\s*\}")
RE_SIDE_MARK = re.compile(r"\((server|client)\)|(?<![\w])(server|client)\s*:")
RE_QUOTED = re.compile(r"'\"([^\"]*)\"'|\"([^\"]*)\"|'([^']*)'")

# `Core.UI.progress` is declared as a class carrying only `---@overload`
# entries (the namespace itself is callable), so the sub-namespace table is
# never empty even when it declares no member functions.
LIB_MODULES_FALLBACK = (
    "Utils", "Math", "Validate", "Log", "Callback", "Net", "Commands", "Keys",
    "Streaming", "Anim", "Player", "UI", "Locale", "Audio",
)
SUB_NAMESPACES_FALLBACK = {
    "UI": ("menu", "input", "alert", "progress", "textUI", "hud", "keys",
           "spinner", "stats", "state", "locale"),
}


@dataclass
class CoreFunction:
    name: str                      # 'Core.Money.add'
    namespace: str                 # 'Money' (top level, '' for bare Core.*)
    sub: str = ""                  # 'menu' for Core.UI.menu.open
    short: str = ""                # 'add'
    args: list = field(default_factory=list)      # declared argument names
    params: list = field(default_factory=list)    # [{name, optional, type, description}]
    returns: list = field(default_factory=list)   # [{type, name, description}]
    overloads: list = field(default_factory=list)
    description: str = ""
    side: str = "shared"
    line: int = 0
    section: str = ""


@dataclass
class CoreClass:
    name: str
    fields: list = field(default_factory=list)    # [{name, optional, type, description}]
    description: str = ""
    line: int = 0
    is_namespace: bool = False
    section: str = ""
    overloads: list = field(default_factory=list)


@dataclass
class CoreAlias:
    name: str
    values: list = field(default_factory=list)    # [{value, description}]
    description: str = ""
    line: int = 0


@dataclass
class ParsedApi:
    functions: list = field(default_factory=list)
    classes: list = field(default_factory=list)
    aliases: list = field(default_factory=list)
    namespaces: dict = field(default_factory=dict)   # 'Money' -> description
    warnings: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# type expressions
# ---------------------------------------------------------------------------
_OPEN = {"(": ")", "[": "]", "{": "}", "<": ">"}
_CLOSE = {v: k for k, v in _OPEN.items()}


def _scan_atom(text: str, i: int) -> int:
    """End offset of one type atom starting at `text[i]` (no leading space).

    An atom is a balanced `{...}` / `(...)` group or a bare identifier that may
    carry balanced `<...>`/`(...)`/`[]` suffixes -- i.e. everything up to the
    first top-level whitespace.
    """
    n = len(text)
    depth = 0
    while i < n:
        ch = text[i]
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            if depth == 0:
                break
            depth -= 1
        elif ch.isspace() and depth == 0:
            break
        elif ch in ",:" and depth == 0:
            break
        i += 1
    return i


def split_type_and_desc(text: str) -> tuple[str, str]:
    """Split `'CoreMenuOptions|integer client: the options'` into the type
    expression and the trailing human description.

    Union members separated by `|` (with or without spaces) stay part of the
    type, and a `fun(...)` atom swallows a following `: <type>` return.
    """
    s = text.strip()
    if not s:
        return "", ""
    i = _scan_atom(s, 0)
    while i < len(s):
        j = i
        while j < len(s) and s[j].isspace():
            j += 1
        if j < len(s) and s[j] == "|":
            j += 1
            while j < len(s) and s[j].isspace():
                j += 1
            i = _scan_atom(s, j)
            continue
        if j < len(s) and s[j] == ":" and s[:i].rstrip().endswith(")"):
            j += 1
            while j < len(s) and s[j].isspace():
                j += 1
            i = _scan_atom(s, j)
            continue
        break
    return s[:i].strip(), s[i:].strip()


def _parse_alias_values(text: str) -> list[dict]:
    """`'"cash"' | '"bank"' | string` or `'"ready"'  # core started` -> values."""
    body, _, comment = text.partition("#")
    comment = comment.strip()
    out: list[dict] = []
    depth = 0
    buf: list[str] = []
    parts: list[str] = []
    for ch in body:
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE and depth:
            depth -= 1
        if ch == "|" and depth == 0:
            parts.append("".join(buf))
            buf = []
            continue
        buf.append(ch)
    parts.append("".join(buf))
    for raw in parts:
        piece = raw.strip()
        if not piece:
            continue
        m = RE_QUOTED.fullmatch(piece)
        value = next((g for g in m.groups() if g is not None), piece) if m else piece
        out.append({"value": value, "description": comment, "quoted": bool(m)})
    return out


def _name_and_desc(rest: str) -> tuple[str, str]:
    """Split a `@return`/`@param` remainder into an optional identifier and the
    description. `'ok'` -> ('ok', ''), `'value the picked item'` -> ('value',
    'the picked item'), `'true when v is an integer'` -> ('', 'true when ...')."""
    rest = rest.strip()
    if rest.startswith("#"):
        return "", rest[1:].strip()
    m = re.match(r"^([A-Za-z_]\w*)\??(\s+|$)(.*)$", rest, re.DOTALL)
    if not m:
        return "", rest
    word, tail = m.group(1), m.group(3).strip()
    if word.lower() in _NOT_A_NAME:
        return "", rest
    return word, tail


# English words that start a `@return <type> <description>` line where the
# author did not name the value -- taking them as the return's name would print
# nonsense like `-> boolean true` in a signature.
_NOT_A_NAME = frozenset({
    "true", "false", "nil", "the", "a", "an", "this", "that", "whether", "when",
    "how", "same", "always", "never", "all", "one", "its", "it", "and", "or",
    "each", "every", "new", "current", "number", "list", "set", "copy", "value's",
})


class _Block:
    """The contiguous `---` comment block above a declaration."""

    def __init__(self, line: int) -> None:
        self.line = line
        self.doc: list[str] = []
        self.params: list[dict] = []
        self.returns: list[dict] = []
        self.overloads: list[str] = []
        self.fields: list[dict] = []
        self.class_name: Optional[str] = None
        self.class_line: int = line
        self.class_doc: list[str] = []
        self.last: Optional[dict] = None   # tag whose description continues

    def description(self) -> str:
        return "\n".join(self.doc).strip()


def _side_of(text: str) -> str:
    """`(server)` / `(client)` / `server:` / `client:` markers in a description.
    Both (or neither) -> 'shared'."""
    sides = set()
    for m in RE_SIDE_MARK.finditer(text or ""):
        sides.add(m.group(1) or m.group(2))
    if len(sides) == 1:
        return sides.pop()
    return "shared"


def _split_ns(dotted: str) -> tuple[str, str, str]:
    """'Core.UI.menu.open' -> ('UI', 'menu', 'open'); 'Core.on' -> ('Core', '', 'on')."""
    parts = dotted.split(".")
    if parts and parts[0] == "Core":
        parts = parts[1:]
    if len(parts) == 1:
        return "Core", "", parts[0]
    if len(parts) == 2:
        return parts[0], "", parts[1]
    return parts[0], ".".join(parts[1:-1]), parts[-1]


def parse_types(text: str) -> ParsedApi:
    """Parse a LuaLS `---@meta` definition file into a ParsedApi."""
    api = ParsedApi()
    lines = text.splitlines()
    var_to_class: dict[str, str] = {}   # 'CoreUIMenu' -> 'Core.UI.menu'
    block: Optional[_Block] = None
    section = ""   # last `-- Core.Money (server/money.lua §4.3) ...` banner comment

    def flush_class(b: Optional[_Block], assigned_to: str = "") -> None:
        """Emit the class the block declares (if any)."""
        if b is None or not b.class_name:
            return
        name = b.class_name
        is_ns = "." in name and name.split(".")[0] == "Core"
        api.classes.append(CoreClass(
            name=name, fields=list(b.fields),
            description="\n".join(b.class_doc).strip(),
            line=b.class_line, is_namespace=is_ns, section=section,
            overloads=list(b.overloads),
        ))
        if is_ns or name == "Core":
            ns_key = name[len("Core."):] if name.startswith("Core.") else "Core"
            api.namespaces.setdefault(ns_key, "\n".join(b.class_doc).strip())
        if assigned_to:
            var_to_class[assigned_to] = name
        b.class_name = None
        b.fields = []
        b.class_doc = []

    def flush(b: Optional[_Block]) -> None:
        flush_class(b)

    for idx, raw in enumerate(lines, start=1):
        line = raw.rstrip()
        stripped = line.strip()

        if stripped.startswith("---"):
            if block is None:
                block = _Block(idx)
            m = RE_CLASS.match(stripped)
            if m:
                flush_class(block)
                block.class_name = m.group(1)
                block.class_line = idx
                block.class_doc = list(block.doc)
                block.doc = []
                block.last = None
                continue
            m = RE_ALIAS.match(stripped)
            if m:
                flush_class(block)
                alias = CoreAlias(name=m.group(1), description=block.description(), line=idx)
                if m.group(2).strip():
                    alias.values.extend(_parse_alias_values(m.group(2)))
                api.aliases.append(alias)
                block.doc = []
                block.last = None
                block._alias = alias  # type: ignore[attr-defined]
                continue
            m = RE_ALIAS_VALUE.match(stripped)
            if m:
                alias = getattr(block, "_alias", None)
                if alias is not None:
                    alias.values.extend(_parse_alias_values(m.group(1)))
                continue
            m = RE_FIELD.match(stripped)
            if m:
                ftype, fdesc = split_type_and_desc(m.group(3))
                entry = {"name": m.group(1), "optional": m.group(2) == "?",
                          "type": ftype, "description": fdesc}
                block.fields.append(entry)
                block.last = entry
                continue
            m = RE_PARAM.match(stripped)
            if m:
                ptype, pdesc = split_type_and_desc(m.group(3))
                entry = {"name": m.group(1), "optional": m.group(2) == "?",
                          "type": ptype, "description": pdesc}
                block.params.append(entry)
                block.last = entry
                continue
            m = RE_RETURN.match(stripped)
            if m:
                rtype, rest = split_type_and_desc(m.group(1))
                rname, rdesc = _name_and_desc(rest)
                entry = {"type": rtype, "name": rname, "description": rdesc}
                block.returns.append(entry)
                block.last = entry
                continue
            m = RE_OVERLOAD.match(stripped)
            if m:
                block.overloads.append(m.group(1).strip())
                block.last = None
                continue
            if RE_GENERIC.match(stripped):
                block.last = None
                continue
            m = RE_DOC.match(stripped)
            if m:
                cont = m.group(1).strip()
                if block.last is not None and cont:
                    block.last["description"] = (block.last["description"] + " " + cont).strip()
                elif block.class_name and not block.fields and not cont:
                    pass
                else:
                    block.doc.append(cont)
                continue
            continue

        m = RE_FUNCTION.match(stripped)
        if m:
            dotted = m.group(1)
            owner, _, short = dotted.rpartition(".")
            if owner in var_to_class:
                dotted = var_to_class[owner] + "." + short
            ns, sub, short = _split_ns(dotted)
            b = block or _Block(idx)
            desc = b.description()
            side_text = desc + "\n" + "\n".join(b.overloads)
            args = [a.strip() for a in m.group(2).split(",") if a.strip()]
            api.functions.append(CoreFunction(
                name=dotted, namespace=ns, sub=sub, short=short, args=args,
                params=list(b.params), returns=list(b.returns),
                overloads=list(b.overloads), description=desc,
                side=_side_of(side_text), line=idx, section=section,
            ))
            flush(block)
            block = None
            continue

        m = RE_NS_ASSIGN.match(stripped)
        if m:
            flush_class(block, assigned_to=m.group(1))
            block = None
            continue

        if stripped.startswith("--") and len(stripped) > 4 and set(stripped) != {"-"}:
            section = stripped.lstrip("-").strip()
        flush(block)
        block = None

    flush(block)
    return api


# ---------------------------------------------------------------------------
# lib vs proxy (core/import.lua + core/lib/**)
# ---------------------------------------------------------------------------
RE_LIB_TABLE = re.compile(r"local\s+LIB_MODULES\s*(?:<const>)?\s*=\s*\{(.*?)\}", re.DOTALL)
RE_SUB_TABLE = re.compile(r"local\s+SUB_NAMESPACES\s*(?:<const>)?\s*=\s*\{(.*?)\n\}", re.DOTALL)
RE_LIB_ENTRY = re.compile(r"([A-Za-z_]\w*)\s*=\s*'([^']*)'")
RE_SUB_ENTRY = re.compile(r"([A-Za-z_]\w*)\s*=\s*\{([^}]*)\}")
RE_SUB_KEY = re.compile(r"([A-Za-z_]\w*)\s*=\s*true")
RE_LIB_FN = re.compile(r"\bfunction\s+ns\.([A-Za-z_]\w*)\s*\(")


def parse_import(text: str) -> tuple[dict, dict]:
    """LIB_MODULES / SUB_NAMESPACES out of core/import.lua.

    Returns ({'Utils': 'utils', ...}, {'UI': {'menu', 'input', ...}}). Falls
    back to the constants at the top of this module when the tables cannot be
    found, so a refactor of import.lua degrades instead of breaking the index.
    """
    libs: dict[str, str] = {}
    subs: dict[str, set] = {}
    m = RE_LIB_TABLE.search(text or "")
    if m:
        libs = {k: v for k, v in RE_LIB_ENTRY.findall(m.group(1))}
    m = RE_SUB_TABLE.search(text or "")
    if m:
        for ns, body in RE_SUB_ENTRY.findall(m.group(1)):
            subs[ns] = set(RE_SUB_KEY.findall(body))
    if not libs:
        libs = {n: n.lower() for n in LIB_MODULES_FALLBACK}
    if not subs:
        subs = {k: set(v) for k, v in SUB_NAMESPACES_FALLBACK.items()}
    return libs, subs


def scan_lib_functions(core_root: Path, libs: dict) -> dict:
    """{'Utils': {'clamp': {'shared'}}, 'UI': {'on': {'client'}}, ...}.

    A lib namespace is only in-VM for the functions its `lib/<dir>/*.lua` files
    actually define -- import.lua puts the export proxy behind everything else
    (`attachProxy`), so e.g. server-side `Core.Player.getInfo` is a proxy call
    even though `Player` is a LIB_MODULE.
    """
    out: dict[str, dict] = {}
    for ns, directory in (libs or {}).items():
        found: dict[str, set] = {}
        base = core_root / "lib" / str(directory)
        if not base.is_dir():
            continue
        for fname, side in (("shared.lua", "shared"), ("client.lua", "client"), ("server.lua", "server")):
            f = base / fname
            if not f.is_file():
                continue
            try:
                body = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for name in RE_LIB_FN.findall(body):
                found.setdefault(name, set()).add(side)
        if found:
            out[ns] = found
    return out


def access_for(fn: CoreFunction, lib_index: dict, subs: dict) -> str:
    """'lib' (compiled into the caller's VM) or 'proxy' (export hop)."""
    if fn.namespace == "Core":
        return "lib"          # Core.on/onReady/... come from import.lua itself
    if fn.sub:
        return "proxy"        # SUB_NAMESPACES are always call('UI', 'menu.open')
    defined = (lib_index.get(fn.namespace) or {}).get(fn.short)
    if not defined:
        return "proxy"
    if "shared" in defined or fn.side in defined:
        return "lib"
    if fn.side == "shared" and defined:
        return "lib"
    return "proxy"


# ---------------------------------------------------------------------------
# rows
# ---------------------------------------------------------------------------
RE_DESIGN_REF = re.compile(r"§\s*\d+(?:\.\d+)*")


def design_ref(*texts: str) -> str:
    seen: list[str] = []
    for t in texts:
        for m in RE_DESIGN_REF.finditer(t or ""):
            ref = m.group(0).replace(" ", "")
            if ref not in seen:
                seen.append(ref)
    return "DESIGN " + ", ".join(seen) if seen else ""


def signature_for(fn: CoreFunction) -> str:
    by_name = {p["name"]: p for p in fn.params}
    args = []
    for a in fn.args:
        p = by_name.get(a)
        args.append(a + "?" if (p and p.get("optional")) else a)
    if not args and any(p["name"] == "..." for p in fn.params):
        args.append("...")
    sig = f"{fn.name}({', '.join(args)})"
    rets = []
    for r in fn.returns:
        rets.append(f"{r['type']} {r['name']}".strip() if r.get("name") else r["type"])
    if rets:
        sig += " -> " + ", ".join(rets)
    return sig


def name_forms(kind: str, name: str) -> list[str]:
    """Every case-insensitive form `fxref core show/resolve` accepts."""
    forms = {name.lower()}
    if kind == "function" and name.startswith("Core."):
        rest = name[len("Core."):]
        forms.add(rest.lower())
        parts = rest.split(".")
        if len(parts) > 2:
            forms.add(".".join(parts[-2:]).lower())
    if kind == "hook":
        forms.add(("corehook." + name).lower())
    return sorted(forms)


def _tokens(name: str) -> str:
    """`Core.UI.menu.open` -> 'Core UI menu open Core.UI.menu.open coreuimenuopen'
    so FTS5 finds it by any word of the dotted name."""
    parts = [p for p in re.split(r"[.\s]+", name) if p]
    words: list[str] = []
    for p in parts:
        words.append(p)
        words.extend(w for w in re.split(r"(?<=[a-z0-9])(?=[A-Z])", p) if w and w != p)
    words.append(name)
    seen, out = set(), []
    for w in words:
        k = w.lower()
        if k not in seen:
            seen.add(k)
            out.append(w)
    return " ".join(out)


def build_rows(api: ParsedApi, lib_index: dict, subs: dict, sha: str = "") -> list[dict]:
    """ParsedApi -> the dict rows `fxref core build` inserts into `core_api`."""
    rows: list[dict] = []

    for fn in api.functions:
        access = access_for(fn, lib_index, subs)
        param_text = " ".join(
            f"{p['name']} {p['type']} {p['description']}" for p in fn.params
        ).strip()
        rows.append({
            "kind": "function", "name": fn.name, "namespace": fn.namespace,
            "sub": fn.sub, "side": fn.side, "access": access,
            "signature": signature_for(fn),
            "params": json.dumps(fn.params, ensure_ascii=False),
            "returns": json.dumps(fn.returns, ensure_ascii=False),
            "description": fn.description,
            "fields": None,
            "values": json.dumps(fn.overloads, ensure_ascii=False) if fn.overloads else None,
            "design_ref": design_ref(fn.section, fn.description),
            "line": fn.line, "sha": sha,
            "name_tokens": _tokens(fn.name), "param_text": param_text,
        })

    for cls in api.classes:
        if cls.is_namespace:
            # A namespace table that declares `---@overload` is itself callable
            # through the proxy (`Core.UI.progress({...})`, `Core.Player(src)`),
            # so it gets a function row -- otherwise fxlint's K013 would report
            # a perfectly valid call as a hallucinated API.
            if cls.overloads:
                rows.append(_callable_namespace_row(cls, lib_index, subs, sha))
            continue    # `---@class Core.Money` only names a namespace table
        field_text = " ".join(
            f"{f['name']} {f['type']} {f['description']}" for f in cls.fields
        ).strip()
        rows.append({
            "kind": "class", "name": cls.name, "namespace": "", "sub": "",
            "side": "shared", "access": "",
            "signature": (f"{cls.name} {{ " + ", ".join(f["name"] for f in cls.fields) + " }"
                           if cls.fields else cls.name),
            "params": None, "returns": None,
            "description": cls.description,
            "fields": json.dumps(cls.fields, ensure_ascii=False),
            "values": None,
            "design_ref": design_ref(cls.section, cls.description),
            "line": cls.line, "sha": sha,
            "name_tokens": _tokens(cls.name), "param_text": field_text,
        })

    for alias in api.aliases:
        shown = " | ".join(
            f"'{v['value']}'" if v.get("quoted") else v["value"] for v in alias.values
        )
        rows.append({
            "kind": "alias", "name": alias.name, "namespace": "", "sub": "",
            "side": "shared", "access": "",
            "signature": f"{alias.name} = {shown}" if shown else alias.name,
            "params": None, "returns": None,
            "description": alias.description,
            "fields": None,
            "values": json.dumps(alias.values, ensure_ascii=False),
            "design_ref": design_ref(alias.description),
            "line": alias.line, "sha": sha,
            "name_tokens": _tokens(alias.name),
            "param_text": " ".join(v["value"] for v in alias.values),
        })
        if alias.name == "CoreHook":
            rows.extend(_hook_rows(alias, sha))

    return rows


RE_OVERLOAD_SIG = re.compile(r"^fun\((.*?)\)\s*(?::\s*(\S+))?\s*(.*)$")


def _callable_namespace_row(cls: CoreClass, lib_index: dict, subs: dict, sha: str) -> dict:
    """`---@class Core.UI.progress` + `---@overload fun(opts: CoreProgressOptions): boolean`
    -> a function row for the directly callable namespace."""
    ns, sub, short = _split_ns(cls.name)
    fn = CoreFunction(name=cls.name, namespace=ns, sub=sub, short=short,
                       description=cls.description, line=cls.line, section=cls.section)
    fn.side = _side_of(cls.description + "\n" + "\n".join(cls.overloads))
    first = RE_OVERLOAD_SIG.match(cls.overloads[0]) if cls.overloads else None
    if first:
        for piece in (p.strip() for p in first.group(1).split(",")):
            if not piece:
                continue
            pname, _, ptype = piece.partition(":")
            fn.args.append(pname.strip())
            fn.params.append({"name": pname.strip(), "optional": False,
                               "type": ptype.strip(), "description": ""})
        if first.group(2):
            fn.returns.append({"type": first.group(2), "name": "", "description": ""})
    access = "proxy" if (sub or ns not in ("Core",)) else "lib"
    if not sub and ns in lib_index and short in (lib_index.get(ns) or {}):
        access = "lib"
    return {
        "kind": "function", "name": fn.name, "namespace": ns, "sub": sub,
        "side": fn.side, "access": access, "signature": signature_for(fn),
        "params": json.dumps(fn.params, ensure_ascii=False),
        "returns": json.dumps(fn.returns, ensure_ascii=False),
        "description": cls.description,
        "fields": None,
        "values": json.dumps(cls.overloads, ensure_ascii=False),
        "design_ref": design_ref(cls.section, cls.description),
        "line": cls.line, "sha": sha,
        "name_tokens": _tokens(fn.name), "param_text": " ".join(p["name"] for p in fn.params),
    }


RE_HOOK_ARGS = re.compile(r"\(([^()]*)\)")


def _hook_rows(alias: CoreAlias, sha: str) -> list[dict]:
    """One row per `CoreHook` value: side + handler arguments, so `fxref core
    hooks` can print `playerDropped  [server]  (src, charId)`."""
    out = []
    for v in alias.values:
        if not v.get("quoted"):
            continue
        desc = v.get("description") or ""
        side = _side_of(desc)
        args = ""
        for m in RE_HOOK_ARGS.finditer(desc):
            inner = m.group(1).strip()
            if inner.lower() in ("server", "client"):
                continue
            args = inner
            break
        arg_list = [a.strip() for a in args.split(",") if a.strip()]
        out.append({
            "kind": "hook", "name": v["value"], "namespace": "CoreHook",
            "sub": "", "side": side, "access": "lib",
            "signature": "Core.on('{}', function({}) end)".format(v["value"], ", ".join(arg_list)),
            "params": json.dumps([{"name": a, "optional": False, "type": "", "description": ""}
                                   for a in arg_list], ensure_ascii=False),
            "returns": None, "description": desc, "fields": None, "values": None,
            "design_ref": design_ref(desc) or "DESIGN §8",
            "line": alias.line, "sha": sha,
            "name_tokens": _tokens(v["value"]) + " hook CoreHook",
            "param_text": args,
        })
    return out


# ---------------------------------------------------------------------------
# filesystem entry point
# ---------------------------------------------------------------------------
def build_core_rows(core_root: Path, types_path: Path, sha: str = "") -> tuple[list[dict], dict]:
    """Read core's sources and return (rows, stats). Raises OSError when
    `types_path` cannot be read -- callers decide whether that is fatal."""
    text = types_path.read_text(encoding="utf-8", errors="replace")
    api = parse_types(text)
    import_path = core_root / "import.lua"
    import_text = import_path.read_text(encoding="utf-8", errors="replace") if import_path.is_file() else ""
    libs, subs = parse_import(import_text)
    lib_index = scan_lib_functions(core_root, libs)
    rows = build_rows(api, lib_index, subs, sha=sha)
    stats = {
        "core_functions": sum(1 for r in rows if r["kind"] == "function"),
        "core_classes": sum(1 for r in rows if r["kind"] == "class"),
        "core_aliases": sum(1 for r in rows if r["kind"] == "alias"),
        "core_hooks": sum(1 for r in rows if r["kind"] == "hook"),
        "core_lib": sum(1 for r in rows if r["kind"] == "function" and r["access"] == "lib"),
        "core_proxy": sum(1 for r in rows if r["kind"] == "function" and r["access"] == "proxy"),
        "core_namespaces": len({r["namespace"] for r in rows if r["kind"] == "function"}),
        "core_sha": sha,
    }
    return rows, stats
