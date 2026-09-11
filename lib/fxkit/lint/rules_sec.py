"""S001-S009: security rules.

All of these look at "server net-event handlers": function frames tagged as
handlers (see luaparse.py/jsparse.py) whose event name is known net-safe
(registered via RegisterNetEvent/RegisterServerEvent/onNet somewhere in the
resource -- see xref.py) and that live in a file on the server side.
"""
from __future__ import annotations

import re

from .model import Finding

_STRING = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""

RE_VALIDATION = re.compile(
    r"\bif\b|\bassert\s*\(|\btonumber\s*\(|\btype\s*\(|#\s*\(|\bIsPlayerAceAllowed\s*\("
)
RE_DIST_CHECK = re.compile(r"#\s*\(|\bGetDistanceBetweenCoords\s*\(|\bVdist2?\s*\(")
RE_TYPE_CHECK_ONLY = re.compile(r"\btype\s*\(|\btonumber\s*\(|\bassert\s*\(")

RE_ANY_CALL_NAME = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
SENSITIVE_EXACT = {
    "SetPlayerRoutingBucket", "DropPlayer", "ExecuteCommand", "GiveWeaponToPed",
    "SetEntityCoords", "SetPedArmour",
}
# "add"/"remove" are deliberately NOT bare substrings here -- they're common in
# totally unrelated runtime/native names (AddEventHandler, RemoveEventHandler,
# AddBlipForEntity, RemoveAllPedWeapons, ...). "AddItem"/"RemoveMoney"-style
# calls still match via the money/item/bank/cash/inventory/xp/level nouns below.
SENSITIVE_SUBSTR = ("money", "item", "bank", "cash", "give", "inventory", "xp", "level")
# Belt-and-suspenders: never treat these runtime/registration calls as "sensitive",
# no matter what SENSITIVE_SUBSTR contains.
SENSITIVE_NEVER = {
    "AddEventHandler", "RemoveEventHandler", "RegisterNetEvent", "RegisterServerEvent",
    "RegisterCommand", "RegisterKeyMapping", "TriggerEvent", "TriggerServerEvent",
    "TriggerClientEvent", "CreateThread", "SetTick", "SetTimeout", "ClearTimeout",
}
RE_MYSQL = re.compile(r"\bMySQL\.[A-Za-z_]+\s*\(", re.IGNORECASE)
RE_OXMYSQL = re.compile(r"exports(?:\.|\[)['\"]?oxmysql['\"]?\]?\s*[:.][A-Za-z_]+\s*\(", re.IGNORECASE)

SUSPECT_PARAM_RE = re.compile(r"^(playerid|player_id|target|targetid|target_id|src|serverid|server_id)$", re.IGNORECASE)

ADMIN_NAME_SUBSTR = ("kick", "ban", "give", "money", "tp", "noclip", "god", "revive", "announce", "setjob", "admin", "weapon", "delete")

RE_REGISTER_COMMAND_TAIL = re.compile(r"\bend\s*,\s*false\s*\)")
RE_REGISTER_COMMAND_SIMPLE = re.compile(
    r"RegisterCommand\s*\(\s*(" + _STRING + r")\s*,\s*[A-Za-z_][\w.]*\s*,\s*false\s*\)"
)
RE_S006 = re.compile(
    r"(?<![.\w])(loadstring|dofile)\s*\(|\bos\.execute\s*\(|\bio\.popen\s*\(|(?<![.\w:])load\s*\("
)
RE_WAIT_OR_AWAIT = re.compile(r"\b(?:Citizen\.)?Wait\s*\(|\bCitizen\.Await\s*\(")
RE_SOURCE_TOKEN = re.compile(r"(?<!\.)\bsource\b")


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        return s[1:-1]
    return s


def _end(pf, frame) -> int:
    return frame.end_line if frame.end_line > 0 else pf.line_count()


def _server_net_handlers(pf, ctx) -> list:
    if pf.side != "server":
        return []
    return [f for f in pf.frames if f.is_handler and ctx.is_net_handler(f)]


def _sensitive_calls_in_line(line: str):
    hits = []
    for m in RE_ANY_CALL_NAME.finditer(line):
        name = m.group(1)
        if name in SENSITIVE_NEVER:
            continue
        low = name.lower()
        if name in SENSITIVE_EXACT or name.startswith("CreateVehicle"):
            hits.append(name)
        elif any(s in low for s in SENSITIVE_SUBSTR):
            hits.append(name)
    if RE_MYSQL.search(line) or RE_OXMYSQL.search(line):
        hits.append("MySQL/oxmysql query")
    return hits


def check_s001(pf, handlers) -> list:
    findings = []
    for f in handlers:
        body = pf.range_text(f.start_line, _end(pf, f))
        if not re.search(r"\bsource\b", body):
            findings.append(Finding(
                pf.rel_path, f.start_line, "S001", "warn",
                f"handler for '{f.handler_name}' never references 'source' -- not bound to the triggering player",
                "read 'source' to know (and validate) who sent this event",
            ))
    return findings


def check_s002(pf, handlers) -> list:
    findings = []
    for f in handlers:
        end = _end(pf, f)
        body = pf.range_text(f.start_line, end)
        if RE_VALIDATION.search(body):
            continue
        params = [p for p in f.params if p != "source"]
        for ln in range(f.start_line, end + 1):
            line = pf.code(ln)  # need real string content for the MySQL/oxmysql check
            hits = _sensitive_calls_in_line(line)
            if not hits:
                continue
            if params and not any(re.search(r"\b" + re.escape(p) + r"\b", line) for p in params):
                continue
            for name in hits:
                findings.append(Finding(
                    pf.rel_path, ln, "S002", "warn",
                    f"'{name}(...)' uses a client-supplied argument with no validation in this handler",
                    "check type/range/ownership/permission (if/assert/tonumber/type/#()/IsPlayerAceAllowed) before acting on event data",
                ))
    return findings


RE_PERMISSION_CALL = re.compile(
    r"\bIsPlayerAceAllowed\s*\("
    r"|\b(?:Is|Has|Can|Check)[A-Za-z]*(?:Police|Admin|Job|Permission|Allowed|Ace|Role|Duty|Group)\s*\("
    r"|\b(?:Jobs|Permissions|ACL)\.[A-Za-z_][A-Za-z0-9_]*\s*\("
)


def _param_type_checked(body: str, param: str) -> bool:
    return bool(re.search(
        r"\btype\s*\(\s*" + re.escape(param) + r"\b|\btonumber\s*\(\s*" + re.escape(param) + r"\b", body
    ))


def _param_guarded(body: str, param: str) -> bool:
    """A distance check, permission/role check, or existence check that reads
    on the parameter (directly, or via a `local ped = GetPlayerPed(param)`
    handle) somewhere in the handler body."""
    ped_of_param = bool(re.search(r"\bGetPlayerPed\s*\(\s*" + re.escape(param) + r"\s*\)", body))
    has_dist = bool(RE_DIST_CHECK.search(body))
    if has_dist and ped_of_param:
        return True
    if has_dist:
        for line in body.splitlines():
            if RE_DIST_CHECK.search(line) and re.search(r"\b" + re.escape(param) + r"\b", line):
                return True
    if RE_PERMISSION_CALL.search(body):
        return True
    if ped_of_param and (
        re.search(r"\bGetPlayerPed\s*\(\s*" + re.escape(param) + r"\s*\)\s*~=\s*0", body)
        or re.search(r"\bDoesEntityExist\s*\(", body)
    ):
        return True
    return False


def check_s003(pf, handlers) -> list:
    findings = []
    for f in handlers:
        suspects = [p for p in f.params if SUSPECT_PARAM_RE.match(p)]
        if not suspects:
            continue
        body = pf.range_text(f.start_line, _end(pf, f))
        # Per param: how many of {type-checked, guarded} hold anywhere in this
        # handler's body -- both -> fully validated (silent), one -> INFO,
        # neither -> WARN. Not line-ordered: a guard commonly reads a ped
        # handle (`local a, b = GetPlayerPed(src), GetPlayerPed(targetId)`)
        # fetched via the very call this rule is checking, so "the guard is
        # textually before every usage" isn't a meaningful requirement here.
        validated = {}
        for p in suspects:
            score = int(_param_type_checked(body, p)) + int(_param_guarded(body, p))
            validated[p] = score

        for ln in range(f.start_line, _end(pf, f) + 1):
            line = pf.clean(ln)
            for p in suspects:
                score = validated[p]
                if score >= 2:
                    continue  # type-checked AND guarded -- treat as validated
                level = "info" if score == 1 else "warn"
                suffix = "" if level == "warn" else \
                    " (partially validated -- only one of a type-check / permission-or-distance-guard is present)"
                if re.search(r"\b(GetPlayerPed|DropPlayer)\s*\(\s*" + re.escape(p) + r"\b", line):
                    findings.append(Finding(
                        pf.rel_path, ln, "S003", level,
                        f"uses parameter '{p}' as a player id straight from the event instead of 'source'{suffix}",
                        "trust 'source' for the caller; validate permission before acting on any other player id from the payload",
                    ))
                if re.search(r"\bTriggerClientEvent\s*\(\s*(?:" + _STRING + r")\s*,\s*" + re.escape(p) + r"\b", line):
                    findings.append(Finding(
                        pf.rel_path, ln, "S003", level,
                        f"TriggerClientEvent targets parameter '{p}' straight from the event instead of a validated id{suffix}",
                        "validate/permission-check before targeting a client with a payload-supplied player id",
                    ))
    return findings


def check_s004(pf, ctx) -> list:
    findings = []
    triggered = {n for _, n, _, _ in ctx.trigger_server if n} | {n for _, n, _, _ in ctx.trigger_client if n}
    for f in pf.frames:
        if f.handler_call not in ("RegisterNetEvent", "RegisterServerEvent", "onNet") or not f.handler_name:
            continue
        if f.handler_name in triggered:
            continue
        findings.append(Finding(
            pf.rel_path, f.start_line, "S004", "info",
            f"'{f.handler_name}' is registered as a net event but is never triggered over the network (TriggerServerEvent/TriggerClientEvent/emitNet) anywhere in this resource",
            "use a local AddEventHandler/TriggerEvent instead if this never needs to cross the network",
        ))
    # also cover RegisterNetEvent(name) with no inline callback (frame not created)
    for i, line in enumerate(pf.code_lines, start=1):
        for m in re.finditer(r"\b(RegisterNetEvent|RegisterServerEvent)\s*\(\s*(" + _STRING + r")\s*\)", line):
            name = _strip_quotes(m.group(2))
            if name and name not in triggered and not any(
                f.handler_name == name and f.start_line == i for f in pf.frames
            ):
                findings.append(Finding(
                    pf.rel_path, i, "S004", "info",
                    f"'{name}' is registered as a net event but is never triggered over the network anywhere in this resource",
                    "use a local AddEventHandler/TriggerEvent instead if this never needs to cross the network",
                ))
    return findings


def check_s005(pf) -> list:
    if pf.side != "server":
        return []
    findings = []
    seen_lines = set()
    for f in pf.frames:
        if f.handler_call != "RegisterCommand" or not f.handler_name:
            continue
        end = _end(pf, f)
        if not any(s in f.handler_name.lower() for s in ADMIN_NAME_SUBSTR):
            continue
        if RE_REGISTER_COMMAND_TAIL.search(pf.clean(end)):
            findings.append(Finding(
                pf.rel_path, f.start_line, "S005", "warn",
                f"RegisterCommand('{f.handler_name}', ..., false) -- admin-looking command registered unrestricted",
                "register with restricted=true and grant it via an ACE permission instead of false",
            ))
            seen_lines.add(f.start_line)
    for i, line in enumerate(pf.code_lines, start=1):
        if i in seen_lines:
            continue
        m = RE_REGISTER_COMMAND_SIMPLE.search(line)
        if not m:
            continue
        name = _strip_quotes(m.group(1))
        if any(s in name.lower() for s in ADMIN_NAME_SUBSTR):
            findings.append(Finding(
                pf.rel_path, i, "S005", "warn",
                f"RegisterCommand('{name}', ..., false) -- admin-looking command registered unrestricted",
                "register with restricted=true and grant it via an ACE permission instead of false",
            ))
    return findings


def check_s006(pf) -> list:
    findings = []
    for i, line in enumerate(pf.clean_lines, start=1):
        if RE_S006.search(line):
            findings.append(Finding(
                pf.rel_path, i, "S006", "warn",
                "dynamic code execution / shell access call found",
                "avoid load/loadstring/dofile/os.execute/io.popen in resource scripts -- arbitrary code execution risk",
            ))
    return findings


def check_s007(pf, ctx) -> list:
    findings = []
    # names handled anywhere on that side (AddEventHandler/on, or a RegisterNetEvent/
    # RegisterServerEvent/onNet call with an inline callback -- see ctx.handled_names)
    server_handled = {n for side, n in ctx.handled_names if side == "server"}
    client_handled = {n for side, n in ctx.handled_names if side == "client"}

    if pf.side == "client":
        for i, line in enumerate(pf.code_lines, start=1):
            for m in re.finditer(r"\bTriggerServerEvent\s*\(\s*(" + _STRING + r")", line):
                name = _strip_quotes(m.group(1))
                if name and name not in server_handled and name not in ctx.net_event_names:
                    findings.append(Finding(
                        pf.rel_path, i, "S007", "info",
                        f"TriggerServerEvent('{name}', ...) has no matching server handler in this resource (probably fine if another resource handles it)",
                        "double-check the event name, or confirm another resource registers a handler for it",
                    ))
    if pf.side == "server":
        for i, line in enumerate(pf.code_lines, start=1):
            for m in re.finditer(r"\bTriggerClientEvent\s*\(\s*(" + _STRING + r")", line):
                name = _strip_quotes(m.group(1))
                if name and name not in client_handled:
                    findings.append(Finding(
                        pf.rel_path, i, "S007", "info",
                        f"TriggerClientEvent(..., '{name}', ...) has no matching client handler in this resource (probably fine if another resource handles it)",
                        "double-check the event name, or confirm another resource registers a handler for it",
                    ))
    return findings


def check_s008(pf, handlers) -> list:
    findings = []
    for f in handlers:
        end = _end(pf, f)
        body = pf.range_text(f.start_line, end)
        if RE_TYPE_CHECK_ONLY.search(body):
            continue
        params = [p for p in f.params if p != "source"]
        if not params:
            continue
        for ln in range(f.start_line, end + 1):
            line = pf.clean(ln)
            hit = None
            for p in params:
                if re.search(r"\b" + re.escape(p) + r"\s*\[", line) or \
                   re.search(r"\b" + re.escape(p) + r"\s*[+\-*/]", line) or \
                   re.search(r"[+\-*/]\s*" + re.escape(p) + r"\b", line):
                    hit = p
                    break
            if hit:
                findings.append(Finding(
                    pf.rel_path, ln, "S008", "warn",
                    f"'{hit}' is used as a table index/number with no type check (type/tonumber/assert) in this handler",
                    "validate with type(...)/tonumber(...) before indexing or doing arithmetic on event arguments",
                ))
                break  # one finding per handler is enough
    return findings


def check_s009(pf, handlers) -> list:
    findings = []
    for f in handlers:
        end = _end(pf, f)
        body = pf.range_text(f.start_line, end)
        if RE_DIST_CHECK.search(body):
            continue
        params = [p for p in f.params if p != "source"]
        for ln in range(f.start_line, end + 1):
            line = pf.clean(ln)
            m = re.search(r"\b(SetEntityCoords|SetPedIntoVehicle)\s*\(([^()]*)\)", line)
            if not m:
                continue
            args = m.group(2)
            if params and not any(re.search(r"\b" + re.escape(p) + r"\b", args) for p in params):
                continue
            findings.append(Finding(
                pf.rel_path, ln, "S009", "warn",
                f"{m.group(1)}(...) uses client-supplied data with no distance check in this handler",
                "check the target is within a sane distance (#(a-b) < N, GetDistanceBetweenCoords, or Vdist) before teleporting/seating",
            ))
    return findings


def check_s010(pf, handlers) -> list:
    """'source' is reset once the handler coroutine yields past the first
    Wait()/Citizen.Wait()/Citizen.Await() -- so reading it again afterwards is
    reading a potentially-stale value. See DESIGN.md section 8."""
    if pf.lang != "lua":
        return []
    findings = []
    for f in handlers:
        end = _end(pf, f)
        wait_line = None
        for ln in range(f.start_line, end + 1):
            line = pf.clean(ln)
            if wait_line is None:
                if RE_WAIT_OR_AWAIT.search(line):
                    wait_line = ln
                continue
            if RE_SOURCE_TOKEN.search(line):
                findings.append(Finding(
                    pf.rel_path, ln, "S010", "warn",
                    "'source' is read after a Wait()/Citizen.Wait()/Citizen.Await() in this handler -- it resets once the coroutine yields, so this may be stale",
                    "capture it first: 'local src = source' as the handler's very first statement, then use 'src' from then on",
                ))
                break  # one finding per handler
    return findings


def run(pf, ctx) -> list:
    handlers = _server_net_handlers(pf, ctx)
    findings = []
    findings += check_s001(pf, handlers)
    findings += check_s002(pf, handlers)
    findings += check_s003(pf, handlers)
    findings += check_s004(pf, ctx)
    findings += check_s005(pf)
    findings += check_s006(pf)
    findings += check_s007(pf, ctx)
    findings += check_s008(pf, handlers)
    findings += check_s009(pf, handlers)
    findings += check_s010(pf, handlers)
    return [f for f in findings if not pf.is_suppressed(f.line, f.rule)]
