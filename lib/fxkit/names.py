"""Native name conversions and signature rendering.

Implements, in Python, the exact algorithms used by FiveM's own codegen:
  - ext/natives/codegen_out_lua.lua  (printFunctionName, isSinglePointerNative,
    printArgumentList, printLuaType)
  - ext/natives/codegen_out_js.lua   (same printFunctionName; array-style returns)
  - ext/natives/codegen_out_cs.lua   (printReturnType, parseArgument -> ref params)
  - ext/natives/codegen_types.lua    (type -> nativeType table)

See DESIGN.md section 2 ("Signature rules") for the contract this implements.
"""
from __future__ import annotations

import re
from typing import Any

# ---------------------------------------------------------------------------
# Type classification (from ext/natives/codegen_types.lua)
# ---------------------------------------------------------------------------
# Maps a *base* type name (pointer '*' and leading 'const ' already stripped)
# to its codegen "nativeType" bucket: int | float | bool | string | vector3 |
# func | object. Case-sensitive on purpose: 'Object' (a GTA prop handle) and
# 'object' (a generic msgpack-serialized table) are different types.
TYPE_KIND: dict[str, str] = {
    "Void": "int",
    "Any": "int",
    "uint": "int",
    "Hash": "int",
    "Entity": "int",
    "Player": "int",
    "DecisionMaker": "int",
    "FireId": "int",
    "Ped": "int",
    "Vehicle": "int",
    "Cam": "int",
    "CarGenerator": "int",
    "Group": "int",
    "Train": "int",
    "Pickup": "int",
    "Object": "int",
    "Weapon": "int",
    "Interior": "int",
    "Blip": "int",
    "Texture": "int",
    "TextureDict": "int",
    "CoverPoint": "int",
    "Camera": "int",
    "TaskSequence": "int",
    "ColourIndex": "int",
    "Sphere": "int",
    "ScrHandle": "int",
    "BOOL": "bool",
    "bool": "bool",
    "int": "int",
    "long": "int",
    "float": "float",
    "Vector3": "vector3",
    "func": "func",
    "object": "object",
    # rdr3-specific but harmless to keep for gta5 builds too
    "ItemSet": "int",
    "AnimScene": "int",
    "PersChar": "int",
    "PopZone": "int",
    "Prompt": "int",
    "PropSet": "int",
    "Volume": "int",
}
_TYPE_KIND_LOWER = {k.lower(): v for k, v in TYPE_KIND.items()}

# Lua/JS display labels (ext/natives/codegen_out_lua.lua printLuaType, plus the
# DESIGN.md-mandated override for Any* -> integer/number).
_LUA_LABEL = {
    "int": "integer",
    "float": "number",
    "bool": "boolean",
    "string": "string",
    "vector3": "vector3",
    "func": "func",
    "object": "object",
    "Any*": "integer",
}
_JS_LABEL = {
    "int": "number",
    "float": "number",
    "bool": "boolean",
    "string": "string",
    "func": "function",
    "object": "object",
    "Any*": "number",
}


def parse_type(raw: str) -> dict[str, Any]:
    """Classify a raw C-ish type string (e.g. 'Vector3*', 'const char*', 'BOOL').

    Returns {'raw', 'base', 'pointer', 'kind'}. `pointer` is True only for
    actual out-params -- char*/const char* are always treated as (input)
    strings, matching DESIGN.md's pointer rule.
    """
    t = re.sub(r"\s+", " ", (raw or "").strip())
    if t in ("char*", "const char*", "char *", "const char *"):
        return {"raw": raw, "base": "char*", "pointer": False, "kind": "string"}

    pointer = t.endswith("*")
    base = t[:-1].strip() if pointer else t
    base = re.sub(r"^const\s+", "", base).strip()

    kind = TYPE_KIND.get(base)
    if kind is None:
        kind = _TYPE_KIND_LOWER.get(base.lower(), "int")

    if pointer and base == "Any":
        kind = "Any*"

    return {"raw": raw, "base": base, "pointer": pointer, "kind": kind}


def classify_return(raw: str | None) -> str | None:
    """Classify a return-type string. None means void/no return value."""
    if not raw:
        return None
    t = raw.strip()
    if not t or t.lower() == "void":
        return None
    if t in ("char*", "const char*"):
        return "string"
    base = t[:-1].strip() if t.endswith("*") else t
    base = re.sub(r"^const\s+", "", base).strip()
    kind = TYPE_KIND.get(base)
    if kind is None:
        kind = _TYPE_KIND_LOWER.get(base.lower(), "int")
    if t.endswith("*") and base == "Any":
        return "Any*"
    return kind


def build_param(name: str, raw_type: str, description: str | None = None) -> dict[str, Any]:
    info = parse_type(raw_type)
    return {
        "name": name,
        "type": raw_type,
        "base": info["base"],
        "pointer": info["pointer"],
        "kind": info["kind"],
        "description": description,
    }


# ---------------------------------------------------------------------------
# Name conversion (ext/natives/codegen_out_lua.lua printFunctionName, byte
# identical in codegen_out_js.lua)
# ---------------------------------------------------------------------------
_UNDERSCORE_LETTER_RE = re.compile(r"_([a-z])")
_FIRST_ALPHA_RE = re.compile(r"[A-Za-z]")


def lua_name(c_name: str) -> str:
    """`SET_PED_INTO_VEHICLE` -> `SetPedIntoVehicle`; `_0x1647F1CB` -> `N_0x1647f1cb`.

    Exactly mirrors:
        name:lower():gsub('0x','n_0x'):gsub('_(%a)', upper):gsub('(%a)(.+)', upperFirst)

    Note the third gsub's `%a` matches a letter of EITHER case -- by the time
    we get here the only uppercase letter possible is one produced by the
    previous step (e.g. the 'N' in 'N_0x...'), and Lua's upper() on an
    already-uppercase letter is a no-op, so we must search for the first
    letter of *either* case, not just lowercase.
    """
    s = (c_name or "").lower()
    s = s.replace("0x", "n_0x")
    s = _UNDERSCORE_LETTER_RE.sub(lambda m: m.group(1).upper(), s)
    m = _FIRST_ALPHA_RE.search(s)
    if m:
        i = m.start()
        s = s[:i] + s[i].upper() + s[i + 1 :]
    return s


def lower_camel(lua_nm: str) -> str:
    if not lua_nm:
        return lua_nm
    return lua_nm[0].lower() + lua_nm[1:]


# ---------------------------------------------------------------------------
# Signature rendering
# ---------------------------------------------------------------------------
def is_single_pointer_native(params: list[dict[str, Any]]) -> bool:
    """True iff exactly one param is a pointer AND it is the last param.

    Mirrors isSinglePointerNative() in codegen_out_lua.lua / codegen_out_js.lua.
    """
    pointer_idxs = [i for i, p in enumerate(params) if p["pointer"]]
    if len(pointer_idxs) != 1:
        return False
    return pointer_idxs[0] == len(params) - 1


def render_c_signature(c_name: str, params: list[dict[str, Any]], return_type_raw: str | None) -> str:
    args = ", ".join(f'{p["type"]} {p["name"]}' for p in params)
    ret = return_type_raw or "void"
    return f"{ret} {c_name}({args})"


def render_lua_signature(lua_nm: str, params: list[dict[str, Any]], return_kind: str | None) -> str:
    single = is_single_pointer_native(params)
    args = []
    for p in params:
        if not p["pointer"]:
            args.append(p["name"])
        elif single:
            args.append(p["name"] + "?")
    arg_str = ", ".join(args)

    entries: list[tuple[str, str]] = []
    if return_kind is not None:
        entries.append(("retval", _LUA_LABEL.get(return_kind, return_kind)))
    for p in params:
        if p["pointer"]:
            entries.append((p["name"], _LUA_LABEL.get(p["kind"], p["kind"])))

    if not entries:
        ret_str = ""
    elif len(entries) == 1 and entries[0][0] == "retval":
        ret_str = " -> " + entries[0][1]
    else:
        ret_str = " -> " + ", ".join(f"{typ} {label}" for label, typ in entries)

    return f"{lua_nm}({arg_str}){ret_str}"


def _js_type(kind: str) -> str:
    if kind == "vector3":
        return "[x, y, z]"
    return _JS_LABEL.get(kind, kind)


def render_js_signature(lua_nm: str, params: list[dict[str, Any]], return_kind: str | None) -> str:
    single = is_single_pointer_native(params)
    args = []
    for p in params:
        if not p["pointer"]:
            args.append(p["name"])
        elif single:
            args.append(p["name"] + "?")
    arg_str = ", ".join(args)

    entries: list[str] = []
    if return_kind is not None:
        entries.append(return_kind)
    for p in params:
        if p["pointer"]:
            entries.append(p["kind"])

    if not entries:
        ret_str = ": void"
    elif len(entries) == 1:
        ret_str = ": " + _js_type(entries[0])
    else:
        ret_str = ": [" + ", ".join(_js_type(k) for k in entries) + "]"

    return f"{lua_nm}({arg_str}){ret_str}"


_CS_KIND_TYPE = {
    "int": "int",
    "float": "float",
    "bool": "bool",
    "string": "string",
    "vector3": "Vector3",
    "func": "InputArgument",
    "object": "object",
}
_CS_RETURN_KIND_TYPE = {
    "string": "string",
    "bool": "bool",
    "float": "float",
    "vector3": "Vector3",
    "int": "int",
    "object": "dynamic",
}


def _cs_param_type(base: str, kind: str) -> str:
    if base in ("Hash", "uint"):
        return "uint"
    if kind == "Any*":
        return "object"
    return _CS_KIND_TYPE.get(kind, "int")


def _cs_return_type(kind: str | None) -> str:
    if kind is None:
        return "void"
    return _CS_RETURN_KIND_TYPE.get(kind, "int")


def render_cs_signature(lua_nm: str, params: list[dict[str, Any]], return_kind: str | None) -> str:
    parts = []
    for p in params:
        t = _cs_param_type(p["base"], p["kind"])
        if p["pointer"]:
            parts.append(f'ref {t} {p["name"]}')
        else:
            parts.append(f'{t} {p["name"]}')
    ret = _cs_return_type(return_kind)
    return f'{ret} API.{lua_nm}({", ".join(parts)})'


def build_signatures(
    c_name: str,
    lua_nm: str,
    params: list[dict[str, Any]],
    return_type_raw: str | None,
) -> dict[str, str]:
    return_kind = classify_return(return_type_raw)
    return {
        "c_signature": render_c_signature(c_name, params, return_type_raw),
        "lua_signature": render_lua_signature(lua_nm, params, return_kind),
        "js_signature": render_js_signature(lua_nm, params, return_kind),
        "cs_signature": render_cs_signature(lua_nm, params, return_kind),
    }


# ---------------------------------------------------------------------------
# Name-token helpers (for search + native_names lookup table)
# ---------------------------------------------------------------------------
def name_words(c_name: str) -> list[str]:
    """Split a C name on '_' into lowercase words, dropping empties."""
    return [w for w in c_name.split("_") if w]


_CAMEL_SPLIT_RE = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|[0-9]+")


def split_camel_or_snake(query: str) -> list[str]:
    """Split a search query term on camelCase/snake_case/hyphen/dot boundaries."""
    words: list[str] = []
    for chunk in re.split(r"[_\-.\s]+", query.strip()):
        if not chunk:
            continue
        parts = _CAMEL_SPLIT_RE.findall(chunk)
        words.extend(parts if parts else [chunk])
    return [w.lower() for w in words if w]
