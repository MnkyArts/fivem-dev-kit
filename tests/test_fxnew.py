#!/usr/bin/env python3
"""Plain-python3 tests for fxnew. No pytest.

Run: python3 tests/test_fxnew.py
Prints PASS/FAIL per check and exits 1 if anything failed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
FXNEW = KIT / "bin" / "fxnew"
FXLINT = KIT / "bin" / "fxlint"

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


def run_fxnew(args, cwd=None):
    return subprocess.run([sys.executable, str(FXNEW), *args], capture_output=True, text=True, cwd=cwd)


def run_fxlint(args, cwd=None):
    return subprocess.run([sys.executable, str(FXLINT), *args], capture_output=True, text=True, cwd=cwd)


def lint_clean(resource_dir: Path, label: str):
    proc = run_fxlint([str(resource_dir), "--json"])
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


def main() -> int:
    test_scaffold_matrix()
    test_refuses_overwrite_without_force()
    test_no_client_no_server_conflict()
    test_no_client_and_no_server_individually()
    test_name_sanitization()
    test_manifest_never_contains_deprecated_keys()
    test_readme_and_fxlintrc_present()
    test_author_and_desc_flags()

    print(f"\n{_pass} passed, {_fail} failed")
    return 1 if _fail else 0


if __name__ == "__main__":
    sys.exit(main())
