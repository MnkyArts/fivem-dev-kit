"""argparse wiring for the `fxref` CLI. See DESIGN.md section 3."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from fxkit import config, db, docs_build, names, natives_build, render, search, util

NATIVES_COLUMNS = [
    "hash", "jhash", "name", "lua_name", "ns", "ns_alt", "apiset", "unofficial",
    "aliases", "params", "return_type", "results_description", "description",
    "comment_alloc8or", "examples", "build", "build_gen9", "in_legacy", "in_gen9",
    "unused", "url", "source", "c_signature", "lua_signature", "js_signature",
    "cs_signature", "name_tokens", "alias_tokens", "param_text",
]
DOCS_COLUMNS = ["path", "url", "title", "section", "nav_group", "headings", "body"]
CFX_SOURCES = ("native-decls", "natives_cfx.json")


# ---------------------------------------------------------------------------
# small shared helpers
# ---------------------------------------------------------------------------
def _require_db() -> None:
    if not db.db_exists(config.db_path()):
        print("fxref: database not built — run: fxref build", file=sys.stderr)
        sys.exit(2)


def _git_sha(path: str) -> str | None:
    try:
        out = subprocess.run(
            ["git", "-C", path, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# build
# ---------------------------------------------------------------------------
def _insert_natives(conn, rows: list[dict]) -> None:
    if rows:
        placeholders = ",".join("?" * len(NATIVES_COLUMNS))
        conn.executemany(
            f"INSERT INTO natives ({','.join(NATIVES_COLUMNS)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in NATIVES_COLUMNS) for r in rows],
        )
    id_rows = conn.execute("SELECT id, name, lua_name, hash, jhash, aliases FROM natives").fetchall()
    name_forms: list[tuple[str, int]] = []
    for r in id_rows:
        aliases_raw = r["aliases"]
        aliases = json.loads(aliases_raw) if isinstance(aliases_raw, str) and aliases_raw else (aliases_raw or [])
        for f in natives_build.name_forms_for_row(r["name"], r["lua_name"], r["hash"], r["jhash"], aliases):
            name_forms.append((f, r["id"]))
    if name_forms:
        conn.executemany("INSERT INTO native_names (name_form, native_id) VALUES (?, ?)", name_forms)


def _insert_docs(conn, rows: list[dict]) -> None:
    if not rows:
        return
    placeholders = ",".join("?" * len(DOCS_COLUMNS))
    conn.executemany(
        f"INSERT INTO docs ({','.join(DOCS_COLUMNS)}) VALUES ({placeholders})",
        [tuple(r.get(c) for c in DOCS_COLUMNS) for r in rows],
    )


def cmd_build(args: argparse.Namespace) -> int:
    db_path = config.db_path()
    do_natives = not getattr(args, "docs_only", False)
    do_docs = not getattr(args, "natives_only", False)
    cache_dir = config.data_dir() / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []

    # Snapshot whichever table this run will *not* rebuild, so `--natives-only`
    # / `--docs-only` don't wipe out the other half of an existing DB.
    preserved_natives = None
    preserved_docs = None
    if db.db_exists(db_path):
        try:
            old = db.connect_ro(db_path)
            if not do_natives:
                preserved_natives = [dict(r) for r in old.execute("SELECT * FROM natives").fetchall()]
            if not do_docs:
                preserved_docs = [dict(r) for r in old.execute("SELECT * FROM docs").fetchall()]
            old.close()
        except Exception:
            pass

    with util.Timer() as timer:
        natives_rows: list[dict] = []
        cfx_stats: dict = {}
        if do_natives:
            nativedb_dir = Path(config.get("sources", "nativedb"))
            fivem_dir = Path(config.get("sources", "fivem"))

            legacy = natives_build.load_legacy(nativedb_dir / "natives.json")
            gen9 = natives_build.load_gen9(nativedb_dir / "natives_gen9.json")

            fivem_data, w1 = util.fetch_json(
                config.get("sources", "natives_json_url"), cache_dir / "natives.json",
                force=args.force_download, no_download=args.no_download,
            )
            if w1:
                warnings.append(w1)
            cfx_data, w2 = util.fetch_json(
                config.get("sources", "natives_cfx_json_url"), cache_dir / "natives_cfx.json",
                force=args.force_download, no_download=args.no_download,
            )
            if w2:
                warnings.append(w2)

            fivem = natives_build._flatten(fivem_data) if fivem_data else {}
            gta_rows = natives_build.build_gta_rows(legacy, gen9, fivem)

            decls_dir = fivem_dir / "ext" / "native-decls"
            cfx_rows, cfx_stats = natives_build.build_cfx_rows(decls_dir, cfx_data or {})

            combined = gta_rows + cfx_rows
            seen_keys = set()
            natives_rows = []
            dup_count = 0
            for r in combined:
                key = (r["hash"], r["apiset"])
                if key in seen_keys:
                    dup_count += 1
                    continue
                seen_keys.add(key)
                natives_rows.append(r)
            if dup_count:
                warnings.append(f"{dup_count} duplicate (hash, apiset) rows were dropped")

        doc_rows: list[dict] = []
        if do_docs:
            doc_rows = docs_build.build_doc_rows(Path(config.get("sources", "fivem_docs")))

        if db_path.exists():
            db_path.unlink()
        for suffix in ("-wal", "-shm"):
            p = Path(str(db_path) + suffix)
            if p.exists():
                p.unlink()

        conn = db.connect_rw(db_path)
        db.create_schema(conn)

        final_natives = natives_rows if do_natives else (preserved_natives or [])
        final_docs = doc_rows if do_docs else (preserved_docs or [])

        _insert_natives(conn, final_natives)
        _insert_docs(conn, final_docs)
        db.rebuild_fts(conn)

        counts = {
            "natives_total": conn.execute("SELECT COUNT(*) FROM natives").fetchone()[0],
            "client": conn.execute("SELECT COUNT(*) FROM natives WHERE apiset='client'").fetchone()[0],
            "server": conn.execute("SELECT COUNT(*) FROM natives WHERE apiset='server'").fetchone()[0],
            "shared": conn.execute("SELECT COUNT(*) FROM natives WHERE apiset='shared'").fetchone()[0],
            "unnamed": conn.execute("SELECT COUNT(*) FROM natives WHERE name LIKE '\\_0x%' ESCAPE '\\'").fetchone()[0],
            "unofficial": conn.execute("SELECT COUNT(*) FROM natives WHERE unofficial=1").fetchone()[0],
            "docs_total": conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0],
        }
        src_ph = ",".join("?" * len(CFX_SOURCES))
        counts["cfx_client"] = conn.execute(
            f"SELECT COUNT(*) FROM natives WHERE source IN ({src_ph}) AND apiset='client'", CFX_SOURCES
        ).fetchone()[0]
        counts["cfx_server"] = conn.execute(
            f"SELECT COUNT(*) FROM natives WHERE source IN ({src_ph}) AND apiset='server'", CFX_SOURCES
        ).fetchone()[0]
        counts["cfx_shared"] = conn.execute(
            f"SELECT COUNT(*) FROM natives WHERE source IN ({src_ph}) AND apiset='shared'", CFX_SOURCES
        ).fetchone()[0]
        counts["cfx_total"] = counts["cfx_client"] + counts["cfx_server"] + counts["cfx_shared"]
        counts["gta_total"] = counts["natives_total"] - counts["cfx_total"]

        build_time = datetime.now(timezone.utc).isoformat()
        meta = {
            "build_time": build_time,
            "elapsed_seconds": None,  # filled after the `with` block
            "nativedb_git_sha": _git_sha(config.get("sources", "nativedb")) or "",
            "fivem_git_sha": _git_sha(config.get("sources", "fivem")) or "",
            "fivem_docs_git_sha": _git_sha(config.get("sources", "fivem_docs")) or "",
            "decls_total": cfx_stats.get("decls_total", 0),
            "decls_kept": cfx_stats.get("decls_kept", 0),
            "decls_excluded_game": cfx_stats.get("decls_excluded_game", 0),
            "decls_unparsed": cfx_stats.get("decls_unparsed", 0),
            "cfx_fallback_used": cfx_stats.get("fallback_used", 0),
            **counts,
        }
        for k, v in meta.items():
            db.set_meta(conn, k, json.dumps(v) if not isinstance(v, str) else v)
        conn.commit()
        conn.close()

    meta["elapsed_seconds"] = round(timer.seconds, 2)
    # persist the real elapsed time too (best-effort, separate tiny connection)
    try:
        conn2 = db.connect_rw(db_path)
        db.set_meta(conn2, "elapsed_seconds", json.dumps(meta["elapsed_seconds"]))
        conn2.commit()
        conn2.close()
    except Exception:
        pass

    if args.json:
        _print_json(meta)
    else:
        print(f"fxref build complete in {meta['elapsed_seconds']:.1f}s")
        print(
            f"  natives: {counts['natives_total']} rows "
            f"(client {counts['client']}, server {counts['server']}, shared {counts['shared']})"
        )
        print(f"    GTA (alloc8or legacy+gen9 + FiveM json): {counts['gta_total']}")
        print(
            f"    CFX (native-decls + natives_cfx.json fallback): {counts['cfx_total']} "
            f"(client {counts['cfx_client']}, server {counts['cfx_server']}, shared {counts['cfx_shared']})"
        )
        print(f"    unnamed: {counts['unnamed']}   unofficial-named: {counts['unofficial']}")
        if cfx_stats:
            print(
                f"    decls files: {cfx_stats.get('decls_total', 0)} "
                f"(kept {cfx_stats.get('decls_kept', 0)}, excluded-by-game {cfx_stats.get('decls_excluded_game', 0)}, "
                f"unparsed {cfx_stats.get('decls_unparsed', 0)}); json-fallback used {cfx_stats.get('fallback_used', 0)}"
            )
        print(f"  docs: {counts['docs_total']} pages")
        for w in warnings:
            print(f"  warning: {w}", file=sys.stderr)
    return 0


# ---------------------------------------------------------------------------
# search / show / resolve / ns
# ---------------------------------------------------------------------------
def cmd_search(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    results = search.search_natives(
        conn, args.query, ns=args.ns, side=args.side, game=args.game,
        limit=args.limit, show_all=args.all,
    )
    if args.json:
        _print_json([render.search_result_to_json(e) for e in results])
    else:
        if not results:
            print("(no matches)")
        for e in results:
            print(render.render_search_line(e["row"], e["exact"]))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    rows = search.resolve_one(conn, args.identifier)
    if not rows:
        print(f"fxref: no native found for '{args.identifier}'", file=sys.stderr)
        return 1
    rows = render.sort_matches(rows)
    if args.json:
        _print_json([render.row_to_dict(r) for r in rows])
    else:
        print(("\n\n").join(render.render_show_card(r) for r in rows))
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    out = []
    for identifier in args.names:
        rows = search.resolve_one(conn, identifier)
        out.append((identifier, rows))
    if args.json:
        _print_json([render.resolve_to_json(i, r) for i, r in out])
    else:
        for identifier, rows in out:
            print(render.render_resolve_line(identifier, rows))
    return 0


def cmd_ns(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    rows = conn.execute(
        "SELECT ns, COUNT(*) AS c FROM natives WHERE ns IS NOT NULL AND ns != '' GROUP BY ns ORDER BY ns"
    ).fetchall()
    if args.json:
        _print_json([{"ns": r["ns"], "count": r["c"]} for r in rows])
    else:
        for r in rows:
            print(f"{r['ns']}\t{r['c']}")
    return 0


# ---------------------------------------------------------------------------
# docs
# ---------------------------------------------------------------------------
def cmd_docs_search(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    results = search.search_docs(conn, args.query, limit=args.limit, show_all=args.all)
    if args.json:
        _print_json([render.docs_search_to_json(e) for e in results])
    else:
        if not results:
            print("(no matches)")
        for e in results:
            print(render.render_docs_search_line(e))
    return 0


def cmd_docs_show(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    ident = args.identifier
    row = conn.execute("SELECT * FROM docs WHERE path = ?", (ident,)).fetchone()
    if row is None:
        norm = ident.strip("/")
        row = conn.execute("SELECT * FROM docs WHERE path = ?", (norm,)).fetchone()
    if row is None:
        print(f"fxref: no doc page found for '{ident}'", file=sys.stderr)
        return 1
    if args.json:
        d = dict(row)
        if args.section:
            d["section_body"] = render.extract_section(d["body"] or "", args.section)
        _print_json(d)
    else:
        print(render.render_docs_show(row, section=args.section, raw=args.raw))
    return 0


def cmd_docs_ls(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    prefix = args.prefix or ""
    if prefix:
        rows = conn.execute(
            "SELECT * FROM docs WHERE path LIKE ? ORDER BY path", (prefix.rstrip("/") + "%",)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM docs ORDER BY path").fetchall()
    if args.json:
        _print_json([{"id": r["path"], "title": r["title"], "section": r["section"]} for r in rows])
    else:
        for r in rows:
            print(render.render_docs_ls_line(r))
    return 0


# ---------------------------------------------------------------------------
# stats / update-sources
# ---------------------------------------------------------------------------
def cmd_stats(args: argparse.Namespace) -> int:
    _require_db()
    conn = db.connect_ro(config.db_path())
    meta_rows = conn.execute("SELECT key, value FROM meta").fetchall()
    meta = {}
    for r in meta_rows:
        try:
            meta[r["key"]] = json.loads(r["value"])
        except (TypeError, ValueError):
            meta[r["key"]] = r["value"]
    if args.json:
        _print_json(meta)
        return 0
    print(f"build time: {meta.get('build_time', '?')}   elapsed: {meta.get('elapsed_seconds', '?')}s")
    print(
        f"natives: {meta.get('natives_total', '?')} "
        f"(client {meta.get('client', '?')}, server {meta.get('server', '?')}, shared {meta.get('shared', '?')})"
    )
    print(f"  GTA: {meta.get('gta_total', '?')}   CFX: {meta.get('cfx_total', '?')}")
    print(f"  unnamed: {meta.get('unnamed', '?')}   unofficial-named: {meta.get('unofficial', '?')}")
    print(f"docs: {meta.get('docs_total', '?')} pages")
    print(
        f"sources: nativedb@{meta.get('nativedb_git_sha', '?')}  "
        f"fivem@{meta.get('fivem_git_sha', '?')}  fivem-docs@{meta.get('fivem_docs_git_sha', '?')}"
    )
    return 0


def cmd_update_sources(args: argparse.Namespace) -> int:
    before = None
    if db.db_exists(config.db_path()):
        conn = db.connect_ro(config.db_path())
        before = {
            "natives": conn.execute("SELECT COUNT(*) FROM natives").fetchone()[0],
            "docs": conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0],
        }
        conn.close()

    for key in ("nativedb", "fivem_docs"):
        path = config.get("sources", key)
        print(f"$ git -C {path} pull --ff-only")
        try:
            out = subprocess.run(
                ["git", "-C", path, "pull", "--ff-only"],
                capture_output=True, text=True, timeout=120, check=False,
            )
            if out.stdout.strip():
                print(out.stdout.strip())
            if out.returncode != 0:
                print(out.stderr.strip(), file=sys.stderr)
        except (OSError, subprocess.SubprocessError) as e:
            print(f"  warning: git pull failed for {key}: {e}", file=sys.stderr)

    build_ns = argparse.Namespace(no_download=False, force_download=True, natives_only=False, docs_only=False, json=False)
    cmd_build(build_ns)

    if before:
        conn = db.connect_ro(config.db_path())
        after_natives = conn.execute("SELECT COUNT(*) FROM natives").fetchone()[0]
        after_docs = conn.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        conn.close()
        print(f"natives: {before['natives']} -> {after_natives} ({after_natives - before['natives']:+d})")
        print(f"docs: {before['docs']} -> {after_docs} ({after_docs - before['docs']:+d})")
    return 0


# ---------------------------------------------------------------------------
# argparse
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="fxref", description="FiveM native + docs reference CLI")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="(re)build data/fxref.sqlite")
    b.add_argument("--no-download", action="store_true", help="use cached JSON only, never hit the network")
    b.add_argument("--force-download", action="store_true", help="re-download even if cache is fresh")
    grp = b.add_mutually_exclusive_group()
    grp.add_argument("--natives-only", action="store_true")
    grp.add_argument("--docs-only", action="store_true")
    b.add_argument("--json", action="store_true")
    b.set_defaults(func=cmd_build)

    s = sub.add_parser("search", help="search natives")
    s.add_argument("query", nargs="+")
    s.add_argument("--ns")
    s.add_argument("--side", choices=["client", "server", "shared", "any"], default="any")
    s.add_argument("--game", choices=["legacy", "gen9", "any"], default="any")
    s.add_argument("--limit", type=int, default=15)
    s.add_argument("--all", action="store_true", help="no limit")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_search)

    sh = sub.add_parser("show", help="full card for one native")
    sh.add_argument("identifier", help="name, hash, or Lua name")
    sh.add_argument("--json", action="store_true")
    sh.set_defaults(func=cmd_show)

    r = sub.add_parser("resolve", help="batch existence/identity check")
    r.add_argument("names", nargs="+")
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=cmd_resolve)

    n = sub.add_parser("ns", help="namespaces with counts")
    n.add_argument("--json", action="store_true")
    n.set_defaults(func=cmd_ns)

    d = sub.add_parser("docs", help="docs.fivem.net search/read")
    dsub = d.add_subparsers(dest="docs_command", required=True)

    dsearch = dsub.add_parser("search")
    dsearch.add_argument("query", nargs="+")
    dsearch.add_argument("--limit", type=int, default=10)
    dsearch.add_argument("--all", action="store_true")
    dsearch.add_argument("--json", action="store_true")
    dsearch.set_defaults(func=cmd_docs_search)

    dshow = dsub.add_parser("show")
    dshow.add_argument("identifier", help="doc id/path")
    dshow.add_argument("--section")
    dshow.add_argument("--raw", action="store_true")
    dshow.add_argument("--json", action="store_true")
    dshow.set_defaults(func=cmd_docs_show)

    dls = dsub.add_parser("ls")
    dls.add_argument("prefix", nargs="?", default="")
    dls.add_argument("--json", action="store_true")
    dls.set_defaults(func=cmd_docs_ls)

    st = sub.add_parser("stats", help="show build stats")
    st.add_argument("--json", action="store_true")
    st.set_defaults(func=cmd_stats)

    up = sub.add_parser("update-sources", help="git pull nativedb + fivem-docs, re-download JSONs, rebuild")
    up.set_defaults(func=cmd_update_sources)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
    except Exception as e:  # noqa: BLE001 - CLI top-level guard
        print(f"fxref: error: {e}", file=sys.stderr)
        return 1
