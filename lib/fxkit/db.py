"""SQLite schema + connection helpers for fxref's data/fxref.sqlite.

Design note (deliberate deviation from a literal reading of DESIGN.md's
`natives_fts (FTS5, content=natives): name_tokens, alias_tokens, ns,
param_text, description`):

SQLite's "external content" FTS5 tables require every FTS column name to be a
*real* column on the content table. `ns` and `description` already are real
columns on `natives`, but `name_tokens` / `alias_tokens` / `param_text` are
derived at build time -- so we add them to `natives` as plain stored columns
(populated once per row, never queried directly by CLI code) purely so the
FTS5 `content='natives', content_rowid='id'` linkage is literal and the
"insert with executemany, rebuild FTS once at the end" build shape
(`INSERT INTO natives_fts(natives_fts) VALUES ('rebuild')`) works exactly as
DESIGN.md's performance section describes. `docs_fts` uses the same pattern
against `docs` (title/headings/body are already real columns there, no extra
columns needed).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_SQL = """
CREATE TABLE natives (
    id                  INTEGER PRIMARY KEY,
    hash                TEXT NOT NULL,
    jhash               TEXT,
    name                TEXT NOT NULL,
    lua_name            TEXT NOT NULL,
    ns                  TEXT,
    ns_alt              TEXT,
    apiset              TEXT NOT NULL,
    unofficial          INTEGER NOT NULL DEFAULT 0,
    aliases             TEXT,
    params              TEXT,
    return_type         TEXT,
    results_description TEXT,
    description         TEXT,
    comment_alloc8or    TEXT,
    examples            TEXT,
    build               TEXT,
    build_gen9          TEXT,
    in_legacy           INTEGER NOT NULL DEFAULT 0,
    in_gen9             INTEGER NOT NULL DEFAULT 0,
    unused              INTEGER NOT NULL DEFAULT 0,
    url                 TEXT,
    source              TEXT,
    c_signature         TEXT,
    lua_signature        TEXT,
    js_signature        TEXT,
    cs_signature        TEXT,
    -- derived, FTS-only columns (see module docstring)
    name_tokens         TEXT,
    alias_tokens        TEXT,
    param_text          TEXT
);

CREATE UNIQUE INDEX idx_natives_hash_apiset ON natives(hash, apiset);
CREATE INDEX idx_natives_name ON natives(name);
CREATE INDEX idx_natives_lua_name ON natives(lua_name);
CREATE INDEX idx_natives_ns ON natives(ns);
CREATE INDEX idx_natives_apiset ON natives(apiset);

-- Every name form (C name, Lua name, lowerCamel, hash, aliases in all three
-- forms) resolves to zero or more native rows. Not unique: the same Lua name
-- can point at both a client and a server row (e.g. SetEntityCoords).
CREATE TABLE native_names (
    name_form  TEXT NOT NULL,
    native_id  INTEGER NOT NULL REFERENCES natives(id)
);
CREATE INDEX idx_native_names_form ON native_names(name_form);

CREATE VIRTUAL TABLE natives_fts USING fts5(
    name_tokens, alias_tokens, ns, param_text, description,
    content='natives', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE docs (
    id        INTEGER PRIMARY KEY,
    path      TEXT UNIQUE NOT NULL,
    url       TEXT,
    title     TEXT,
    section   TEXT,
    nav_group TEXT,
    headings  TEXT,
    body      TEXT
);
CREATE INDEX idx_docs_path ON docs(path);

CREATE VIRTUAL TABLE docs_fts USING fts5(
    title, headings, body,
    content='docs', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

-- core framework API index (DESIGN.md section 9.2). Only populated when a
-- `core` block is configured; every core command degrades to "not indexed"
-- when the table is empty. `name_tokens`/`param_text` are stored columns for
-- the same external-content FTS5 reason as `natives` above; `values` is
-- quoted everywhere it appears in SQL (it is an SQLite keyword).
CREATE TABLE core_api (
    id          INTEGER PRIMARY KEY,
    kind        TEXT NOT NULL,          -- function | class | alias | hook
    name        TEXT NOT NULL,
    namespace   TEXT,
    sub         TEXT,
    side        TEXT,                   -- server | client | shared
    access      TEXT,                   -- lib | proxy | ''
    signature   TEXT,
    params      TEXT,                   -- json
    returns     TEXT,                   -- json
    description TEXT,
    fields      TEXT,                   -- json
    "values"    TEXT,                   -- json
    design_ref  TEXT,
    line        INTEGER,
    sha         TEXT,
    -- derived, FTS-only columns
    name_tokens TEXT,
    param_text  TEXT
);
CREATE INDEX idx_core_api_name ON core_api(name);
CREATE INDEX idx_core_api_kind ON core_api(kind);
CREATE INDEX idx_core_api_ns ON core_api(namespace);

CREATE TABLE core_api_names (
    name_form TEXT NOT NULL,
    api_id    INTEGER NOT NULL REFERENCES core_api(id)
);
CREATE INDEX idx_core_api_names_form ON core_api_names(name_form);

CREATE VIRTUAL TABLE core_api_fts USING fts5(
    name_tokens, namespace, description, param_text,
    content='core_api', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TABLE meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);
"""


def connect_rw(db_path: Path) -> sqlite3.Connection:
    """Read-write connection, used only by `fxref build`."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    return conn


def connect_ro(db_path: Path) -> sqlite3.Connection:
    """Read-only connection for every other command (fast, no lock contention)."""
    uri = f"file:{db_path.as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def db_exists(db_path: Path) -> bool:
    return db_path.exists() and db_path.stat().st_size > 0


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA_SQL)


CORE_SCHEMA_START = "-- core framework API index"
CORE_SCHEMA_END = "CREATE TABLE meta ("


def core_schema_sql() -> str:
    """Just the core_api/core_api_names/core_api_fts part of SCHEMA_SQL, so a
    database built before the core index existed can be upgraded in place."""
    start = SCHEMA_SQL.index(CORE_SCHEMA_START)
    end = SCHEMA_SQL.index(CORE_SCHEMA_END, start)
    return SCHEMA_SQL[start:end]


def ensure_core_schema(conn: sqlite3.Connection) -> bool:
    """Create the core tables when this database predates them. Returns True
    when something was created."""
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='core_api'"
    ).fetchone()
    if row is not None:
        return False
    conn.executescript(core_schema_sql())
    return True


def rebuild_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO natives_fts(natives_fts) VALUES ('rebuild')")
    conn.execute("INSERT INTO docs_fts(docs_fts) VALUES ('rebuild')")
    rebuild_core_fts(conn)


def rebuild_core_fts(conn: sqlite3.Connection) -> None:
    conn.execute("INSERT INTO core_api_fts(core_api_fts) VALUES ('rebuild')")


CORE_API_COLUMNS = [
    "kind", "name", "namespace", "sub", "side", "access", "signature", "params",
    "returns", "description", "fields", "values", "design_ref", "line", "sha",
    "name_tokens", "param_text",
]


def has_core_index(conn: sqlite3.Connection) -> bool:
    """True when this database carries a populated `core_api` table."""
    try:
        return conn.execute("SELECT COUNT(*) FROM core_api").fetchone()[0] > 0
    except sqlite3.Error:
        return False


def insert_core_rows(conn: sqlite3.Connection, rows: list) -> None:
    """Replace the whole core index with `rows` (+ their lookup name forms)."""
    from fxkit import core_build

    conn.execute("DELETE FROM core_api_names")
    conn.execute("DELETE FROM core_api")
    if not rows:
        rebuild_core_fts(conn)
        return
    cols = ",".join(f'"{c}"' for c in CORE_API_COLUMNS)
    placeholders = ",".join("?" * len(CORE_API_COLUMNS))
    conn.executemany(
        f"INSERT INTO core_api ({cols}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in CORE_API_COLUMNS) for r in rows],
    )
    forms = []
    for r in conn.execute("SELECT id, kind, name FROM core_api").fetchall():
        for form in core_build.name_forms(r["kind"], r["name"]):
            forms.append((form, r["id"]))
    if forms:
        conn.executemany("INSERT INTO core_api_names (name_form, api_id) VALUES (?, ?)", forms)
    rebuild_core_fts(conn)


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )


def get_meta(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    if row is None:
        return default
    return row[0] if not isinstance(row, sqlite3.Row) else row["value"]
