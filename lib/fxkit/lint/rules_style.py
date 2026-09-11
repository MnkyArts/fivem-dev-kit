"""C001-C012: conventions / correctness rules.

A few of these are resource-level rather than per-file (C004, C005) -- the
engine calls check_c004/check_c005 once per resource instead of once per
file. Everything else follows the same run(pf, ctx) shape as rules_sec.py.
"""
from __future__ import annotations

import re

from .model import Finding

_STRING = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""

RE_C001 = re.compile(r"\bCitizen\.(CreateThread|Wait|SetTimeout|Trace)\s*\(")
C001_MODERN = {"CreateThread": "CreateThread(...)", "Wait": "Wait(...)", "SetTimeout": "SetTimeout(...)", "Trace": "print(...)"}
RE_C002 = re.compile(r"\bGetPlayerPed\s*\(\s*-1\s*\)")
RE_C009_TSE = re.compile(r"(?<![.\w:])TriggerServerEvent\s*\(")
RE_C009_TCE = re.compile(r"(?<![.\w:])TriggerClientEvent\s*\(")
RE_C009_SOURCE = re.compile(r"(?<!\.)\bsource\b")
RE_LOCAL_SOURCE = re.compile(r"\b(?:local|const|let|var)\s+source\b")  # Lua `local` / JS declarations
RE_PARAM_SOURCE = re.compile(r"function\s*\([^)]*\bsource\b[^)]*\)|\([^)]*\bsource\b[^)]*\)\s*=>")

RE_TOPLEVEL_FUNC_DECL = re.compile(r"^\s*function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(")
RE_TOPLEVEL_ASSIGN = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")

RE_EXPORTS_DOT = re.compile(r"\bexports\.([A-Za-z_][A-Za-z0-9_\-]*)\s*[:.]")
RE_EXPORTS_BRACKET = re.compile(r"\bexports\[\s*(" + _STRING + r")\s*\]\s*[:.]")


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        return s[1:-1]
    return s


def _end(pf, frame) -> int:
    return frame.end_line if frame.end_line > 0 else pf.line_count()


def check_c001(pf) -> list:
    findings = []
    for i, line in enumerate(pf.clean_lines, start=1):
        for m in RE_C001.finditer(line):
            name = m.group(1)
            findings.append(Finding(
                pf.rel_path, i, "C001", "info",
                f"Citizen.{name}(...) -- use the modern global form",
                f"use {C001_MODERN[name]} instead of Citizen.{name}(...)",
            ))
    return findings


def check_c002(pf) -> list:
    findings = []
    for i, line in enumerate(pf.clean_lines, start=1):
        if RE_C002.search(line):
            findings.append(Finding(
                pf.rel_path, i, "C002", "info",
                "GetPlayerPed(-1) -- use PlayerPedId() instead",
                "PlayerPedId() is the direct, documented way to get the local player's ped",
            ))
    return findings


def check_c003(pf, ctx) -> list:
    if pf.lang != "lua":
        return []
    findings = []
    for i, line in enumerate(pf.clean_lines, start=1):
        # frames that *start on this exact line* (e.g. this very `function Name()`
        # declaration) don't count as nesting -- only frames opened on an earlier
        # line make this a non-top-level statement.
        enclosing = [f for f in pf.open_frames(i) if f.start_line != i]
        if enclosing or pf.table_depth_start.get(i, 0) != 0:
            continue  # not file scope (inside a function/if/loop/table constructor)
        if re.match(r"^\s*local\b", line):
            continue
        m = RE_TOPLEVEL_FUNC_DECL.match(line)
        if m:
            name = m.group(1)
            if name in ctx.callback_or_export_refs:
                continue
            findings.append(Finding(
                pf.rel_path, i, "C003", "warn",
                f"global function '{name}' declared without local -- leaks into this resource's shared globals",
                f"use 'local function {name}(...)'; keep it global only if it's an export/callback registered elsewhere",
            ))
            continue
        m = RE_TOPLEVEL_ASSIGN.match(line)
        if not m:
            continue
        name, rhs = m.group(1), m.group(2).strip()
        if name in ctx.callback_or_export_refs:
            continue
        if rhs.startswith("function"):
            findings.append(Finding(
                pf.rel_path, i, "C003", "warn",
                f"global '{name} = function...' declared without local -- leaks into this resource's shared globals",
                f"use 'local {name} = function(...)' or 'local function {name}(...)'",
            ))
            continue
        if rhs.startswith("{"):
            continue  # namespace/config table (Config = {...}) -- idiomatic and expected across files
        if re.match(r"^[A-Za-z_][A-Za-z0-9_]*\s+or\s+\{", rhs):
            continue  # `Config = Config or {}` re-entrant guard
        if re.match(r"^exports[.\[]", rhs) or re.match(r"^require\s*[(\'\"]", rhs):
            continue  # framework bootstrap: ESX = exports['es_extended']:getSharedObject()
            # (require(...) or Lua's paren-less `require '@ox_core.lib.init'` sugar call)
        findings.append(Finding(
            pf.rel_path, i, "C003", "warn",
            f"global variable '{name}' assigned without local -- leaks into this resource's shared globals",
            f"use 'local {name} = ...' unless this is intentionally a cross-file namespace table",
        ))
    return findings


def check_c006(pf, ctx) -> list:
    findings = []
    if pf.side == "server":
        incoming = {n for _, n, _, _ in ctx.trigger_server if n}
    elif pf.side == "client":
        incoming = {n for _, n, _, _ in ctx.trigger_client if n}
    else:
        incoming = set()

    for f in pf.frames:
        if f.handler_call != "AddEventHandler" or not f.handler_name:
            continue
        if f.handler_name in incoming and f.handler_name not in ctx.net_event_names:
            findings.append(Finding(
                pf.rel_path, f.start_line, "C006", "warn",
                f"AddEventHandler('{f.handler_name}', ...) is triggered from the other side over the network but was never RegisterNetEvent'ed -- it won't be delivered",
                f"add RegisterNetEvent('{f.handler_name}') (RegisterServerEvent on the server) before/instead of this AddEventHandler",
            ))

    for i, line in enumerate(pf.code_lines, start=1):
        for m in re.finditer(r"\b(RegisterNetEvent|RegisterServerEvent)\s*\(\s*(" + _STRING + r")\s*\)", line):
            name = _strip_quotes(m.group(2))
            if name and (pf.side, name) not in ctx.handled_names:
                findings.append(Finding(
                    pf.rel_path, i, "C006", "warn",
                    f"RegisterNetEvent('{name}') has no AddEventHandler anywhere in this resource",
                    "add an AddEventHandler(name, function(...) ... end) for it, or remove the unused registration",
                ))
    return findings


def check_c007_c008(pf, candidates, resolved_map) -> list:
    findings = []
    for ln, name in candidates:
        entry = resolved_map.get(name)
        if entry is None:
            continue
        if not entry.get("found"):
            findings.append(Finding(
                pf.rel_path, ln, "C008", "warn",
                f"'{name}(...)' looks like a native call but wasn't found in the native database",
                "double-check the spelling (fxref search '<name>'), or define it locally if it's a helper you wrote",
            ))
            continue
        matches = entry.get("matches") or []
        apisets = {m.get("apiset") for m in matches if m.get("apiset")}
        if pf.side in ("client", "server") and apisets and pf.side not in apisets and "shared" not in apisets:
            other = "server" if pf.side == "client" else "client"
            findings.append(Finding(
                pf.rel_path, ln, "C007", "error",
                f"'{name}(...)' is a {other}-only native but this is a {pf.side} file",
                f"call it from a {other} file, or use a net event to reach the {other} side",
            ))
    return findings


def check_c009(pf) -> list:
    findings = []
    for i, line in enumerate(pf.clean_lines, start=1):
        if pf.side == "server" and RE_C009_TSE.search(line):
            findings.append(Finding(
                pf.rel_path, i, "C009", "error",
                "TriggerServerEvent(...) called from a server file -- this function only exists on the client",
                "server -> client is TriggerClientEvent(...); server -> server is TriggerEvent(...)",
            ))
        if pf.side == "client" and RE_C009_TCE.search(line):
            findings.append(Finding(
                pf.rel_path, i, "C009", "error",
                "TriggerClientEvent(...) called from a client file -- this function only exists on the server",
                "client -> server is TriggerServerEvent(...); client -> client is TriggerEvent(...)",
            ))
        if pf.side == "client" and RE_C009_SOURCE.search(line):
            if RE_LOCAL_SOURCE.search(line) or RE_PARAM_SOURCE.search(line):
                continue
            findings.append(Finding(
                pf.rel_path, i, "C009", "error",
                "'source' used in a client file -- this global doesn't mean 'triggering player' on the client",
                "the client has no server-style event source; remove this or double-check the intent",
            ))
    return findings


def check_c010(pf, ctx) -> list:
    if pf.side != "server" or pf.lang not in ("js", "ts"):
        return []
    findings = []
    triggered_by_client = {n for _, n, _, _ in ctx.trigger_server if n}
    for f in pf.frames:
        if f.handler_call == "on" and f.handler_name in triggered_by_client:
            findings.append(Finding(
                pf.rel_path, f.start_line, "C010", "info",
                f"on('{f.handler_name}', ...) handles an event a client triggers over the network -- use onNet instead",
                "onNet marks the event net-safe the same way on() handles a purely local event",
            ))
    return findings


def check_c011(pf) -> list:
    findings = []
    for f in pf.frames:
        if not f.is_handler or not f.handler_name or "ResourceStop" not in f.handler_name:
            continue
        end = _end(pf, f)
        for ln in range(f.start_line, end + 1):
            line = pf.clean(ln)
            if re.search(r"\b(?:Citizen\.)?Wait\s*\(", line) or re.search(r"\bawait\s+Delay\s*\(", line):
                findings.append(Finding(
                    pf.rel_path, ln, "C011", "info",
                    f"Wait()/Delay() inside a '{f.handler_name}' handler -- stop handlers must run synchronously",
                    "do cleanup synchronously; the resource may already be torn down by the time an async wait resumes",
                ))
    return findings


def check_c012(pf, ctx) -> list:
    findings = []
    seen = set()
    for i, line in enumerate(pf.code_lines, start=1):
        names = set()
        for m in RE_EXPORTS_DOT.finditer(line):
            names.add(m.group(1))
        for m in RE_EXPORTS_BRACKET.finditer(line):
            n = _strip_quotes(m.group(1))
            if n:
                names.add(n)
        for name in names:
            if name in ctx.dependencies or name in seen:
                continue
            seen.add(name)
            findings.append(Finding(
                pf.rel_path, i, "C012", "info",
                f"exports.{name} is used but '{name}' is not declared as a dependency in fxmanifest.lua",
                f"add dependency '{name}' so start order and missing-dependency errors are explicit",
            ))
    return findings


def run(pf, ctx) -> list:
    """Per-file style checks (C001-C003, C006, C009-C012). C004/C005 are
    resource-level (see check_c004/check_c005) and C007/C008 need the batch
    fxref resolution result (see check_c007_c008), so the engine calls those
    separately."""
    findings = []
    findings += check_c001(pf)
    findings += check_c002(pf)
    findings += check_c003(pf, ctx)
    findings += check_c006(pf, ctx)
    findings += check_c009(pf)
    findings += check_c010(pf, ctx)
    findings += check_c011(pf)
    findings += check_c012(pf, ctx)
    return [f for f in findings if not pf.is_suppressed(f.line, f.rule)]


def check_c004(resource_dir) -> list:
    p = resource_dir / "__resource.lua"
    if p.exists():
        return [Finding("__resource.lua", 1, "C004", "error",
                         "__resource.lua is present -- this legacy manifest format is superseded by fxmanifest.lua",
                         "migrate to fxmanifest.lua and delete __resource.lua")]
    return []


def check_c005(resource_dir, manifest) -> list:
    findings = []
    if manifest.path is None:
        return [Finding("fxmanifest.lua", 1, "C005", "warn",
                         "no fxmanifest.lua found in this resource",
                         "add an fxmanifest.lua (fx_version, game, scripts, ...) -- FiveM won't load the resource without one")]
    mpath = manifest.path.name
    if not manifest.fx_version:
        findings.append(Finding(mpath, 1, "C005", "warn", "fxmanifest.lua has no fx_version",
                                 "add fx_version 'cerulean' (or newer)"))
    if not manifest.games:
        findings.append(Finding(mpath, 1, "C005", "warn", "fxmanifest.lua has no game",
                                 "add game 'gta5' (or 'rdr3'/'common')"))
    # lua54 'yes' is a no-op since Lua 5.3 was removed (June 2025, see DESIGN.md section 8) --
    # deliberately not linted for, whether present or absent.
    if manifest.use_experimental_fxv2_oal:
        findings.append(Finding(mpath, 1, "C005", "info",
                                 "use_experimental_fxv2_oal is enabled",
                                 "OAL enabled: pass vectors as x, y, z (SetEntityCoords(ped, v.x, v.y, v.z)) -- vector3 auto-unpacking is disabled"))
    uses_lib = False
    for pat in (resource_dir / "client", resource_dir / "server", resource_dir / "shared", resource_dir):
        if pat.is_dir():
            for f in pat.rglob("*.lua"):
                try:
                    # require a *call* (lib.points.new(...)) -- not just any "lib."
                    # text, which also matches unrelated things like a module path
                    # ('@ox_core.lib.init') in a require(...) string.
                    if re.search(r"\blib\.[A-Za-z_][A-Za-z0-9_.]*\s*\(", f.read_text(encoding="utf-8", errors="replace")):
                        uses_lib = True
                        break
                except OSError:
                    continue
        if uses_lib:
            break
    if uses_lib and not manifest.uses_ox_lib:
        findings.append(Finding(mpath, 1, "C005", "warn",
                                 "scripts call lib.* (ox_lib) but fxmanifest.lua has no '@ox_lib/init.lua' shared_script / ox_lib dependency",
                                 "add '@ox_lib/init.lua' to shared_scripts and dependency 'ox_lib'"))
    return findings
