"""Native-call collection and verification (C007/C008) for fxlint.

Candidates are "PascalCase(" or "N_0x<hex>(" call sites that are not a
dotted/colon method call (Config.Foo(), lib.callback(), exports.x:Y()) and
are not defined locally in the resource. What's left is checked in a single
batch subprocess against `fxref resolve --json`, if fxref has been built.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from fxkit import config

# Identifiers the Lua/JS *runtime itself* provides (scheduler.lua, natives_loader.lua,
# v8/main.js, v8/timer.js) that look like PascalCase native calls but are not native
# functions in the fxref database -- these must never be sent to fxref / flagged C008.
RUNTIME_GLOBALS = frozenset({
    # scheduling
    "CreateThread", "Wait", "SetTimeout", "ClearTimeout",
    # events
    "AddEventHandler", "RemoveEventHandler", "RegisterNetEvent", "RegisterServerEvent",
    "TriggerEvent", "TriggerServerEvent", "TriggerClientEvent",
    "TriggerLatentClientEvent", "TriggerLatentServerEvent",
    "RegisterCommand", "RegisterKeyMapping",
    # player/entity helpers documented as always-known in DESIGN.md
    "GetHashKey", "PlayerPedId", "PlayerId", "GetPlayerServerId",
    "Entity", "Player", "GlobalState", "LocalPlayer",
    # misc scheduler.lua globals
    "GetPlayerIdentifiers", "GetPlayerTokens", "GetPlayers", "GetPlayerEP",
    "PerformHttpRequest", "PerformHttpRequestAwait", "SendNUIMessage",
    "RconPrint", "RconLog",
    # vector/quaternion constructors (usually lowercase but tolerate PascalCase typos safely)
    "Vector2", "Vector3", "Vector4", "Quat",
})

# Framework / library namespace roots -- calls through these always go through the
# dot/colon exclusion below, this just also covers the (rare) bare reference.
FRAMEWORK_GLOBALS = frozenset({
    "Config", "ESX", "QBCore", "QBox", "Qbox", "Ox", "Core", "Framework", "Lib",
})

RE_NATIVE_CALL = re.compile(r"(?<![.\w:])((?:[A-Z][A-Za-z0-9]*)|(?:N_0x[0-9A-Fa-f]+))\s*\(")


def find_native_candidates(clean_lines: list, exclude: set) -> list:
    """Returns [(line, name), ...] for calls that look like natives."""
    out = []
    for i, line in enumerate(clean_lines, start=1):
        for m in RE_NATIVE_CALL.finditer(line):
            name = m.group(1)
            if name in RUNTIME_GLOBALS or name in FRAMEWORK_GLOBALS or name in exclude:
                continue
            out.append((i, name))
    return out


def fxref_bin_path() -> Path:
    return config.kit_root() / "bin" / "fxref"


def fxref_db_path() -> Path:
    return config.kit_root() / "data" / "fxref.sqlite"


def is_available() -> bool:
    try:
        return fxref_bin_path().exists() and fxref_db_path().exists()
    except OSError:
        return False


def resolve_names(names, timeout: float = 15.0) -> Optional[list]:
    """Batch-resolve `names` via `fxref resolve --json`.

    Returns the parsed JSON list ([{input, found, matches:[...]}, ...]), or
    None if fxref isn't available / the call failed / output was unusable --
    callers must treat None as "skip verification", never as "all unknown".
    """
    names = sorted(set(names))
    if not names:
        return []
    if not is_available():
        return None
    bin_path = fxref_bin_path()
    cmd = [str(bin_path), "resolve", "--json", *names]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        # not executable, interpreter mismatch, timeout, etc. -- degrade gracefully
        try:
            proc = subprocess.run([sys.executable, str(bin_path), "resolve", "--json", *names],
                                   capture_output=True, text=True, timeout=timeout)
        except (OSError, subprocess.SubprocessError):
            return None
    if proc.returncode != 0 or not proc.stdout:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    if not isinstance(data, list):
        return None
    return data


def apiset_ok(side: Optional[str], apisets) -> bool:
    if side is None or side == "shared":
        return True
    return side in apisets or "shared" in apisets
