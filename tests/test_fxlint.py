#!/usr/bin/env python3
"""Plain-python3 tests for fxlint. No pytest.

Run: python3 tests/test_fxlint.py
Prints PASS/FAIL per check and exits 1 if anything failed.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
FXLINT = KIT / "bin" / "fxlint"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

sys.path.insert(0, str(KIT / "lib"))

_pass = 0
_fail = 0


def check(name: str, cond: bool, detail=None) -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"PASS {name}")
    else:
        _fail += 1
        suffix = f" -- {detail}" if detail else ""
        print(f"FAIL {name}{suffix}")


def run_fxlint(args, cwd=None):
    return subprocess.run([sys.executable, str(FXLINT), *args], capture_output=True, text=True, cwd=cwd)


def collect_expected(root: Path) -> set:
    expected = set()
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in (".lua", ".js"):
            continue
        rel = str(p.relative_to(root)).replace(os.sep, "/")
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            m = re.search(r"expect:\s*([A-Z]\d{3})", line)
            if m:
                expected.add((rel, i, m.group(1)))
    return expected


def actual_set(data: dict) -> set:
    out = set()
    for path, items in data["files"].items():
        for it in items:
            out.add((path, it["line"], it["rule"]))
    return out


# ---------------------------------------------------------------------------

def test_bad_resource_matches():
    bad = FIXTURES / "bad-resource"
    expected = collect_expected(bad)
    proc = run_fxlint([str(bad), "--json"])
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        check("bad-resource: produces valid JSON", False, proc.stdout[:500] + proc.stderr[:500])
        return
    actual = actual_set(data)
    # C007 needs a built native database; verified separately with a stubbed fxref.
    expected_no_c007 = {e for e in expected if e[2] != "C007"}
    missing = expected_no_c007 - actual
    check(
        f"bad-resource: every '-- expect:' marker fires at its exact line ({len(expected_no_c007)} checked)",
        not missing, f"missing={sorted(missing)}",
    )
    check("bad-resource: covers every P/S/C rule at least once (except C007/C008, which need fxref)",
          {r for _, _, r in expected_no_c007} >= {
              *(f"P00{i}" for i in range(1, 8)),
              *(f"S00{i}" for i in range(1, 10)), "S010",
              "C001", "C002", "C003", "C004", "C005", "C006", "C009", "C010", "C011", "C012",
          })
    check("bad-resource: exit code is 1 (errors present)", proc.returncode == 1, f"exit={proc.returncode}")
    check("bad-resource: no crash / traceback on stderr", "Traceback" not in proc.stderr, proc.stderr[:800])


def test_good_resource_clean():
    good = FIXTURES / "good-resource"
    proc = run_fxlint([str(good), "--json"])
    data = json.loads(proc.stdout)
    check("good-resource: zero errors", data["summary"]["errors"] == 0, json.dumps(data["summary"]))
    check("good-resource: zero warnings", data["summary"]["warns"] == 0, json.dumps(data["files"]))
    check("good-resource: exit code 0", proc.returncode == 0, f"exit={proc.returncode}")


def test_s003_validation_levels():
    """S003 has three outcomes depending on how much of {type-check,
    permission/distance-or-existence guard} is present for the payload
    player id: both -> silent, one -> info, neither -> warn."""
    bad = run_fxlint([str(FIXTURES / "bad-resource"), "--json"])
    bad_data = json.loads(bad.stdout)
    bad_items = {(p, it["line"]): it for p, items in bad_data["files"].items() for it in items if it["rule"] == "S003"}

    check("S003 no guards at all (GetPlayerPed(targetId)) stays WARN",
          bad_items.get(("server/main.lua", 16), {}).get("level") == "warn", bad_items.get(("server/main.lua", 16)))
    check("S003 no guards at all (DropPlayer(playerId)) stays WARN",
          bad_items.get(("server/main.lua", 22), {}).get("level") == "warn", bad_items.get(("server/main.lua", 22)))
    check("S003 exactly one guard (type-check only) is downgraded to INFO",
          bad_items.get(("server/main.lua", 30), {}).get("level") == "info", bad_items.get(("server/main.lua", 30)))

    good = run_fxlint([str(FIXTURES / "good-resource"), "--json"])
    good_data = json.loads(good.stdout)
    good_s003 = [it for items in good_data["files"].values() for it in items if it["rule"] == "S003"]
    check("S003 type-check AND guard both present ('police:cuff') -> no finding at all, not even info",
          good_s003 == [], good_s003)


def test_native_verification_with_stub_fxref():
    """C007/C008 need a fxref database. We don't own bin/fxref (another engineer
    does), so this stubs it out with a throwaway fake executable in a temp dir
    and monkeypatches fxkit.lint.natives to point at it -- nothing under $KIT
    is touched."""
    from fxkit.lint import engine, natives

    tmp = Path(tempfile.mkdtemp(prefix="fxlint-fxref-stub-"))
    try:
        stub = tmp / "fxref"
        db = tmp / "fxref.sqlite"
        db.write_text("")  # only existence is checked
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import json, sys\n"
            "names = sys.argv[3:]\n"
            "out = []\n"
            "for n in names:\n"
            "    if n == 'SomeClientOnlyNative':\n"
            "        out.append({'input': n, 'found': True, 'matches': ["
            "{'name': 'SOME_CLIENT_ONLY_NATIVE', 'lua_name': n, 'hash': '0x1', 'apiset': 'client', 'ns': 'TEST'}]})\n"
            "    elif n == 'SomeUnknownNative':\n"
            "        out.append({'input': n, 'found': False, 'matches': []})\n"
            "    else:\n"
            "        out.append({'input': n, 'found': True, 'matches': ["
            "{'name': n.upper(), 'lua_name': n, 'hash': '0x0', 'apiset': 'shared', 'ns': 'TEST'}]})\n"
            "print(json.dumps(out))\n"
        )
        stub.chmod(0o755)

        orig_bin, orig_db = natives.fxref_bin_path, natives.fxref_db_path
        natives.fxref_bin_path = lambda: stub
        natives.fxref_db_path = lambda: db
        try:
            findings, notes = engine.lint([str(FIXTURES / "bad-resource")])
        finally:
            natives.fxref_bin_path, natives.fxref_db_path = orig_bin, orig_db

        hits = {(f.path, f.line, f.rule) for f in findings}
        expected = collect_expected(FIXTURES / "bad-resource")
        c007_line = next(ln for (path, ln, rule) in expected if path == "server/main.lua" and rule == "C007")
        c008_line = next(ln for (path, ln, rule) in expected if path == "server/main.lua" and rule == "C008")
        check("C007 fires for a client-only native used server-side (stubbed fxref)",
              ("server/main.lua", c007_line, "C007") in hits, sorted(hits))
        check("C008 fires for an unresolved native-looking call (stubbed fxref)",
              ("server/main.lua", c008_line, "C008") in hits, sorted(hits))
        check("stubbed run produced no 'verification skipped' note", notes == [], notes)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_native_verification_skipped_without_fxref():
    from fxkit.lint import engine, natives

    orig_bin, orig_db = natives.fxref_bin_path, natives.fxref_db_path
    natives.fxref_bin_path = lambda: Path("/nonexistent/fxref")
    natives.fxref_db_path = lambda: Path("/nonexistent/fxref.sqlite")
    try:
        findings, notes = engine.lint([str(FIXTURES / "bad-resource")])
    finally:
        natives.fxref_bin_path, natives.fxref_db_path = orig_bin, orig_db

    check("no fxref -> exactly the documented skip note, no crash",
          notes == ["natives: verification skipped (fxref database not built)"], notes)
    check("no fxref -> no C007/C008 findings at all",
          not any(f.rule in ("C007", "C008") for f in findings),
          [f for f in findings if f.rule in ("C007", "C008")])


def test_suppression_comments():
    tmp = Path(tempfile.mkdtemp(prefix="fxlint-suppress-"))
    try:
        (tmp / "client").mkdir()
        (tmp / "fxmanifest.lua").write_text(
            "fx_version 'cerulean'\ngame 'gta5'\nclient_scripts { 'client/*.lua' }\n"
        )
        (tmp / "client" / "main.lua").write_text(
            "CreateThread(function()\n"
            "    while true do\n"
            "        -- fxlint-disable-next-line P002\n"
            "        Wait(0)\n"
            "    end\n"
            "end)\n"
        )
        proc = run_fxlint([str(tmp), "--json"])
        data = json.loads(proc.stdout)
        found = actual_set(data)
        check("fxlint-disable-next-line suppresses the exact rule on the next line",
              not any(r == "P002" for _, _, r in found), found)

        (tmp / "client" / "main2.lua").write_text(
            "-- fxlint-disable P002\n"
            "CreateThread(function()\n"
            "    while true do\n"
            "        Wait(0)\n"
            "    end\n"
            "end)\n"
        )
        proc2 = run_fxlint([str(tmp), "--json"])
        data2 = json.loads(proc2.stdout)
        found2 = actual_set(data2)
        check("fxlint-disable (file scope) suppresses the rule for the whole file",
              not any(f == "client/main2.lua" and r == "P002" for f, _, r in found2), found2)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_json_shape():
    proc = run_fxlint([str(FIXTURES / "bad-resource"), "--json"])
    data = json.loads(proc.stdout)
    check("--json has 'files' and 'summary' keys", "files" in data and "summary" in data, list(data.keys()))
    check("summary has errors/warns/infos", set(data["summary"].keys()) >= {"errors", "warns", "infos"}, data["summary"])
    any_path = next(iter(data["files"]))
    item = data["files"][any_path][0]
    check("each finding has line/rule/level/msg/hint",
          set(item.keys()) >= {"line", "rule", "level", "msg", "hint"}, item)


def test_strict_mode():
    tmp = Path(tempfile.mkdtemp(prefix="fxlint-strict-"))
    try:
        (tmp / "client").mkdir()
        (tmp / "fxmanifest.lua").write_text("fx_version 'cerulean'\ngame 'gta5'\nclient_scripts { 'client/*.lua' }\n")
        (tmp / "client" / "main.lua").write_text(
            "CreateThread(function()\n    while true do\n        Wait(0)\n    end\nend)\n"
        )
        normal = run_fxlint([str(tmp)])
        strict = run_fxlint([str(tmp), "--strict"])
        check("without --strict, a lone P002 warning exits 0", normal.returncode == 0, normal.stdout)
        check("with --strict, that same warning exits 1", strict.returncode == 1, strict.stdout)
        check("--strict relabels the finding as ERROR in the text report", "ERROR P002" in strict.stdout, strict.stdout)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_rules_and_ignore_filters():
    bad = FIXTURES / "bad-resource"
    only = run_fxlint([str(bad), "--json", "--rules", "P001"])
    data = json.loads(only.stdout)
    rules = {it["rule"] for items in data["files"].values() for it in items}
    check("--rules P001 only reports P001", rules == {"P001"}, rules)

    ignored = run_fxlint([str(bad), "--json", "--ignore", "P001,S001"])
    data2 = json.loads(ignored.stdout)
    rules2 = {it["rule"] for items in data2["files"].values() for it in items}
    check("--ignore P001,S001 excludes both", "P001" not in rules2 and "S001" not in rules2, rules2)


def test_never_crashes_on_garbage():
    tmp = Path(tempfile.mkdtemp(prefix="fxlint-garbage-"))
    try:
        (tmp / "client").mkdir()
        (tmp / "fxmanifest.lua").write_text("fx_version 'cerulean'\ngame 'gta5'\nclient_scripts { 'client/*.lua' }\n")
        with open(tmp / "client" / "garbage.lua", "wb") as fh:
            fh.write(bytes(range(0, 256)) * 4)
            fh.write(b"\nfunction ((( not lua [[[ end end end while(((\n")
        proc = run_fxlint([str(tmp), "--json"])
        check("garbage/binary input doesn't crash fxlint", proc.returncode in (0, 1), f"exit={proc.returncode}")
        check("garbage/binary input produces no traceback", "Traceback" not in proc.stderr, proc.stderr[:800])
        json.loads(proc.stdout)  # must still be valid JSON
        check("garbage/binary input still produces valid JSON output", True)
    except ValueError as exc:
        check("garbage/binary input still produces valid JSON output", False, str(exc))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_manifest_and_path_heuristic_sides():
    from fxkit.lint import engine

    groups = engine.resolve_targets([str(FIXTURES / "bad-resource")])
    check("resolve_targets finds exactly one resource group", len(groups) == 1, len(groups))
    g = groups[0]
    sides = {str(p.relative_to(g.resource_dir)): s for p, s in g.sides.items()}
    check("manifest-listed client/main.lua resolves to side=client", sides.get("client/main.lua") == "client", sides)
    check("manifest-listed server/main.lua resolves to side=server", sides.get("server/main.lua") == "server", sides)
    check("shared/config.lua resolves to side=shared", sides.get("shared/config.lua") == "shared", sides)
    check("client/extra.js (not in any manifest glob) falls back to the client/ path heuristic",
          sides.get("client/extra.js") == "client", sides)
    check("server/extra.js (not in any manifest glob) falls back to the server/ path heuristic",
          sides.get("server/extra.js") == "server", sides)


def test_single_file_invocation():
    """fxlint also accepts loose files, not just a resource directory."""
    f = FIXTURES / "good-resource" / "client" / "main.lua"
    proc = run_fxlint([str(f), "--json"])
    check("linting a single loose file exits cleanly", proc.returncode == 0, proc.stdout + proc.stderr)


# ---------------------------------------------------------------------------
# `core` framework conventions -- group K (DESIGN.md section 9.3)
# ---------------------------------------------------------------------------
# The level(s) a rule must be reported at in core-plugin-bad. K014/K015/K017 are
# multi-part rules: each part has the severity its own failure deserves.
K_LEVELS = {
    "K001": {"warn"}, "K002": {"warn"}, "K003": {"info"}, "K004": {"warn"}, "K005": {"info"},
    "K006": {"error"}, "K007": {"warn"}, "K008": {"warn"}, "K009": {"warn"}, "K010": {"info"},
    "K011": {"warn"}, "K012": {"warn"}, "K013": {"warn"}, "K014": {"warn"},
    "K015": {"error", "warn"}, "K016": {"error"}, "K017": {"info", "warn"},
}
K_COUNT = 17


def collect_expected_core(root: Path) -> set:
    """`-- expect: Kxxx` annotations in the plugin's scripts. The manifest,
    package.json and ui/ carry their annotations as prose (fxlint reports those
    at line 1 / in another file), so only client/ and server/ are matched."""
    expected = set()
    for sub in ("client", "server"):
        for p in sorted((root / sub).rglob("*.lua")):
            rel = str(p.relative_to(root)).replace(os.sep, "/")
            for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                m = re.search(r"expect:\s*(K\d{3})", line)
                if m:
                    expected.add((rel, i, m.group(1)))
    return expected


def _config_without_core(tmp: Path) -> dict:
    """A throwaway FXKIT_CONFIG with the `core` block removed."""
    sys.path.insert(0, str(KIT / "lib"))
    from fxkit import config as fxconfig
    cfg = json.loads(fxconfig.config_path().read_text(encoding="utf-8"))
    cfg.pop("core", None)
    cfg.setdefault("project", {})["framework"] = "standalone"
    path = tmp / "fxkit-config-no-core.json"
    path.write_text(json.dumps(cfg), encoding="utf-8")
    return dict(os.environ, FXKIT_CONFIG=str(path))


def test_core_plugin_bad():
    bad = FIXTURES / "core-plugin-bad"
    proc = run_fxlint([str(bad), "--json"])
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        check("core-plugin-bad: fxlint produced JSON", False, proc.stdout[:400] + proc.stderr[:400])
        return
    actual = actual_set(data)

    for rel, line, rule in sorted(collect_expected_core(bad)):
        check(f"core-plugin-bad {rel}:{line} reports {rule}", (rel, line, rule) in actual,
              sorted(r for p, l, r in actual if (p, l) == (rel, line)))

    fired = {rule for _p, _l, rule in actual if rule.startswith("K")}
    for n in range(1, K_COUNT + 1):
        rid = f"K{n:03d}"
        check(f"core-plugin-bad: {rid} fires", rid in fired, sorted(fired))

    levels = {(it["rule"], it["level"]) for items in data["files"].values() for it in items}
    for rid, wanted in sorted(K_LEVELS.items()):
        have = {l for r, l in levels if r == rid}
        check(f"{rid} has level {'/'.join(sorted(wanted))}", wanted <= have, sorted(have))

    check("core-plugin-bad: K006 is reported in ui/Page.vue",
          any(p.endswith("ui/Page.vue") and r == "K006" for p, _l, r in actual), sorted(actual))
    check("core-plugin-bad: K007 is reported on package.json",
          any(p == "package.json" and r == "K007" for p, _l, r in actual), sorted(actual))
    check("core-plugin-bad: K008/K009/K014 are reported on the manifest",
          {"K008", "K009", "K014"} <= {r for p, _l, r in actual if p == "fxmanifest.lua"}, sorted(actual))
    check("core-plugin-bad: K015 is reported on the built ui/dist/manifest.json",
          any(p == "ui/dist/manifest.json" and r == "K015" for p, _l, r in actual), sorted(actual))
    check("core-plugin-bad: K017 is reported in ui/src, not ui/dist",
          {p for p, _l, r in actual if r == "K017"} == {"ui/src/index.ts"},
          sorted(p for p, _l, r in actual if r == "K017"))
    check("core-plugin-bad: exit code 1 (K006/K015/K016 are errors)", proc.returncode == 1, proc.returncode)


def test_core_plugin_bad_ui():
    """The UI wiring errors the first bad fixture cannot also hold: `core_ui` that
    no `files {}` entry packs, with nothing built behind it (core DESIGN section 38.4)."""
    bad = FIXTURES / "core-plugin-bad-ui"
    proc = run_fxlint([str(bad), "--json"])
    data = json.loads(proc.stdout)
    items = [(p, it) for p, its in data["files"].items() for it in its]
    check("core-plugin-bad-ui: K014 errors -- no files {} entry covers core_ui",
          any(it["rule"] == "K014" and it["level"] == "error" for _p, it in items), items)
    check("core-plugin-bad-ui: K015 warns -- core_ui with nothing to load",
          any(it["rule"] == "K015" and it["level"] == "warn" for _p, it in items), items)
    check("core-plugin-bad-ui: nothing else fires (the Lua is correct)",
          {it["rule"] for _p, it in items} == {"K014", "K015"}, sorted(it["rule"] for _p, it in items))
    check("core-plugin-bad-ui: exit code 1 (K014 is an error)", proc.returncode == 1, proc.returncode)


def _core_plugin_tmp(tmp: Path, name: str, manifest_tail: str) -> Path:
    """A minimal, otherwise-correct core plugin to point one K014/K015 case at."""
    res = tmp / name
    (res / "client").mkdir(parents=True)
    (res / "fxmanifest.lua").write_text(
        "fx_version 'cerulean'\ngame 'gta5'\ndependency 'core'\n"
        "shared_scripts { '@core/import.lua' }\nclient_scripts { 'client/*.lua' }\n"
        + manifest_tail, encoding="utf-8")
    (res / "client" / "main.lua").write_text(
        "Core.onReady(function()\n"
        "    Core.UI.registerPage('probe', { type = 'page' })\n"
        "end)\n", encoding="utf-8")
    return res


def _k_items(res: Path, rule: str) -> list:
    data = json.loads(run_fxlint([str(res), "--json"]).stdout)
    return [it for items in data["files"].values() for it in items if it["rule"] == rule]


def test_k014_k015_wiring_cases():
    """The four cases that cannot share a fixture directory, because each one needs
    a different combination of `core_ui`, a built dist and ui/src."""
    tmp = Path(tempfile.mkdtemp(prefix="fxlint-uiplugin-"))
    try:
        res = _core_plugin_tmp(tmp, "bad_dir", "core_ui 'https://evil.example/x'\nfiles { 'ui/dist/**' }\n")
        hits = _k_items(res, "K014")
        check("K014: an absolute core_ui URL is an error (it would point the CEF elsewhere)",
              len(hits) == 1 and hits[0]["level"] == "error", hits)

        res = _core_plugin_tmp(tmp, "no_optin", "files { 'ui/dist/**' }\n")
        (res / "ui" / "dist").mkdir(parents=True)
        (res / "ui" / "dist" / "manifest.json").write_text('{"id":"no_optin"}', encoding="utf-8")
        hits = _k_items(res, "K014")
        check("K014: a built ui/dist with no core_ui line warns (core never probes it)",
              len(hits) == 1 and hits[0]["level"] == "warn", hits)

        res = _core_plugin_tmp(tmp, "no_build", "files { 'locales/*.json' }\n")
        (res / "ui" / "src").mkdir(parents=True)
        (res / "ui" / "src" / "index.ts").write_text("export default defineUIPlugin({})\n", encoding="utf-8")
        hits = _k_items(res, "K014")
        check("K014: ui/src with neither core_ui nor a dist warns (the page can never load)",
              len(hits) == 1 and hits[0]["level"] == "warn", hits)

        res = _core_plugin_tmp(tmp, "fresh", "core_ui 'ui/dist'\nfiles { 'ui/dist/**' }\n")
        (res / "ui" / "src").mkdir(parents=True)
        (res / "ui" / "src" / "index.ts").write_text("export default defineUIPlugin({})\n", encoding="utf-8")
        hits = _k_items(res, "K015")
        check("K015: a scaffolded plugin that has not been built yet is INFO, not a warning",
              len(hits) == 1 and hits[0]["level"] == "info", hits)
        check("K015: ... so a freshly scaffolded plugin still lints 0 errors / 0 warnings",
              json.loads(run_fxlint([str(res), "--json"]).stdout)["summary"]["errors"] == 0
              and json.loads(run_fxlint([str(res), "--json"]).stdout)["summary"]["warns"] == 0)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_k017_only_flags_real_nui_callbacks():
    """`https://cfx-nui-<res>/...` is the resource's OWN file host (core DESIGN
    section 38.1) -- a page fetching an asset its `files {}` ships, not a NUI
    callback. And a comment that merely mentions an API is not a use of it."""
    tmp = Path(tempfile.mkdtemp(prefix="fxlint-k017-"))
    try:
        res = _core_plugin_tmp(tmp, "pages", "core_ui 'ui/dist'\nfiles { 'ui/dist/**' }\n")
        (res / "ui" / "src").mkdir(parents=True)
        (res / "ui" / "src" / "index.ts").write_text(
            "export default defineUIPlugin({})\n"
            "const items = await fetch('https://cfx-nui-pages/ui/dist/data/x.json')\n"   # 2: fine
            "const page = usePage()   // was window.CoreUI.usePage('pages')\n"           # 3: fine
            "await fetch('https://pages/close', { method: 'POST' })\n"                   # 4: K017
            "await fetch(`https://${GetParentResourceName()}/close`)\n",                 # 5: K017
            encoding="utf-8")
        lines = {it["line"] for it in _k_items(res, "K017")}
        check("K017: a fetch from the resource's own cfx-nui- file host is not a callback",
              2 not in lines, sorted(lines))
        check("K017: a trailing `// ...` mentioning window.CoreUI is not a use of it",
              3 not in lines, sorted(lines))
        check("K017: a dotless-host fetch and the ${...} form are both still reported",
              {4, 5} <= lines, sorted(lines))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_k015_stale_dist():
    """A committed dist older than ui/src is an info: the browser pins a module by
    URL, so only a fresh hash ever runs new code (core DESIGN section 38.1)."""
    tmp = Path(tempfile.mkdtemp(prefix="fxlint-staledist-"))
    try:
        res = _core_plugin_tmp(tmp, "stale", "core_ui 'ui/dist'\nfiles { 'ui/dist/**' }\n")
        (res / "ui" / "src").mkdir(parents=True)
        (res / "ui" / "dist").mkdir(parents=True)
        (res / "ui" / "dist" / "plugin.a1.js").write_text("export default {}\n", encoding="utf-8")
        (res / "ui" / "dist" / "manifest.json").write_text(json.dumps({
            "id": "stale", "apiVersion": 1, "entry": "plugin.a1.js", "css": [],
            "build": "a1", "load": "eager", "pages": ["stale"],
        }), encoding="utf-8")
        entry = res / "ui" / "src" / "index.ts"
        entry.write_text("export default defineUIPlugin({})\n", encoding="utf-8")
        old = (res / "ui" / "dist" / "manifest.json").stat().st_mtime
        os.utime(entry, (old + 600, old + 600))
        hits = _k_items(res, "K015")
        check("K015: a dist older than ui/src is reported as info (rebuild)",
              len(hits) == 1 and hits[0]["level"] == "info" and "older" in hits[0]["msg"], hits)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_core_plugin_good():
    good = FIXTURES / "core-plugin-good"
    proc = run_fxlint([str(good), "--json"])
    data = json.loads(proc.stdout)
    check("core-plugin-good: 0 errors", data["summary"]["errors"] == 0, json.dumps(data["files"]))
    check("core-plugin-good: 0 warnings", data["summary"]["warns"] == 0, json.dumps(data["files"]))
    check("core-plugin-good: no K finding at all",
          not any(it["rule"].startswith("K") for items in data["files"].values() for it in items),
          json.dumps(data["files"]))
    check("core-plugin-good: exit 0", proc.returncode == 0, proc.returncode)


def test_core_rules_need_a_core_resource():
    """The K rules must not fire on a plain FiveM resource."""
    for name in ("good-resource", "bad-resource"):
        proc = run_fxlint([str(FIXTURES / name), "--json"])
        data = json.loads(proc.stdout)
        ks = sorted({it["rule"] for items in data["files"].values() for it in items
                     if it["rule"].startswith("K")})
        check(f"{name}: no K rule fires (not a core resource)", not ks, ks)


def test_k013_skipped_without_core_index():
    tmp = Path(tempfile.mkdtemp(prefix="fxlint-nocore-"))
    try:
        env = _config_without_core(tmp)
        proc = subprocess.run([sys.executable, str(FXLINT), str(FIXTURES / "core-plugin-bad"), "--json"],
                               capture_output=True, text=True, env=env)
        data = json.loads(proc.stdout)
        rules = {it["rule"] for items in data["files"].values() for it in items}
        check("no core index: K013 is skipped, not reported as missing", "K013" not in rules, sorted(rules))
        check("no core index: K010 is skipped too", "K010" not in rules, sorted(rules))
        check("no core index: the other K rules still run", "K004" in rules and "K012" in rules, sorted(rules))
        check("no core index: a note explains the skip",
              any("K013" in n for n in data.get("notes", [])), data.get("notes"))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_real_core_and_core_example_stay_clean():
    """`fxlint <core>` and `fxlint <core_example>` must stay at 0 errors / 0
    warnings with the K rules on -- if a K rule fires there, the rule is wrong."""
    sys.path.insert(0, str(KIT / "lib"))
    from fxkit import config as fxconfig
    paths = fxconfig.core_paths()
    if not paths:
        check("core configured (skipping the real-core lint)", True, "no core block")
        return
    targets = [("core", paths["path"])]
    if paths.get("example"):
        targets.append(("core_example", paths["example"]))
    for label, target in targets:
        proc = run_fxlint([str(target), "--json"])
        data = json.loads(proc.stdout)
        bad = [f"{p}:{it['line']} {it['level']} {it['rule']}"
               for p, items in data["files"].items() for it in items if it["level"] != "info"]
        check(f"{label}: 0 errors", data["summary"]["errors"] == 0, bad[:8])
        check(f"{label}: 0 warnings", data["summary"]["warns"] == 0, bad[:8])
        ks = sorted({it["rule"] for items in data["files"].values() for it in items
                     if it["rule"].startswith("K")})
        check(f"{label}: no K finding", not ks, ks)

    # The post-edit hook lints ONE file at a time: cross-file definitions
    # (core's `Core.DB.markDegraded`, defined in server/db.lua and called in
    # server/db_pg.lua) must still keep K013 quiet.
    for one in sorted((paths["path"] / "server").glob("*.lua"))[:12]:
        proc = run_fxlint([str(one), "--json"])
        data = json.loads(proc.stdout)
        ks = sorted({it["rule"] for items in data["files"].values() for it in items
                     if it["rule"].startswith("K")})
        check(f"core single-file lint ({one.name}): no K finding", not ks, ks)


def main() -> int:
    test_bad_resource_matches()
    test_good_resource_clean()
    test_s003_validation_levels()
    test_native_verification_with_stub_fxref()
    test_native_verification_skipped_without_fxref()
    test_suppression_comments()
    test_json_shape()
    test_strict_mode()
    test_rules_and_ignore_filters()
    test_never_crashes_on_garbage()
    test_manifest_and_path_heuristic_sides()
    test_single_file_invocation()
    test_core_plugin_bad()
    test_core_plugin_bad_ui()
    test_core_plugin_good()
    test_k014_k015_wiring_cases()
    test_k017_only_flags_real_nui_callbacks()
    test_k015_stale_dist()
    test_core_rules_need_a_core_resource()
    test_k013_skipped_without_core_index()
    test_real_core_and_core_example_stay_clean()

    print(f"\n{_pass} passed, {_fail} failed")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
