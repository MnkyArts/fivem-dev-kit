"""Build the merged `natives` rows from the four sources (DESIGN.md section 2).

Sources:
  1. alloc8or natives.json       (legacy / GTA V "Legacy")
  2. alloc8or natives_gen9.json  (GTA V Enhanced)
  3. FiveM natives.json          (docs.fivem.net data, downloaded/cached)
  4. CFX native-decls/*.md       (canonical CFX natives), with natives_cfx.json
     as a fallback for any CFX native missing a .md file.

GTA natives (1-3) are merged by hash into apiset='client' rows. CFX natives (4)
keep their own declared apiset (client/server/shared) -- so the same C name
can legitimately produce two rows (e.g. SetEntityCoords: a client GTA native
*and* a CFX server RPC native), which is intentional (see DESIGN.md).
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from fxkit import names, util

HASH_PLACEHOLDER_RE = re.compile(r"^_0x[0-9A-Fa-f]+$")


# ---------------------------------------------------------------------------
# Loading raw sources
# ---------------------------------------------------------------------------
def _flatten(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """NS -> hash -> entry  =>  norm_hash -> entry (entry gains 'ns')."""
    out: dict[str, dict[str, Any]] = {}
    for ns, natives in raw.items():
        for h, n in natives.items():
            try:
                key = util.norm_hash(h, width=16)
            except ValueError:
                continue
            entry = dict(n)
            entry["ns"] = ns
            out[key] = entry
    return out


def load_legacy(path: Path) -> dict[str, dict[str, Any]]:
    return _flatten(util.read_json(path))


def load_gen9(path: Path) -> dict[str, dict[str, Any]]:
    return _flatten(util.read_json(path))


def load_fivem(path: Path) -> dict[str, dict[str, Any]]:
    return _flatten(util.read_json(path))


def load_cfx_json(path: Path) -> dict[str, Any]:
    return util.read_json(path)


# ---------------------------------------------------------------------------
# Row assembly (shared by GTA + CFX paths)
# ---------------------------------------------------------------------------
def finalize_row(
    *,
    name: str,
    ns: str | None,
    ns_alt: str | None,
    apiset: str,
    unofficial: bool | int,
    aliases: list[str],
    params: list[dict[str, Any]],
    return_type_raw: str | None,
    results_description: str | None,
    description: str,
    comment_alloc8or: str | None,
    examples: list[dict[str, str]],
    build: str | None,
    build_gen9: str | None,
    in_legacy: bool | int,
    in_gen9: bool | int,
    unused: bool | int,
    hash_str: str,
    jhash_str: str | None,
    source: str,
    c_signature_override: str | None = None,
) -> dict[str, Any]:
    lnm = names.lua_name(name)
    sigs = names.build_signatures(name, lnm, params, return_type_raw)
    if c_signature_override:
        sigs["c_signature"] = c_signature_override

    name_tok = " ".join(names.name_words(name) + [lnm])
    alias_words: list[str] = []
    for a in aliases:
        alias_words.extend(names.name_words(a))
        alias_words.append(names.lua_name(a))
    alias_tok = " ".join(alias_words)
    param_text = " ".join(f"{p['name']} {p['base']}" for p in params)

    return {
        "hash": hash_str,
        "jhash": jhash_str,
        "name": name,
        "lua_name": lnm,
        "ns": ns,
        "ns_alt": ns_alt,
        "apiset": apiset,
        "unofficial": int(bool(unofficial)),
        "aliases": json.dumps(aliases, ensure_ascii=False),
        "params": json.dumps(params, ensure_ascii=False),
        "return_type": return_type_raw,
        "results_description": results_description,
        "description": description or "",
        "comment_alloc8or": comment_alloc8or,
        "examples": json.dumps(examples, ensure_ascii=False),
        "build": build,
        "build_gen9": build_gen9,
        "in_legacy": int(bool(in_legacy)),
        "in_gen9": int(bool(in_gen9)),
        "unused": int(bool(unused)),
        "url": f"https://docs.fivem.net/natives/?_{hash_str}",
        "source": source,
        "c_signature": sigs["c_signature"],
        "lua_signature": sigs["lua_signature"],
        "js_signature": sigs["js_signature"],
        "cs_signature": sigs["cs_signature"],
        "name_tokens": name_tok,
        "alias_tokens": alias_tok,
        "param_text": param_text,
    }


def name_forms_for_row(name: str, lua_nm: str, hash_str: str, jhash_str: str | None, aliases: list[str]) -> set[str]:
    forms = {name.lower(), lua_nm.lower(), names.lower_camel(lua_nm).lower()}
    forms.add(hash_str.lower())
    forms.add(hash_str.lower().replace("0x", ""))
    if jhash_str:
        forms.add(jhash_str.lower())
        forms.add(jhash_str.lower().replace("0x", ""))
    for a in aliases:
        if not a:
            continue
        forms.add(a.lower())
        aln = names.lua_name(a)
        forms.add(aln.lower())
        forms.add(names.lower_camel(aln).lower())
    return {f for f in forms if f}


def _dedupe_aliases(raw_aliases: list[str] | None, name: str, hash_str: str) -> list[str]:
    out = {a for a in (raw_aliases or []) if a}
    out.add(hash_str)
    out.discard(name)
    return sorted(out)


# ---------------------------------------------------------------------------
# GTA natives merge (sources 1-3)
# ---------------------------------------------------------------------------
def _enrich_params(params: list[dict[str, Any]], fivem_params: list[dict[str, Any]]) -> None:
    by_name = {p["name"]: p for p in fivem_params if p.get("name")}
    by_name_lower = {p["name"].lower(): p for p in fivem_params if p.get("name")}
    for i, p in enumerate(params):
        src = by_name.get(p["name"]) or by_name_lower.get(p["name"].lower())
        if not src and i < len(fivem_params):
            src = fivem_params[i]
        if src and src.get("description"):
            p["description"] = src["description"]


def build_gta_rows(
    legacy: dict[str, dict[str, Any]],
    gen9: dict[str, dict[str, Any]],
    fivem: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    rows = []
    all_hashes = set(legacy) | set(gen9) | set(fivem)

    for h in sorted(all_hashes):
        leg = legacy.get(h)
        g9 = gen9.get(h)
        fv = fivem.get(h)
        alloc = leg or g9

        alloc_ns = alloc.get("ns") if alloc else None
        fivem_ns = fv.get("ns") if fv else None

        alloc_name = alloc.get("name") if alloc else None
        fivem_name = fv.get("name") if fv else None
        fivem_real = bool(fivem_name) and not HASH_PLACEHOLDER_RE.match(fivem_name.lstrip("_"))
        if fivem_real:
            # The FiveM runtime generates the Lua/JS functions from natives.json (name + aliases),
            # so ITS name is the one that exists inside a script. A newer nativedb rename
            # (SET_PED_MICRO_MORPH vs the runtime's _SET_PED_FACE_FEATURE) is kept as an alias
            # below; printing it as canonical made agents call functions that do not exist.
            if fivem_name.startswith("_"):
                name = fivem_name[1:]
                unofficial = True
            else:
                name = fivem_name
                unofficial = False
        elif alloc_name and not HASH_PLACEHOLDER_RE.match(alloc_name):
            name = alloc_name
            unofficial = False
        else:
            name = f"_{h}"
            unofficial = False
        if not name:
            continue

        ns = fivem_ns or alloc_ns
        ns_alt = alloc_ns if (fivem_ns and alloc_ns and fivem_ns != alloc_ns) else None

        if alloc:
            params = [names.build_param(p["name"], p["type"]) for p in alloc.get("params") or []]
            return_type_raw = alloc.get("return_type")
        else:
            params = [
                names.build_param(p.get("name", ""), p.get("type", "int"), p.get("description"))
                for p in (fv.get("params") if fv else []) or []
            ]
            return_type_raw = (fv.get("results") if fv else None) or "void"

        if alloc and fv:
            _enrich_params(params, fv.get("params") or [])

        fivem_desc = (fv.get("description") or "").strip() if fv else ""
        alloc_comment = (alloc.get("comment") or "").strip() if alloc else ""
        if fivem_desc:
            description = fivem_desc
            comment_alloc8or = alloc_comment if (alloc_comment and alloc_comment != fivem_desc) else None
        else:
            description = alloc_comment
            comment_alloc8or = None

        aliases: set[str] = set()
        if fv and fv.get("aliases"):
            aliases.update(a for a in fv["aliases"] if a)
        if alloc and alloc.get("old_names"):
            aliases.update(a for a in alloc["old_names"] if a)
        if fv and fv.get("name") and fv["name"] != name:
            fn = fv["name"]
            if fn.startswith("_"):
                fn = fn[1:]
            if fn and fn != name:
                aliases.add(fn)
        if alloc_name and alloc_name != name and not HASH_PLACEHOLDER_RE.match(alloc_name):
            aliases.add(alloc_name)   # the nativedb's (newer) name stays searchable
        aliases.add(h)
        aliases.discard(name)

        jhash = None
        if alloc and alloc.get("jhash"):
            jhash = util.norm_hash(alloc["jhash"], width=8)
        elif fv and fv.get("jhash"):
            jhash = util.norm_hash(fv["jhash"], width=8)

        build = leg.get("build") if leg else None
        build_gen9 = g9.get("build") if g9 else None
        in_legacy = bool(leg)
        in_gen9 = bool(g9)
        unused = bool(leg and leg.get("unused"))

        examples = (fv.get("examples") if fv else []) or []

        source_list = []
        if leg:
            source_list.append("alloc8or-legacy")
        if g9:
            source_list.append("alloc8or-gen9")
        if fv:
            source_list.append("fivem-json")

        row = finalize_row(
            name=name,
            ns=ns,
            ns_alt=ns_alt,
            apiset="client",
            unofficial=unofficial,
            aliases=sorted(aliases),
            params=params,
            return_type_raw=return_type_raw,
            results_description=(fv.get("resultsDescription") if fv else None),
            description=description,
            comment_alloc8or=comment_alloc8or,
            examples=examples,
            build=build,
            build_gen9=build_gen9,
            in_legacy=in_legacy,
            in_gen9=in_gen9,
            unused=unused,
            hash_str=h,
            jhash_str=jhash,
            source=",".join(source_list),
        )
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# CFX natives (native-decls/*.md, with natives_cfx.json fallback)
# ---------------------------------------------------------------------------
_FRONT_MATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$", re.M)
_FENCE_RE = re.compile(r"```([a-zA-Z0-9_+-]*)[ \t]*\r?\n(.*?)```", re.S)
_BULLET_RE = re.compile(r"^\s*[-*]\s+\*\*([^*]+)\*\*:?\s*(.*)$")


def _parse_decl_front_matter(text: str) -> tuple[dict[str, Any], str]:
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, Any] = {}
    for raw_line in m.group(1).splitlines():
        line = raw_line.rstrip("\r").rstrip()
        if not line.strip() or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if key == "aliases":
            try:
                fm[key] = json.loads(val)
            except (json.JSONDecodeError, ValueError):
                fm[key] = [x.strip().strip("\"'") for x in val.strip("[]").split(",") if x.strip()]
        else:
            fm[key] = val.strip("\"'")
    return fm, text[m.end() :]


def _split_sections(body: str) -> tuple[str | None, dict[str, str]]:
    matches = list(_HEADING_RE.finditer(body))
    if not matches:
        return None, {}
    sections: dict[str, str] = {}
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections[title.lower()] = body[start:end].strip()
    return matches[0].group(1).strip(), sections


def _parse_c_signature(text: str) -> tuple[str, str, list[dict[str, str]]] | None:
    t = text.strip()
    if t.endswith(";"):
        t = t[:-1].strip()
    if "(" not in t or ")" not in t:
        return None
    open_idx = t.index("(")
    close_idx = t.rfind(")")
    if close_idx < open_idx:
        return None
    head = t[:open_idx].strip()
    args_str = t[open_idx + 1 : close_idx].strip()
    m = re.match(r"^(?P<ret>.*?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)$", head)
    if not m:
        return None
    ret = m.group("ret").strip()
    fn_name = m.group("name")
    params: list[dict[str, str]] = []
    if args_str and args_str.lower() != "void":
        for part in args_str.split(","):
            part = part.strip()
            if not part:
                continue
            pm = re.match(r"^(?P<type>.*?)(?P<name>[A-Za-z_][A-Za-z0-9_]*)$", part)
            if not pm or not pm.group("type").strip():
                continue
            params.append({"type": pm.group("type").strip(), "name": pm.group("name")})
    return ret, fn_name, params


def _parse_param_bullets(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []

    def flush() -> None:
        if current is not None:
            result[current] = " ".join(buf).strip()

    for line in text.splitlines():
        m = _BULLET_RE.match(line)
        if m:
            flush()
            current = m.group(1).strip()
            buf = [m.group(2).strip()] if m.group(2).strip() else []
        elif current is not None and line.strip():
            buf.append(line.strip())
    flush()
    return result


def parse_decl_md(path: Path) -> dict[str, Any] | None:
    raw = path.read_text(encoding="utf-8", errors="replace")
    fm, body = _parse_decl_front_matter(raw)

    game = fm.get("game")
    if game and game.strip().lower() != "gta5":
        return None

    name_heading, sections = _split_sections(body)
    if not name_heading:
        return None
    name = name_heading.strip()
    name_body = sections.get(name.lower(), "")

    fence = _FENCE_RE.search(name_body)
    c_sig_raw = None
    return_type_raw = None
    params_from_sig: list[dict[str, str]] = []
    if fence:
        c_sig_raw = fence.group(2).strip()
        parsed_sig = _parse_c_signature(c_sig_raw)
        if parsed_sig:
            return_type_raw, _sig_name, params_from_sig = parsed_sig
        description = name_body[fence.end() :].strip()
    else:
        description = name_body.strip()

    param_descs = _parse_param_bullets(sections["parameters"]) if "parameters" in sections else {}
    params = [
        names.build_param(p["name"], p["type"], param_descs.get(p["name"]) or param_descs.get(p["name"].lower()))
        for p in params_from_sig
    ]

    results_description = None
    for key in ("return value", "return values", "returns"):
        if key in sections and sections[key].strip():
            results_description = sections[key].strip()
            break

    examples: list[dict[str, str]] = []
    ex_section = sections.get("examples") or sections.get("example")
    if ex_section:
        for m in _FENCE_RE.finditer(ex_section):
            lang = (m.group(1) or "text").strip().lower()
            code = m.group(2).strip("\n")
            if code.strip():
                examples.append({"lang": lang, "code": code})

    h = util.joaat(name)
    hash_str = f"0x{h:08X}"

    return {
        "name": name,
        "ns": fm.get("ns") or "CFX",
        "apiset": (fm.get("apiset") or "client").strip().lower(),
        "aliases": fm.get("aliases") or [],
        "description": description.strip(),
        "params": params,
        "return_type_raw": return_type_raw,
        "results_description": results_description,
        "examples": examples,
        "hash": hash_str,
        "jhash": hash_str,
        "c_signature": (c_sig_raw.rstrip(";").strip() if c_sig_raw else None),
    }


def row_from_decl(parsed: dict[str, Any]) -> dict[str, Any]:
    return finalize_row(
        name=parsed["name"],
        ns=parsed["ns"],
        ns_alt=None,
        apiset=parsed["apiset"],
        unofficial=False,
        aliases=_dedupe_aliases(parsed["aliases"], parsed["name"], parsed["hash"]),
        params=parsed["params"],
        return_type_raw=parsed["return_type_raw"],
        results_description=parsed["results_description"],
        description=parsed["description"],
        comment_alloc8or=None,
        examples=parsed["examples"],
        build=None,
        build_gen9=None,
        in_legacy=False,
        in_gen9=False,
        unused=False,
        hash_str=parsed["hash"],
        jhash_str=parsed["jhash"],
        source="native-decls",
        c_signature_override=parsed.get("c_signature"),
    )


def row_from_cfx_json(hash_key: str, entry: dict[str, Any]) -> dict[str, Any] | None:
    game = entry.get("game")
    if game and str(game).strip().lower() != "gta5":
        return None
    name = entry.get("name")
    if not name:
        return None
    params = [
        names.build_param(p.get("name", ""), p.get("type", "int"), p.get("description"))
        for p in entry.get("params") or []
    ]
    return_type_raw = entry.get("results") or "void"
    hash_str = util.norm_hash(entry.get("hash") or hash_key, width=8)
    jhash_str = util.norm_hash(entry["jhash"], width=8) if entry.get("jhash") else hash_str
    return finalize_row(
        name=name,
        ns=entry.get("ns") or "CFX",
        ns_alt=None,
        apiset=(entry.get("apiset") or "client").lower(),
        unofficial=False,
        aliases=_dedupe_aliases(entry.get("aliases"), name, hash_str),
        params=params,
        return_type_raw=return_type_raw,
        results_description=entry.get("resultsDescription"),
        description=entry.get("description") or "",
        comment_alloc8or=None,
        examples=entry.get("examples") or [],
        build=None,
        build_gen9=None,
        in_legacy=False,
        in_gen9=False,
        unused=False,
        hash_str=hash_str,
        jhash_str=jhash_str,
        source="natives_cfx.json",
    )


def build_cfx_rows(decls_dir: Path, cfx_json: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = []
    seen_names: set[str] = set()
    stats = {"decls_total": 0, "decls_kept": 0, "decls_excluded_game": 0, "decls_unparsed": 0, "fallback_used": 0}

    for path in sorted(decls_dir.glob("*.md")):
        stats["decls_total"] += 1
        try:
            parsed = parse_decl_md(path)
        except Exception:
            parsed = None
        if parsed is None:
            fm_game = None
            try:
                fm_game, _ = _parse_decl_front_matter(path.read_text(encoding="utf-8", errors="replace"))
                fm_game = fm_game.get("game")
            except OSError:
                pass
            if fm_game and fm_game.strip().lower() != "gta5":
                stats["decls_excluded_game"] += 1
            else:
                stats["decls_unparsed"] += 1
            continue
        stats["decls_kept"] += 1
        rows.append(row_from_decl(parsed))
        seen_names.add(parsed["name"])

    for ns, natives in (cfx_json or {}).items():
        for h, entry in natives.items():
            name = entry.get("name")
            if not name or name in seen_names:
                continue
            row = row_from_cfx_json(h, entry)
            if row is None:
                continue
            rows.append(row)
            seen_names.add(name)
            stats["fallback_used"] += 1

    return rows, stats
