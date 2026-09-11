"""Cross-file facts for a whole resource: which event names are registered
net-safe, which are triggered from which side, which names are referenced as
exports/callbacks. Built once per `fxlint` run and shared by rules_sec.py /
rules_style.py so S004/S007/C006/C010/C003 can reason across files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_STRING = r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""

RE_REGISTER_NET = re.compile(r"\b(RegisterNetEvent|RegisterServerEvent)\s*\(\s*(" + _STRING + r")")
RE_ADD_HANDLER = re.compile(r"\bAddEventHandler\s*\(\s*(" + _STRING + r")\s*,")
RE_TRIGGER_SERVER = re.compile(r"\bTriggerServerEvent\s*\(\s*(" + _STRING + r")")
RE_TRIGGER_CLIENT = re.compile(r"\bTriggerClientEvent\s*\(\s*(" + _STRING + r")")
RE_TRIGGER_LOCAL = re.compile(r"\bTriggerEvent\s*\(\s*(" + _STRING + r")")
RE_ON = re.compile(r"\bon\s*\(\s*(" + _STRING + r")\s*,")
RE_ONNET = re.compile(r"\bonNet\s*\(\s*(" + _STRING + r")\s*,")
RE_EMIT = re.compile(r"\bemit\s*\(\s*(" + _STRING + r")")
RE_EMITNET = re.compile(r"\bemitNet\s*\(\s*(" + _STRING + r")")
RE_EXPORTS_CALL = re.compile(r"\bexports\s*\(\s*(?:" + _STRING + r")\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)")
RE_CALLBACK_REF = re.compile(
    r"\b(?:AddEventHandler|RegisterNetEvent|RegisterServerEvent|RegisterCommand|RegisterKeyMapping|"
    r"SetTick|setTick|on|onNet)\s*\([^()]*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*[,)]"
)


def _lit(s) -> "str | None":
    if s is None:
        return None
    s = s.strip()
    if len(s) >= 2 and s[0] in "'\"" and s[-1] == s[0]:
        return s[1:-1]
    return None


@dataclass
class ResourceContext:
    net_event_names: set = field(default_factory=set)
    add_handler: list = field(default_factory=list)      # (side, name, path, line)
    trigger_server: list = field(default_factory=list)   # (side, name, path, line)
    trigger_client: list = field(default_factory=list)   # (side, name, path, line)
    trigger_local: list = field(default_factory=list)    # (side, name, path, line)
    handled_names: set = field(default_factory=set)      # (side, name) for every is_handler frame, any call style
    defined_names: set = field(default_factory=set)
    callback_or_export_refs: set = field(default_factory=set)
    dependencies: set = field(default_factory=set)

    def is_net_handler(self, frame) -> bool:
        if frame.handler_call in ("RegisterNetEvent", "RegisterServerEvent", "onNet"):
            return True
        return bool(frame.handler_name and frame.handler_name in self.net_event_names)


def collect_file_facts(pf) -> dict:
    facts = dict(
        net_event_names=set(), add_handler=[], trigger_server=[], trigger_client=[],
        trigger_local=[], callback_or_export_refs=set(),
    )
    # code_lines (comments blanked, strings kept) -- these regexes need the actual
    # string content (event names), unlike most of the structural rules elsewhere.
    for i, line in enumerate(pf.code_lines, start=1):
        for m in RE_REGISTER_NET.finditer(line):
            name = _lit(m.group(2))
            if name:
                facts["net_event_names"].add(name)
        for m in RE_ONNET.finditer(line):
            name = _lit(m.group(1))
            if name:
                facts["net_event_names"].add(name)
        for m in RE_ADD_HANDLER.finditer(line):
            facts["add_handler"].append((pf.side, _lit(m.group(1)), pf.rel_path, i))
        for m in RE_ON.finditer(line):
            facts["add_handler"].append((pf.side, _lit(m.group(1)), pf.rel_path, i))
        for m in RE_TRIGGER_SERVER.finditer(line):
            facts["trigger_server"].append((pf.side, _lit(m.group(1)), pf.rel_path, i))
        for m in RE_TRIGGER_CLIENT.finditer(line):
            facts["trigger_client"].append((pf.side, _lit(m.group(1)), pf.rel_path, i))
        for m in RE_TRIGGER_LOCAL.finditer(line):
            facts["trigger_local"].append((pf.side, _lit(m.group(1)), pf.rel_path, i))
        for m in RE_EMITNET.finditer(line):
            name = _lit(m.group(1))
            bucket = "trigger_server" if pf.side == "client" else "trigger_client"
            facts[bucket].append((pf.side, name, pf.rel_path, i))
        for m in RE_EMIT.finditer(line):
            facts["trigger_local"].append((pf.side, _lit(m.group(1)), pf.rel_path, i))

    text = "\n".join(pf.code_lines)
    for m in RE_EXPORTS_CALL.finditer(text):
        facts["callback_or_export_refs"].add(m.group(1))
    for m in RE_CALLBACK_REF.finditer(text):
        facts["callback_or_export_refs"].add(m.group(1))
    return facts


def build_context(parsed_files: list, defined_names: set, dependencies: set) -> ResourceContext:
    ctx = ResourceContext(defined_names=set(defined_names), dependencies=set(dependencies))
    for pf in parsed_files:
        facts = collect_file_facts(pf)
        ctx.net_event_names |= facts["net_event_names"]
        ctx.add_handler.extend(facts["add_handler"])
        ctx.trigger_server.extend(facts["trigger_server"])
        ctx.trigger_client.extend(facts["trigger_client"])
        ctx.trigger_local.extend(facts["trigger_local"])
        ctx.callback_or_export_refs |= facts["callback_or_export_refs"]
        for f in pf.frames:
            if f.is_handler and f.handler_name:
                ctx.handled_names.add((pf.side, f.handler_name))
    return ctx
