#!/usr/bin/env python3
"""Plain-python3 tests for fxnew. No pytest.

Run: python3 tests/test_fxnew.py
Prints PASS/FAIL per check and exits 1 if anything failed.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
FXNEW = KIT / "bin" / "fxnew"
FXLINT = KIT / "bin" / "fxlint"

sys.path.insert(0, str(KIT / "lib"))
from fxkit import config as fxconfig  # noqa: E402
from fxkit.scaffold import camel_name, rewrite_text  # noqa: E402

_pass = 0
_fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _pass, _fail
    if cond:
        _pass += 1
        print(f"PASS {name}")
    else:
        _fail += 1
        print(f"FAIL {name} {(' -- ' + detail) if detail else ''}")


def run_fxnew(args, cwd=None, env=None, framework="standalone"):
    """`--framework standalone` is added unless the caller picked one, so these
    checks stay independent of config.json's project.framework (which is `core`
    on this machine -- see the core tests at the bottom)."""
    args = list(args)
    if framework and "--framework" not in args:
        args += ["--framework", framework]
    return subprocess.run([sys.executable, str(FXNEW), *args], capture_output=True, text=True,
                           cwd=cwd, env=env)


def run_fxlint(args, cwd=None, env=None):
    return subprocess.run([sys.executable, str(FXLINT), *args], capture_output=True, text=True,
                           cwd=cwd, env=env)


def lint_clean(resource_dir: Path, label: str, env=None):
    proc = run_fxlint([str(resource_dir), "--json"], env=env)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        check(f"{label}: fxlint produced valid JSON", False, proc.stdout[:500] + proc.stderr[:500])
        return
    check(f"{label}: fxlint reports 0 errors", data["summary"]["errors"] == 0, json.dumps(data["files"]))
    check(f"{label}: fxlint reports 0 warnings", data["summary"]["warns"] == 0, json.dumps(data["files"]))
    check(f"{label}: fxlint exit code 0", proc.returncode == 0, f"exit={proc.returncode}")


def test_scaffold_matrix():
    """The deliverable's required matrix: lua, js, --nui, --ox-lib, --framework qb."""
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-matrix-"))
    try:
        cases = [
            ("plain_lua", []),
            ("plain_js", ["--lang", "js"]),
            ("with_nui", ["--nui"]),
            ("with_nui_js", ["--nui", "--lang", "js"]),
            ("with_ox_lib", ["--ox-lib"]),
            ("qb_framework", ["--framework", "qb"]),
            ("esx_framework", ["--framework", "esx"]),
            ("qbox_framework", ["--framework", "qbox"]),
            ("ox_framework", ["--framework", "ox"]),
            ("no_client", ["--no-client"]),
            ("no_server", ["--no-server"]),
            ("kitchen_sink", ["--nui", "--ox-lib", "--framework", "qb"]),
        ]
        for name, extra in cases:
            proc = run_fxnew([name, "--dir", str(tmp), *extra])
            check(f"fxnew {name}: exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
            check(f"fxnew {name}: 'fxlint self-check passed' in its own output",
                  "fxlint self-check passed" in proc.stdout, proc.stdout)
            resource_dir = tmp / name
            check(f"fxnew {name}: resource directory created", resource_dir.is_dir())
            check(f"fxnew {name}: fxmanifest.lua created", (resource_dir / "fxmanifest.lua").is_file())
            lint_clean(resource_dir, f"fxnew {name}")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_refuses_overwrite_without_force():
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-force-"))
    try:
        first = run_fxnew(["dup", "--dir", str(tmp)])
        check("first fxnew call succeeds", first.returncode == 0, first.stdout + first.stderr)

        second = run_fxnew(["dup", "--dir", str(tmp)])
        check("second fxnew call without --force fails", second.returncode != 0, second.stdout + second.stderr)
        check("second fxnew call without --force explains why", "already exists" in second.stderr, second.stderr)

        third = run_fxnew(["dup", "--dir", str(tmp), "--force"])
        check("fxnew --force overwrites an existing directory", third.returncode == 0, third.stdout + third.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_client_no_server_conflict():
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-conflict-"))
    try:
        proc = run_fxnew(["broken", "--dir", str(tmp), "--no-client", "--no-server"])
        check("--no-client + --no-server together is rejected", proc.returncode != 0, proc.stdout + proc.stderr)
        check("--no-client + --no-server: nothing created", not (tmp / "broken").exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_no_client_and_no_server_individually():
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-single-side-"))
    try:
        run_fxnew(["clientless", "--dir", str(tmp), "--no-client"])
        check("--no-client: no client/ directory", not (tmp / "clientless" / "client").exists())
        check("--no-client: server/ still exists", (tmp / "clientless" / "server").is_dir())
        check("--no-client: fxmanifest.lua has no client_scripts",
              "client_scripts" not in (tmp / "clientless" / "fxmanifest.lua").read_text())

        run_fxnew(["serverless", "--dir", str(tmp), "--no-server"])
        check("--no-server: no server/ directory", not (tmp / "serverless" / "server").exists())
        check("--no-server: client/ still exists", (tmp / "serverless" / "client").is_dir())
        check("--no-server: fxmanifest.lua has no server_scripts",
              "server_scripts" not in (tmp / "serverless" / "fxmanifest.lua").read_text())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_name_sanitization():
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-sanitize-"))
    try:
        proc = run_fxnew(["My Cool Resource!!", "--dir", str(tmp)])
        check("a name with spaces/punctuation is sanitized, not rejected", proc.returncode == 0, proc.stdout + proc.stderr)
        check("sanitized name notice printed on stderr", "sanitized resource name" in proc.stderr, proc.stderr)
        dirs = [p.name for p in tmp.iterdir() if p.is_dir()]
        check("sanitized name is lowercase/hyphenated, and that dir exists",
              any(d.replace("-", "").isalnum() and d.islower() for d in dirs), dirs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_manifest_never_contains_deprecated_keys():
    """DESIGN.md section 8: lua54 is a no-op (never generate it), OAL is off by
    default (never generate it unless the user asks -- fxnew has no flag for it,
    so it should just never appear)."""
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-manifest-keys-"))
    try:
        run_fxnew(["keycheck", "--dir", str(tmp)])
        text = (tmp / "keycheck" / "fxmanifest.lua").read_text()
        check("generated fxmanifest.lua never sets lua54", "lua54" not in text, text)
        check("generated fxmanifest.lua never sets use_experimental_fxv2_oal",
              "use_experimental_fxv2_oal" not in text, text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_readme_and_fxlintrc_present():
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-extras-"))
    try:
        run_fxnew(["extras", "--dir", str(tmp)])
        readme = tmp / "extras" / "README.md"
        rc = tmp / "extras" / ".fxlintrc.json"
        check("README.md is created", readme.is_file())
        check("README.md has an 'In-game test checklist' section", "In-game test checklist" in readme.read_text())
        check(".fxlintrc.json is created and is valid JSON", rc.is_file() and isinstance(json.loads(rc.read_text()), dict))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_author_and_desc_flags():
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-authordesc-"))
    try:
        run_fxnew(["withauthor", "--dir", str(tmp), "--author", "Test Author", "--desc", "a custom description"])
        text = (tmp / "withauthor" / "fxmanifest.lua").read_text()
        check("--author is used in fxmanifest.lua", "Test Author" in text, text)
        check("--desc is used in fxmanifest.lua", "a custom description" in text, text)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# `core` framework mode (DESIGN.md section 9.4)
# ---------------------------------------------------------------------------
def _core_env(workspace: Path, tmp: Path):
    """A throwaway FXKIT_CONFIG whose project.workspace is `workspace` and whose
    core.path is the REAL core checkout (read only -- nothing is written there).
    Returns (env, core_path) or (None, None) when core is not configured here."""
    paths = fxconfig.core_paths()
    if not paths:
        return None, None
    cfg = json.loads(fxconfig.config_path().read_text(encoding="utf-8"))
    cfg.setdefault("project", {})["workspace"] = str(workspace)
    cfg["project"]["framework"] = "core"
    cfg_path = tmp / "fxkit-config.json"
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
    env = dict(os.environ, FXKIT_CONFIG=str(cfg_path))
    return env, paths["path"]


def test_core_placeholder_rewriting():
    """The pure substitution must match core/scripts/new-plugin.sh exactly:
    longest placeholder first, so `my_plugin` cannot eat `MyPlugin`/`MY_PLUGIN`.
    The camel placeholder is `MyPlugin` (the template's TypeScript carries
    `MyPluginProps`, `MyPluginEvents`, `MyPluginRpc`), not `MyPluginPage`."""
    check("camel_name('shop_robbery') == 'ShopRobbery'", camel_name("shop_robbery") == "ShopRobbery",
          camel_name("shop_robbery"))
    check("camel_name('bank') == 'Bank'", camel_name("bank") == "Bank")
    src = ("id = 'my_plugin'\ncomponent = MyPluginPage\nconst MY_PLUGIN = 1\n"
           "interface MyPluginProps {}\ntype MyPluginRpc = {}")
    out = rewrite_text(src, "shop_robbery")
    check("my_plugin -> the resource name", "id = 'shop_robbery'" in out, out)
    check("MyPluginPage -> <Camel>Page (not eaten by my_plugin)", "ShopRobberyPage" in out, out)
    check("MyPluginProps -> <Camel>Props", "interface ShopRobberyProps" in out, out)
    check("MyPluginRpc -> <Camel>Rpc", "type ShopRobberyRpc" in out, out)
    check("MY_PLUGIN -> <UPPER>", "SHOP_ROBBERY = 1" in out, out)
    check("no placeholder survives", "my_plugin" not in out and "MyPlugin" not in out and "MY_PLUGIN" not in out, out)


def test_core_plugin_scaffold():
    tmp = Path(tempfile.mkdtemp(prefix="fxnew-core-"))
    try:
        workspace = tmp / "resources"
        workspace.mkdir()
        env, core_path = _core_env(workspace, tmp)
        if env is None:
            check("core framework configured (skipping core fxnew tests)", True, "no core block")
            return

        proc = run_fxnew(["shop_robbery", "--author", "MnkyArts", "--desc", "Rob the 24/7"],
                          env=env, framework=None)
        check("fxnew (core): exits 0", proc.returncode == 0, proc.stdout + proc.stderr)
        plugin = workspace / "shop_robbery"
        check("fxnew (core): scaffolds into project.workspace", plugin.is_dir(), str(plugin))
        check("fxnew (core): copied core/templates/plugin", (plugin / "fxmanifest.lua").is_file()
              and (plugin / "client" / "main.lua").is_file()
              and (plugin / "server" / "main.lua").is_file()
              and (plugin / "shared" / "config.lua").is_file()
              and (plugin / "locales" / "en.json").is_file())

        blob = "\n".join(p.read_text(encoding="utf-8", errors="replace")
                          for p in plugin.rglob("*") if p.is_file())
        check("fxnew (core): no placeholder survives anywhere",
              "my_plugin" not in blob and "MyPluginPage" not in blob and "MY_PLUGIN" not in blob)
        check("fxnew (core): the new name is used", "shop_robbery" in blob)

        manifest = (plugin / "fxmanifest.lua").read_text(encoding="utf-8")
        check("fxnew (core): --author lands in the manifest", "author 'MnkyArts'" in manifest, manifest)
        check("fxnew (core): --desc lands in the manifest", "description 'Rob the 24/7'" in manifest, manifest)
        check("fxnew (core): version is set", "version '1.0.0'" in manifest, manifest)
        check("fxnew (core): dependency 'core'", "dependency 'core'" in manifest, manifest)
        check("fxnew (core): '@core/import.lua' first in shared_scripts",
              manifest.index("'@core/import.lua'") < manifest.index("'shared/config.lua'"), manifest)

        check("fxnew (core): self-lint passed", "fxlint self-check passed" in proc.stdout, proc.stdout)
        lint_clean(plugin, "fxnew (core) shop_robbery", env=env)

        out = proc.stdout
        check("fxnew (core): next steps give the ensure order",
              "ensure core" in out and "ensure shop_robbery" in out, out)
        check("fxnew (core): next steps build THIS plugin's UI, not core's",
              "npm run build -w shop_robbery-ui" in out, out)
        check("fxnew (core): next steps say core is never rebuilt for a plugin page",
              "No core rebuild" in out and "restart shop_robbery" in out, out)
        check("fxnew (core): next steps mention the one-off workspace npm install",
              "npm install" in out, out)
        check("fxnew (core): next steps mention refresh", "refresh; ensure shop_robbery" in out, out)
        check("fxnew (core): ui/ kept by default", (plugin / "ui" / "src" / "Page.vue").is_file())
        check("fxnew (core): the UI plugin entry is ui/src/index.ts",
              (plugin / "ui" / "src" / "index.ts").is_file())
        check("fxnew (core): the plugin's own build config came along",
              (plugin / "ui" / "vite.config.ts").is_file() and (plugin / "ui" / "package.json").is_file()
              and (plugin / "ui" / "tsconfig.json").is_file() and (plugin / "ui" / ".gitignore").is_file())
        check("fxnew (core): the browser dev host came along",
              (plugin / "ui" / "dev" / "host.ts").is_file() and (plugin / "ui" / "dev" / "mock.ts").is_file())
        pkg = json.loads((plugin / "ui" / "package.json").read_text())
        check("fxnew (core): ui/package.json is renamed to <resource>-ui",
              pkg.get("name") == "shop_robbery-ui", pkg.get("name"))
        check("fxnew (core): vue is never a plugin dependency (the shell hands it over)",
              "vue" not in pkg.get("dependencies", {}), pkg.get("dependencies"))
        ignore = [l.strip() for l in (plugin / "ui" / ".gitignore").read_text().splitlines()
                  if l.strip() and not l.strip().startswith("#")]
        check("fxnew (core): the extension-less ui/.gitignore came along and never ignores dist/ "
              "(the build is committed, like core/html)",
              ".core-ui/" in ignore and "node_modules/" in ignore
              and not any(i.strip("/") == "dist" for i in ignore), ignore)
        manifest_ui = (plugin / "fxmanifest.lua").read_text(encoding="utf-8")
        check("fxnew (core): the manifest opts the resource in with core_ui + a files glob",
              "core_ui 'ui/dist'" in manifest_ui and "'ui/dist/**'" in manifest_ui, manifest_ui)

        again = run_fxnew(["shop_robbery"], env=env, framework=None)
        check("fxnew (core): refuses to overwrite", again.returncode != 0, again.stdout + again.stderr)
        check("fxnew (core): says why", "already exists" in again.stderr, again.stderr)

        no_ui = run_fxnew(["bank_heist", "--no-ui"], env=env, framework=None)
        check("fxnew (core) --no-ui: exits 0", no_ui.returncode == 0, no_ui.stdout + no_ui.stderr)
        check("fxnew (core) --no-ui: ui/ removed", not (workspace / "bank_heist" / "ui").exists())
        no_ui_manifest = (workspace / "bank_heist" / "fxmanifest.lua").read_text(encoding="utf-8")
        check("fxnew (core) --no-ui: the core_ui opt-in is gone from the manifest",
              "core_ui" not in no_ui_manifest, no_ui_manifest)
        check("fxnew (core) --no-ui: so is the ui/dist files entry",
              "ui/dist" not in no_ui_manifest, no_ui_manifest)
        check("fxnew (core) --no-ui: locales stay in files {}",
              "'locales/*.json'" in no_ui_manifest, no_ui_manifest)
        check("fxnew (core) --no-ui: client/main.lua says how to add a page later",
              "--no-ui" in (workspace / "bank_heist" / "client" / "main.lua").read_text(encoding="utf-8"),
              (workspace / "bank_heist" / "client" / "main.lua").read_text(encoding="utf-8"))
        check("fxnew (core) --no-ui: next steps say how to add a UI later",
              "templates/plugin/ui" in no_ui.stdout, no_ui.stdout)
        lint_clean(workspace / "bank_heist", "fxnew (core) bank_heist --no-ui", env=env)

        nui = run_fxnew(["car_wash", "--nui"], env=env, framework=None)
        check("fxnew (core) --nui: keeps ui/", (workspace / "car_wash" / "ui" / "src" / "index.ts").is_file())
        check("fxnew (core) --nui: says the plugin owns and builds its own frontend",
              "npm run build -w car_wash-ui" in nui.stdout and "never rebuilt" in nui.stdout, nui.stdout)

        bad = run_fxnew(["core"], env=env, framework=None)
        check("fxnew (core): refuses the name 'core'", bad.returncode != 0, bad.stdout + bad.stderr)

        standalone = run_fxnew(["plain_one", "--framework", "standalone"], env=env, framework=None)
        check("fxnew --framework standalone still uses the old scaffold",
              standalone.returncode == 0 and (workspace / "plain_one" / ".fxlintrc.json").is_file(),
              standalone.stdout + standalone.stderr)
        check("fxnew --framework standalone: no core dependency",
              "dependency 'core'" not in (workspace / "plain_one" / "fxmanifest.lua").read_text())

        check("fxnew (core): core checkout untouched",
              not (core_path / "shop_robbery").exists() and not (core_path / "templates" / "plugin" / "ui" / "dist").exists())
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    test_scaffold_matrix()
    test_refuses_overwrite_without_force()
    test_no_client_no_server_conflict()
    test_no_client_and_no_server_individually()
    test_name_sanitization()
    test_manifest_never_contains_deprecated_keys()
    test_readme_and_fxlintrc_present()
    test_author_and_desc_flags()
    test_core_placeholder_rewriting()
    test_core_plugin_scaffold()

    print(f"\n{_pass} passed, {_fail} failed")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
