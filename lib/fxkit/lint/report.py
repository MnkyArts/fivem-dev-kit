"""Output formatting, rule catalogue metadata, and exit-code logic for fxlint."""
from __future__ import annotations

import json as _json

from .model import Finding

# id -> (default level, one-line description). Used for --rules/--ignore validation
# and to keep docs/fxlint.md and this implementation honest about the same list.
RULES = {
    "P001": ("error", "infinite loop with no Wait()/Citizen.Wait()"),
    "P002": ("warn", "Wait(0..15) in a loop with no adaptive branch or justification"),
    "P003": ("info", "Wait(16..99) in a loop -- consider raising it"),
    "P004": ("warn", "CreateThread/setTick created inside a loop or event handler"),
    "P005": ("warn", "expensive native call inside a per-frame loop"),
    "P006": ("warn", "TriggerClientEvent/emitNet broadcast (-1) inside a loop/timer"),
    "P007": ("info", "PlayerPedId() called repeatedly inside one per-frame loop"),
    "S001": ("warn", "server net-event handler never reads 'source'"),
    "S002": ("warn", "sensitive call fed an unvalidated event argument"),
    "S003": ("warn", "trusts a payload player id instead of 'source'"),
    "S004": ("info", "net event registered but never triggered over the network"),
    "S005": ("warn", "admin-looking RegisterCommand registered unrestricted"),
    "S006": ("warn", "dynamic code execution / shell access call"),
    "S007": ("info", "triggered event has no matching handler in this resource"),
    "S008": ("warn", "event argument used as a table index/number with no type check"),
    "S009": ("warn", "SetEntityCoords/SetPedIntoVehicle from payload with no distance check"),
    "S010": ("warn", "'source' read after Wait()/Await() -- may be stale"),
    "C001": ("info", "Citizen.* call -- use the modern global form"),
    "C002": ("info", "GetPlayerPed(-1) -- use PlayerPedId()"),
    "C003": ("warn", "file-scope global leak (function/variable declared without local)"),
    "C004": ("error", "__resource.lua present (legacy manifest format)"),
    "C005": ("warn", "fxmanifest.lua issues (missing keys, ox_lib without dependency, ...)"),
    "C006": ("warn", "RegisterNetEvent/AddEventHandler registration mismatch"),
    "C007": ("error", "native used from the wrong side (client/server apiset mismatch)"),
    "C008": ("warn", "unknown call that looks like a native, not found in the native database"),
    "C009": ("error", "TriggerServerEvent/TriggerClientEvent/'source' used on the wrong side"),
    "C010": ("info", "JS on() used for a networked event -- use onNet()"),
    "C011": ("info", "Wait()/Delay() inside a resource-stop handler"),
    "C012": ("info", "exports.* used without a matching manifest dependency"),
    # tool-level notices, not part of the P/S/C catalogue proper -- always info,
    # never affect the exit code, exist purely so "never crash" degrades visibly.
    "PARSE": ("info", "a file could not be analysed and was skipped"),
}

_LEVEL_RANK = {"error": 0, "warn": 1, "info": 2}


def level_rank(level: str) -> int:
    return _LEVEL_RANK.get(level, 3)


def _sort_key(f: Finding):
    return (f.path, f.line, level_rank(f.level), f.rule)


def apply_strict(findings: list, strict: bool) -> list:
    if strict:
        for f in findings:
            if f.level == "warn":
                f.level = "error"
    return findings


def summarize(findings: list) -> dict:
    s = {"errors": 0, "warns": 0, "infos": 0}
    for f in findings:
        if f.level == "error":
            s["errors"] += 1
        elif f.level == "warn":
            s["warns"] += 1
        else:
            s["infos"] += 1
    return s


def exit_code(findings: list) -> int:
    return 1 if any(f.level == "error" for f in findings) else 0


def format_text(findings: list, notes: list = None) -> str:
    lines = []
    for f in sorted(findings, key=_sort_key):
        lines.append(f"{f.path}:{f.line}: {f.level.upper()} {f.rule} {f.msg}")
        if f.hint:
            lines.append(f"    fix: {f.hint}")
    for note in (notes or []):
        lines.append(note)
    summary = summarize(findings)
    lines.append(f"summary: {summary['errors']} error(s), {summary['warns']} warning(s), {summary['infos']} info(s)")
    return "\n".join(lines)


def format_json(findings: list, notes: list = None) -> str:
    by_file: dict = {}
    for f in sorted(findings, key=_sort_key):
        by_file.setdefault(f.path, []).append(f.to_json())
    out = {"files": by_file, "summary": summarize(findings), "notes": list(notes or [])}
    return _json.dumps(out, indent=2)
