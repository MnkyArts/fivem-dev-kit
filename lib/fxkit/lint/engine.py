"""fxlint orchestration: figure out what to lint, parse it, run the rules,
verify natives in one batched subprocess call, and return findings+notes.

Kept deliberately defensive: per-file parsing and rule execution are each
wrapped in try/except so one bad file (or one bug in a rule) degrades to a
PARSE info finding instead of crashing the whole run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from . import jsparse, luaparse, manifest as manifest_mod, natives, rules_perf, rules_sec, rules_style, xref
from .model import Finding

SOURCE_EXTS = {".lua", ".js", ".ts"}
EXCLUDE_DIR_NAMES = {".git", "node_modules", "html", "ui", "web", "nui", "dist", "tests", ".vscode", "__pycache__"}


@dataclass
class ResourceGroup:
    resource_dir: Optional[Path]
    manifest: manifest_mod.ManifestInfo
    files: list
    sides: dict
    parsed: list = field(default_factory=list)
    ctx: object = None


def _find_resource_root(file: Path) -> Optional[Path]:
    cur = file.parent
    for _ in range(8):
        if manifest_mod.find_manifest(cur) is not None:
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _walk_source_files(resource_dir: Path) -> list:
    out = []
    for p in resource_dir.rglob("*"):
        if not p.is_file() or p.suffix not in SOURCE_EXTS:
            continue
        if p.name in manifest_mod.MANIFEST_NAMES:
            continue  # fxmanifest.lua/__resource.lua are declarative metadata, not scripts to lint as code
        rel_parts = p.relative_to(resource_dir).parts[:-1]
        if any(part in EXCLUDE_DIR_NAMES for part in rel_parts):
            continue
        out.append(p)
    return sorted(out)


def resolve_targets(paths: list) -> list:
    groups_by_root: dict = {}
    for raw in paths:
        p = Path(raw).resolve()
        if p.is_dir():
            groups_by_root.setdefault(p, set())
            groups_by_root[p].update(_walk_source_files(p))
        elif p.is_file():
            if p.name in manifest_mod.MANIFEST_NAMES:
                # linted via check_c004/check_c005 (resource-level), never as a script --
                # still register the directory so those checks run for a bare `fxlint fxmanifest.lua`.
                groups_by_root.setdefault(p.parent, set())
                continue
            root = _find_resource_root(p)
            key = root if root is not None else p.parent
            groups_by_root.setdefault(key, set()).add(p)

    groups = []
    for root, files in groups_by_root.items():
        mpath = manifest_mod.find_manifest(root)
        m = manifest_mod.parse_manifest(mpath) if mpath else manifest_mod.ManifestInfo(path=None)
        file_list = sorted(files)
        sides = manifest_mod.resolve_sides(root, m, file_list)
        groups.append(ResourceGroup(resource_dir=root, manifest=m, files=file_list, sides=sides))
    return groups


def _lang_for(path: Path) -> str:
    if path.suffix == ".lua":
        return "lua"
    if path.suffix == ".ts":
        return "ts"
    return "js"


def _parse_file(path: Path, resource_dir: Optional[Path], side: Optional[str]):
    text = path.read_text(encoding="utf-8", errors="replace")
    rel = str(path.relative_to(resource_dir)) if resource_dir else str(path)
    rel = rel.replace("\\", "/")
    lang = _lang_for(path)
    if lang == "lua":
        return luaparse.parse_lua(str(path), rel, side, text)
    return jsparse.parse_js(str(path), rel, side, text, lang=lang)


def _defined_names_for(pf) -> set:
    if pf.lang == "lua":
        return luaparse.collect_defined_names(pf.clean_lines)
    return jsparse.collect_defined_names(pf.clean_lines)


def lint(paths: list, no_verify: bool = False):
    """Returns (findings: list[Finding], notes: list[str])."""
    findings: list = []
    notes: list = []
    groups = resolve_targets(paths)
    native_candidates: list = []  # (ParsedFile, line, name)

    for g in groups:
        for f in g.files:
            try:
                pf = _parse_file(f, g.resource_dir, g.sides.get(f))
            except Exception as exc:  # noqa: BLE001 - must never crash the whole run
                rel = str(f.relative_to(g.resource_dir)) if g.resource_dir else str(f)
                findings.append(Finding(rel, 1, "PARSE", "info",
                                         f"could not analyse {rel}: {exc}", "file skipped, rest of the run continues"))
                continue
            g.parsed.append(pf)

        defined = set()
        for pf in g.parsed:
            try:
                defined |= _defined_names_for(pf)
            except Exception:  # noqa: BLE001
                continue

        deps = {d for d in g.manifest.dependencies if not d.startswith("/")}
        ctx = xref.build_context(g.parsed, defined, deps)
        g.ctx = ctx

        for pf in g.parsed:
            try:
                findings += rules_perf.run(pf)
                findings += rules_sec.run(pf, ctx)
                findings += rules_style.run(pf, ctx)
            except Exception as exc:  # noqa: BLE001
                findings.append(Finding(pf.rel_path, 1, "PARSE", "info",
                                         f"could not analyse {pf.rel_path}: {exc}", "file skipped, rest of the run continues"))
                continue
            try:
                for ln, name in natives.find_native_candidates(pf.clean_lines, defined):
                    native_candidates.append((pf, ln, name))
            except Exception:  # noqa: BLE001
                pass

        if g.resource_dir is not None:
            findings += rules_style.check_c004(g.resource_dir)
            findings += rules_style.check_c005(g.resource_dir, g.manifest)

    if native_candidates and not no_verify:
        names = {name for _, _, name in native_candidates}
        resolved = natives.resolve_names(names)
        if resolved is None:
            reason = "fxref database not built" if not natives.is_available() else "fxref resolve failed"
            notes.append(f"natives: verification skipped ({reason})")
        else:
            resolved_map = {e.get("input"): e for e in resolved if isinstance(e, dict)}
            by_pf: dict = {}
            for pf, ln, name in native_candidates:
                by_pf.setdefault(id(pf), (pf, []))[1].append((ln, name))
            for pf, cand in by_pf.values():
                try:
                    findings += rules_style.check_c007_c008(pf, cand, resolved_map)
                except Exception:  # noqa: BLE001
                    pass
    elif native_candidates and no_verify:
        pass  # explicitly opted out, no note needed

    return findings, notes
