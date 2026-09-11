"""Build `docs` rows from the docs.fivem.net Hugo source (fivem-docs/content/docs).

Page id = path relative to `content/`, without `.md` and without a trailing
`_index` component (e.g. `docs/scripting-reference/resource-manifest/resource-manifest`).
url = https://docs.fivem.net/<id>/. section = 2nd path component of the id.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_FRONT_MATTER_RE = re.compile(r"^---\r?\n(.*?)\r?\n---\r?\n?", re.S)
_ANGLE_SHORTCODE_RE = re.compile(r"\{\{<\s*(.*?)\s*>\}\}", re.S)
_PERCENT_SHORTCODE_RE = re.compile(r"\{\{%(.*?)%\}\}", re.S)
_ATTR_RE = re.compile(r'(\w[\w-]*)\s*=\s*"([^"]*)"')
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.M)


def parse_front_matter(text: str) -> tuple[dict[str, str], str]:
    """Lenient YAML-ish front matter parser: only cares about simple
    `key: value` one-liners (title, nav_group, ...); multi-line block
    scalars (`description: >`) and their indented continuation are skipped.
    """
    m = _FRONT_MATTER_RE.match(text)
    if not m:
        return {}, text
    lines = m.group(1).splitlines()
    fm: dict[str, str] = {}
    i = 0
    while i < len(lines):
        line = lines[i].rstrip("\r")
        i += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if line[:1] in (" ", "\t"):
            continue  # continuation of a previous (possibly multi-line) value
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val in ("", ">", "|", ">-", "|-", "|+", ">+"):
            while i < len(lines) and (not lines[i].strip() or lines[i][:1] in (" ", "\t")):
                i += 1
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ("\"", "'"):
            val = val[1:-1]
        fm[key] = val
    return fm, text[m.end() :]


def _youtube_url(inner: str) -> str:
    attrs = dict(_ATTR_RE.findall(inner))
    vid = attrs.get("id")
    if not vid:
        parts = inner.split()
        if len(parts) > 1:
            vid = parts[1].strip("\"'")
    return f"https://www.youtube.com/watch?v={vid}" if vid else ""


def simplify_shortcodes(text: str, docs_root: "Path | None" = None) -> str:
    """Hugo shortcodes -> plain text. `{{< ... >}}` (raw/HTML) tags are
    dropped, except `{{< youtube ... >}}` which becomes its watch URL.
    `{{% ... %}}` (markdown-processed) tags are stripped, keeping whatever
    markdown text sits *between* a paired open/close tag untouched; a bare
    `{{% native_link "X" %}}` becomes just `X`.
    """

    def repl_angle(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        if inner.lower().startswith("youtube"):
            return _youtube_url(inner)
        return ""

    text = _ANGLE_SHORTCODE_RE.sub(repl_angle, text)

    def _static(rel: str) -> str:
        """Read a file referenced by a Hugo shortcode (paths are site-root relative)."""
        if docs_root is None:
            return ""
        try:
            return (docs_root / rel.lstrip("/")).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return ""

    def repl_percent(m: re.Match[str]) -> str:
        inner = m.group(1).strip()
        closing = inner.startswith("/")
        inner = inner.strip("/*").strip()
        low = inner.lower()
        if low.startswith("youtube"):
            return _youtube_url(inner)
        if low.startswith("native_link"):
            mm = re.search(r'"([^"]+)"', inner)
            return mm.group(1) if mm else ""
        if low == "rmv2":  # current fx_version name (e.g. cerulean)
            return _static("static/resource_manifest_version2.txt") or "cerulean"
        if low == "rmv":  # legacy resource_manifest_version GUID
            return _static("static/resource_manifest_version.txt")
        if low.startswith("code"):  # {{% code file="/static/x.lua" language="lua" %}} -> fenced file contents
            mf = re.search(r'file="([^"]+)"', inner)
            ml = re.search(r'language="([^"]+)"', inner)
            body = _static(mf.group(1)) if mf else ""
            if body:
                rmv = _static("static/resource_manifest_version.txt")
                body = body.replace("{{RMV}}", rmv)
                return "\n```" + (ml.group(1) if ml else "") + "\n" + body + "\n```\n"
            return ""
        if low.startswith("alert"):
            if closing:
                return ""
            mt = re.search(r'title="([^"]+)"', inner)
            return "> **" + (mt.group(1) if mt else "Note") + ":** "
        return ""

    text = _PERCENT_SHORTCODE_RE.sub(repl_percent, text)
    return text


def doc_id_for(path: Path, content_root: Path) -> str:
    rel = path.relative_to(content_root).with_suffix("")
    parts = list(rel.parts)
    if parts and parts[-1] == "_index":
        parts = parts[:-1]
    if not parts:
        parts = [content_root.name]
    return "/".join(parts)


def parse_doc_page(path: Path, content_root: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    fm, rest = parse_front_matter(raw)
    body = simplify_shortcodes(rest, docs_root=content_root.parent)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()

    doc_id = doc_id_for(path, content_root)
    parts = doc_id.split("/")
    section = parts[1] if len(parts) > 1 else (parts[0] if parts else None)

    title = fm.get("title")
    if not title:
        hm = re.search(r"^#\s+(.+?)\s*$", body, re.M)
        if hm:
            title = hm.group(1).strip()
    if not title:
        stem = path.stem if path.stem != "_index" else path.parent.name
        title = stem.replace("-", " ").replace("_", " ").strip().title() or doc_id

    heading_texts = [h[1].strip() for h in _HEADING_RE.findall(body)]

    return {
        "path": doc_id,
        "url": f"https://docs.fivem.net/{doc_id}/",
        "title": title,
        "section": section,
        "nav_group": fm.get("nav_group"),
        "headings": "\n".join(heading_texts),
        "body": body,
    }


def build_doc_rows(fivem_docs_root: Path) -> list[dict[str, Any]]:
    content_root = fivem_docs_root / "content"
    docs_dir = content_root / "docs"
    rows = []
    for path in sorted(docs_dir.rglob("*.md")):
        try:
            rows.append(parse_doc_page(path, content_root))
        except Exception:
            continue
    return rows
