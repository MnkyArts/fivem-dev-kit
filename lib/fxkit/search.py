"""Query-side logic: exact-match resolution + FTS5 search for natives and docs.

See DESIGN.md section 3 ("Search behaviour") for the contract.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from fxkit import names, synonyms

# bm25() column weights, in natives_fts column order
# (name_tokens, alias_tokens, ns, param_text, description).
_NATIVES_BM25_WEIGHTS = (10.0, 6.0, 3.0, 2.0, 1.0)
# docs_fts column order: (title, headings, body).
_DOCS_BM25_WEIGHTS = (8.0, 4.0, 1.0)


# ---------------------------------------------------------------------------
# Native lookups (used by resolve/show/search's exact-match step)
# ---------------------------------------------------------------------------
def lookup_name_form(conn: sqlite3.Connection, form: str) -> list[int]:
    """Exact (case-insensitive) name_form lookup -> list of native ids."""
    f = form.strip().lower()
    if f.startswith("0x"):
        f = f[2:]
    rows = conn.execute(
        "SELECT DISTINCT native_id FROM native_names WHERE name_form = ? OR name_form = ?",
        (f, "0x" + f),
    ).fetchall()
    return [r[0] for r in rows]


def fetch_natives_by_ids(conn: sqlite3.Connection, ids: list[int]) -> list[sqlite3.Row]:
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT * FROM natives WHERE id IN ({placeholders})", ids).fetchall()
    by_id = {r["id"]: r for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def resolve_one(conn: sqlite3.Connection, identifier: str) -> list[sqlite3.Row]:
    """All native rows matching `identifier` exactly (any known name form)."""
    ids = lookup_name_form(conn, identifier)
    return fetch_natives_by_ids(conn, ids)


# ---------------------------------------------------------------------------
# fxref search
# ---------------------------------------------------------------------------
def _exact_candidates(query_args: list[str]) -> set[str]:
    raw = " ".join(query_args).strip()
    variants = {raw, raw.replace("-", "").replace(".", ""), raw.replace(" ", "")}
    variants.add(raw.replace(" ", "").replace("-", "").replace(".", ""))
    return {v.lower() for v in variants if v}


def _tokenize_query(query_args: list[str]) -> list[str]:
    words: list[str] = []
    for arg in query_args:
        words.extend(names.split_camel_or_snake(arg))
    return words


def _fts_match_expr(words: list[str]) -> str:
    groups = []
    for w in words:
        syns = sorted(synonyms.expand(w))
        terms = [f'{s}*' for s in syns if s]
        if not terms:
            continue
        groups.append(terms[0] if len(terms) == 1 else "(" + " OR ".join(terms) + ")")
    return " AND ".join(groups)


def search_natives(
    conn: sqlite3.Connection,
    query_args: list[str],
    *,
    ns: str | None = None,
    side: str = "any",
    game: str = "any",
    limit: int = 15,
    show_all: bool = False,
) -> list[dict[str, Any]]:
    """Returns a list of {'row': sqlite3.Row, 'exact': bool}, deterministically
    ordered (exact matches first, then BM25 rank, tie-broken by name).
    """

    def side_ok(apiset: str) -> bool:
        return side == "any" or apiset == side or apiset == "shared"

    def game_ok(row: sqlite3.Row) -> bool:
        if game == "any":
            return True
        if not row["in_legacy"] and not row["in_gen9"]:
            return True
        return bool(row["in_legacy"]) if game == "legacy" else bool(row["in_gen9"])

    def ns_ok(row: sqlite3.Row) -> bool:
        if not ns:
            return True
        n = ns.lower()
        return (row["ns"] or "").lower() == n or (row["ns_alt"] or "").lower() == n

    results: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    exact_ids: list[int] = []
    for cand in _exact_candidates(query_args):
        exact_ids.extend(lookup_name_form(conn, cand))
    if exact_ids:
        uniq_ids = sorted(set(exact_ids))
        for row in fetch_natives_by_ids(conn, uniq_ids):
            if row["id"] in seen_ids:
                continue
            if not (side_ok(row["apiset"]) and game_ok(row) and ns_ok(row)):
                continue
            seen_ids.add(row["id"])
            results.append({"row": row, "exact": True})

    words = _tokenize_query(query_args)
    match_expr = _fts_match_expr(words)
    if match_expr:
        w = _NATIVES_BM25_WEIGHTS
        sql = (
            f"SELECT rowid AS native_id, bm25(natives_fts, {w[0]}, {w[1]}, {w[2]}, {w[3]}, {w[4]}) AS rank "
            f"FROM natives_fts WHERE natives_fts MATCH ? ORDER BY rank ASC LIMIT ?"
        )
        # Fetch a generous pool since post-filtering (ns/side/game) can drop rows.
        pool = 500 if show_all else max(limit * 20, 200)
        try:
            fts_rows = conn.execute(sql, (match_expr, pool)).fetchall()
        except sqlite3.OperationalError:
            fts_rows = []
        candidate_ids = [r["native_id"] for r in fts_rows]
        by_id = {r["id"]: r for r in fetch_natives_by_ids(conn, candidate_ids)}
        scored = []
        for r in fts_rows:
            row = by_id.get(r["native_id"])
            if row is None or row["id"] in seen_ids:
                continue
            if not (side_ok(row["apiset"]) and game_ok(row) and ns_ok(row)):
                continue
            # BM25 alone treats a prefix match (query "lock*" hitting "LOCKED")
            # the same as any other hit, so a longer, more-specific name (e.g.
            # ..._FOR_ALL_TEAMS) can out-score the plain, canonical native it
            # was derived from purely on document-length arithmetic. Re-rank
            # the BM25-selected candidate pool by how many *whole* query
            # concepts the name actually contains, preferring fewer, more
            # precise extra words -- BM25 rank is still the final tie-break.
            name_words = {w.lower() for w in names.name_words(row["name"])}
            concept_hits = sum(1 for w in words if synonyms.expand(w) & name_words)
            scored.append((-concept_hits, len(name_words), r["rank"], row["name"], row))
        scored.sort(key=lambda t: (t[0], t[1], t[2], t[3]))
        for _hits, _wc, _rank, _name, row in scored:
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            results.append({"row": row, "exact": False})

    if not show_all:
        results = results[:limit]
    return results


# ---------------------------------------------------------------------------
# fxref docs search
# ---------------------------------------------------------------------------
def search_docs(conn: sqlite3.Connection, query_args: list[str], *, limit: int = 10, show_all: bool = False) -> list[dict[str, Any]]:
    words: list[str] = []
    for arg in query_args:
        words.extend(names.split_camel_or_snake(arg))
    terms = [f"{w}*" for w in words if w]
    if not terms:
        return []
    match_expr = " AND ".join(terms)

    w = _DOCS_BM25_WEIGHTS
    sql = (
        f"SELECT rowid AS doc_id, bm25(docs_fts, {w[0]}, {w[1]}, {w[2]}) AS rank, "
        f"snippet(docs_fts, 2, '', '', ' … ', 12) AS snip "
        f"FROM docs_fts WHERE docs_fts MATCH ? ORDER BY rank ASC LIMIT ?"
    )
    pool = 500 if show_all else max(limit * 5, 50)
    try:
        rows = conn.execute(sql, (match_expr, pool)).fetchall()
    except sqlite3.OperationalError:
        return []

    ids = [r["doc_id"] for r in rows]
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    doc_rows = conn.execute(f"SELECT * FROM docs WHERE id IN ({placeholders})", ids).fetchall()
    by_id = {d["id"]: d for d in doc_rows}

    out = []
    for r in rows:
        d = by_id.get(r["doc_id"])
        if d is None:
            continue
        out.append({"doc": d, "snippet": r["snip"], "rank": r["rank"]})
    out.sort(key=lambda e: (e["rank"], e["doc"]["path"]))
    if not show_all:
        out = out[:limit]
    return out
