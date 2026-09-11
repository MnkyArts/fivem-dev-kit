"""Text + JSON rendering for every `fxref` read command."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from fxkit import util

_APISET_ORDER = {"client": 0, "server": 1, "shared": 2}


def row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for k in ("aliases", "params", "examples"):
        if d.get(k):
            try:
                d[k] = json.loads(d[k])
            except (TypeError, ValueError):
                pass
    d.pop("name_tokens", None)
    d.pop("alias_tokens", None)
    d.pop("param_text", None)
    return d


def sort_matches(rows: list[sqlite3.Row]) -> list[sqlite3.Row]:
    return sorted(rows, key=lambda r: (_APISET_ORDER.get(r["apiset"], 9), r["hash"]))


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------
def _availability_tag(row: sqlite3.Row) -> str | None:
    if row["in_legacy"] and row["in_gen9"]:
        return "legacy+gen9"
    if row["in_legacy"]:
        return "legacy"
    if row["in_gen9"]:
        return "gen9"
    return None


def _bracket(row: sqlite3.Row) -> str:
    parts = [row["ns"] or "?", row["apiset"]]
    if row["build"]:
        parts.append(f"build {row['build']}")
    avail = _availability_tag(row)
    if avail:
        parts.append(avail)
    return "[" + ", ".join(parts) + "]"


def render_search_line(row: sqlite3.Row, exact: bool) -> str:
    tag = " (exact)" if exact else ""
    desc = util.first_sentence(row["description"], 110)
    line = f"{row['name']}{tag}  {_bracket(row)}  Lua: {row['lua_signature']}"
    if desc:
        line += f"  -- {desc}"
    return line


def search_result_to_json(entry: dict[str, Any]) -> dict[str, Any]:
    d = row_to_dict(entry["row"])
    d["exact"] = entry["exact"]
    return d


# ---------------------------------------------------------------------------
# show
# ---------------------------------------------------------------------------
def render_show_card(row: sqlite3.Row) -> str:
    lines: list[str] = []
    name_line = row["name"]
    if row["unofficial"]:
        name_line += "  (unofficial name)"
    lines.append(f"=== {name_line} ===")

    hash_line = f"hash: {row['hash']}"
    if row["jhash"] and row["jhash"] != row["hash"]:
        hash_line += f"   jhash: {row['jhash']}"
    lines.append(hash_line)

    ns_line = f"ns: {row['ns'] or '?'}"
    if row["ns_alt"]:
        ns_line += f"  (alt: {row['ns_alt']})"
    lines.append(ns_line)
    lines.append(f"apiset: {row['apiset']}")

    build_bits = []
    if row["build"]:
        build_bits.append(f"build {row['build']} (legacy)")
    if row["build_gen9"]:
        build_bits.append(f"build {row['build_gen9']} (gen9)")
    avail = _availability_tag(row)
    if build_bits:
        lines.append("build: " + ", ".join(build_bits))
    elif avail:
        lines.append("build: " + avail)
    if row["unused"]:
        lines.append("** marked unused (alloc8or) **")

    aliases = json.loads(row["aliases"] or "[]")
    if aliases:
        lines.append("aliases: " + ", ".join(aliases))

    lines.append("")
    lines.append("C:   " + (row["c_signature"] or ""))
    lines.append("Lua: " + (row["lua_signature"] or ""))
    lines.append("JS:  " + (row["js_signature"] or ""))
    lines.append("C#:  " + (row["cs_signature"] or ""))

    if row["description"]:
        lines.append("")
        lines.append(row["description"])
    if row["comment_alloc8or"]:
        lines.append("")
        lines.append("alloc8or comment: " + row["comment_alloc8or"])

    params = json.loads(row["params"] or "[]")
    if params:
        lines.append("")
        lines.append("Parameters:")
        for p in params:
            ptr = " (out)" if p.get("pointer") else ""
            desc = f" -- {p['description']}" if p.get("description") else ""
            lines.append(f"  {p['type']} {p['name']}{ptr}{desc}")

    if row["results_description"]:
        lines.append("")
        lines.append("Returns: " + row["results_description"])

    examples = json.loads(row["examples"] or "[]")
    if examples:
        lines.append("")
        lines.append("Examples:")
        for ex in examples:
            lines.append(f"  [{ex.get('lang', '?')}]")
            for line in (ex.get("code") or "").splitlines():
                lines.append("    " + line)

    lines.append("")
    lines.append("url: " + (row["url"] or ""))
    lines.append("source: " + (row["source"] or ""))

    if len(lines) > 80:
        lines = lines[:79] + ["... (truncated; use --json for full output)"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------
def render_resolve_line(identifier: str, rows: list[sqlite3.Row]) -> str:
    if not rows:
        return f"MISSING {identifier}"
    rows = sort_matches(rows)
    apisets: list[str] = []
    for r in rows:
        if r["apiset"] not in apisets:
            apisets.append(r["apiset"])
    primary = rows[0]
    return (
        f"FOUND name={primary['name']} lua={primary['lua_name']} "
        f"hash={primary['hash']} apiset={'+'.join(apisets)} ns={primary['ns'] or '?'}"
    )


def resolve_to_json(identifier: str, rows: list[sqlite3.Row]) -> dict[str, Any]:
    rows = sort_matches(rows)
    return {
        "input": identifier,
        "found": bool(rows),
        "matches": [
            {
                "name": r["name"],
                "lua_name": r["lua_name"],
                "hash": r["hash"],
                "apiset": r["apiset"],
                "ns": r["ns"],
            }
            for r in rows
        ],
    }


# ---------------------------------------------------------------------------
# docs
# ---------------------------------------------------------------------------
_HEADING_LINE_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def extract_section(body: str, heading: str) -> str | None:
    lines = body.splitlines()
    start = None
    level = None
    target = heading.strip().lower()
    for i, line in enumerate(lines):
        m = _HEADING_LINE_RE.match(line)
        if m and m.group(2).strip().lower() == target:
            start = i
            level = len(m.group(1))
            break
    if start is None:
        return None
    end = len(lines)
    for j in range(start + 1, len(lines)):
        m = _HEADING_LINE_RE.match(lines[j])
        if m and len(m.group(1)) <= level:
            end = j
            break
    return "\n".join(lines[start:end]).strip()


def render_docs_show(row: sqlite3.Row, section: str | None = None, raw: bool = False) -> str:
    body = row["body"] or ""
    if section:
        extracted = extract_section(body, section)
        body = extracted if extracted is not None else f"(no such section: {section!r})"
    if raw:
        return body
    header = f"# {row['title']}\n{row['url']}\n"
    return header + "\n" + body


def render_docs_ls_line(row: sqlite3.Row) -> str:
    return f"{row['path']} — {row['title']}"


def render_docs_search_line(entry: dict[str, Any]) -> str:
    d = entry["doc"]
    snippet = (entry.get("snippet") or "").replace("\n", " ").strip()
    return f"{d['path']}  [{d['section'] or '-'}]  {d['title']}  — {snippet}"


def docs_search_to_json(entry: dict[str, Any]) -> dict[str, Any]:
    d = dict(entry["doc"])
    return {
        "id": d["path"],
        "url": d["url"],
        "title": d["title"],
        "section": d["section"],
        "snippet": entry.get("snippet"),
    }
