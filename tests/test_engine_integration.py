"""Step 3 tests 50-56 (+ golden fixture, CLI commands, source guards, real window).

50-52: the GUI and CLI reach GLB only through the registry. 53-56: every frozen
suite from Steps 1, 2, 2.5 and 2.75 still passes at its frozen test count, run in
a fresh interpreter.
"""

import ast
import contextlib
import dataclasses
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except Exception:  # ImportError (no tkinter) or TclError (no display)
    HAVE_DISPLAY = False

from desktop_support import SMALL_PREVIEW, FakeDialogs, make_session
from engine_support import (
    GOLDEN,
    GOLDEN_DIR,
    GOLDEN_GLB_SHA256,
    GOLDEN_MANIFEST_SHA256,
    cached,
    rehash,
    repack,
    sha256,
    split,
)
from forge import catalog
from forge.catalog import REGISTRY
from forge.cli import main
from forge.engine.contract import CONTRACT_ID
from forge.engine.validate import validate_package
from forge.registry import build_registry
from forge_desktop.controller import ForgeController
from forge_test_support import REPO_ROOT
from registry_fixtures import spying_registry

EXAMPLE_RECORD = REPO_ROOT / "examples" / "asset_record_seed1337.json"
FROZEN_GROUPS = {   # step -> (modules, frozen test count)
    "Step 1": (("test_prng", "test_seed", "test_determinism", "test_geometry", "test_obj_export", "test_cli"), 68),
    "Step 2": (("test_step2_cli", "test_step2_export", "test_step2_guards", "test_step2_presentation",
                "test_step2_record", "test_step2_render"), 77),
    "Step 2.5": (("test_registry_core", "test_registry_dispatch", "test_registry_family", "test_registry_guards"), 44),
    "Step 2.75": (("test_desktop_controller", "test_desktop_session", "test_desktop_guards", "test_desktop_window"), 49),
}


def run_cli(*argv, registry=REGISTRY, cwd=None):
    out, err = io.StringIO(), io.StringIO()
    old = os.getcwd()
    try:
        if cwd:
            os.chdir(cwd)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv), registry=registry)
    finally:
        os.chdir(old)
    return code, out.getvalue(), err.getvalue()


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def code_strings(t):
    doc = {id(n.body[0].value) for n in ast.walk(t)
           if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
           and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(t) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in doc]


def imports(t):
    out = []
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
    return out


class TestGuiThroughRegistry(unittest.TestCase):
    def test_50_gui_offers_glb_only_through_the_registry(self):
        opts = ForgeController(REGISTRY, preview_size=SMALL_PREVIEW).options("short_sword")
        glb = opts.exporter("glb:1")
        self.assertEqual((glb.format_id, glb.format_version, glb.extension, glb.contract),
                         ("glb", 1, ".forgepkg", (CONTRACT_ID, 1)))
        self.assertEqual(glb.label, "GLB format 1 · with presentation data · + manifest file · forge.engine-contract v1")
        self.assertEqual(glb.action_label, "Export Engine Package…")
        self.assertEqual(opts.exporter("obj:1").action_label, "Export…")

        # Same GUI code, a registry whose asset type doesn't offer glb: the option disappears.
        tables = dict(assets=catalog.ASSETS, generators=catalog.GENERATORS, presentations=catalog.PRESENTATIONS,
                      exporters=catalog.EXPORTERS, previews=catalog.PREVIEWS)
        entry = catalog.ASSETS[0]
        no_glb = dataclasses.replace(entry, descriptor=dataclasses.replace(
            entry.descriptor, export_formats=(("obj", 1), ("obj", 2))))
        reg = build_registry(**{**tables, "assets": (no_glb,)})
        self.assertEqual([c.key for c in ForgeController(reg).options("short_sword").exporters], ["obj:1", "obj:2"])

        # ...and one whose glb entry declares no contract: shown as a plain export.
        plain = tuple(dataclasses.replace(e, contract=None) for e in catalog.EXPORTERS)
        reg = build_registry(**{**tables, "exporters": plain})
        choice = ForgeController(reg).options("short_sword").exporter("glb:1")
        self.assertEqual((choice.contract, choice.action_label), (None, "Export…"))
        self.assertNotIn("contract", choice.label)

    def test_50b_session_exports_an_engine_package(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "picked.forgepkg"
            session, dialogs = make_session(dialogs=FakeDialogs(export_path=target))
            session.set_seed_text("1337")
            session.generate()
            self.assertIsNone(session.view_model().export_key)       # three formats: nothing preselected
            session.select_export("glb:1")
            vm = session.view_model()
            self.assertEqual(vm.export_action, "Export Engine Package…")
            self.assertIn(("Engine contract", "forge.engine-contract v1"), vm.details)
            session.export()
            vm = session.view_model()
            self.assertEqual(dialogs.errors, [])
            self.assertEqual(dialogs.asked[-1][1:3], ("short_sword_seed1337_v1_glb1.forgepkg", ".forgepkg"))
            self.assertEqual(vm.status, "Export complete: glb:1 → picked.forgepkg/asset.glb "
                                        "(+ picked.forgepkg/manifest.json) · forge.engine-contract v1 validated")
            rows = dict(vm.details)
            self.assertEqual(rows["Last export"], f"glb:1 → {target / 'asset.glb'}")
            self.assertEqual(rows["Last export · manifest"], str(target / "manifest.json"))
            self.assertEqual(rows["Last export · status"], "validated against forge.engine-contract v1 before writing")
            self.assertEqual(sha256((target / "asset.glb").read_bytes()), GOLDEN_GLB_SHA256)
            self.assertEqual(sha256((target / "manifest.json").read_bytes()), GOLDEN_MANIFEST_SHA256)
            session.select_export("obj:1")
            self.assertEqual(session.view_model().export_action, "Export…")
            session.generate()                                         # a new asset forgets the last export
            self.assertNotIn("Last export", dict(session.view_model().details))

    def test_51_desktop_shell_does_not_import_or_name_the_glb_implementation(self):
        banned_literals = re.compile(r"(?i)\bglb\b|gltf|forgepkg|asset\.glb|manifest\.json|collision_hull|socket_")
        for path in sorted((REPO_ROOT / "forge_desktop").glob("*.py")):
            with self.subTest(file=path.name):
                t = tree(path)
                for mod in imports(t):
                    self.assertFalse(mod.startswith("forge.engine"), f"{path.name} imports {mod}")
                    self.assertFalse(mod.startswith(("forge.export", "forge.assets")), f"{path.name} imports {mod}")
                hits = [s for s in code_strings(t) if banned_literals.search(s)]
                self.assertEqual(hits, [], f"{path.name} hard-codes {hits}")


class TestCli(unittest.TestCase):
    def test_52_cli_exports_glb_through_the_registry(self):
        reg, spies = spying_registry()
        glb_spy = spies["export"][[e.format_id for e in catalog.EXPORTERS].index("glb")]
        with tempfile.TemporaryDirectory() as tmp:
            code, out, err = run_cli("generate", "short_sword", "--seed", "1337", "--generator-version", "1",
                                     "--presentation-version", "1", "--export", "glb:1", registry=reg, cwd=tmp)
            self.assertEqual((code, err), (0, ""))
            self.assertEqual(glb_spy.calls, 1)
            pkg = Path(tmp) / "output" / "short_sword_seed1337_v1.forgepkg"
            self.assertIn(f"wrote              {Path('output/short_sword_seed1337_v1.forgepkg/asset.glb')}", out)
            self.assertIn(f"sha256             {GOLDEN_GLB_SHA256}", out)
            self.assertIn("contract           forge.engine-contract v1 (validated before writing)", out)
            self.assertEqual(sha256((pkg / "manifest.json").read_bytes()), GOLDEN_MANIFEST_SHA256)

            code, out, err = run_cli("export", str(EXAMPLE_RECORD), "--format", "glb:1", "--out",
                                     str(Path(tmp) / "from_record.forgepkg"), "--json", registry=reg)
            self.assertEqual(code, 0, err)
            self.assertEqual(glb_spy.calls, 2)
            report = json.loads(out)
            self.assertEqual(sorted(report["files"].values()), sorted([GOLDEN_GLB_SHA256, GOLDEN_MANIFEST_SHA256]))
            self.assertEqual(report["contract"], {"id": CONTRACT_ID, "version": 1})
        t = tree(REPO_ROOT / "forge" / "cli.py")
        engine_imports = [m for m in imports(t) if m.startswith("forge.engine")]
        self.assertEqual(engine_imports, ["forge.engine.validate"])      # validation only; writing goes via registry

    def test_52b_cli_refusals_and_exit_codes(self):
        with tempfile.TemporaryDirectory() as tmp:
            cases = [
                (("generate", "short_sword", "--seed", "1337", "--generator-version", "1", "--export", "glb:1"),
                 2, "--presentation-version is required"),                   # no implicit presentation version
                (("generate", "short_sword", "--seed", "1", "--generator-version", "1", "--presentation-version",
                  "1", "--export", "glb:2"), 2, "unsupported export version 2 for 'glb'; supported: \\[1\\]"),
                (("generate", "short_sword", "--seed", "1", "--generator-version", "1", "--presentation-version",
                  "1", "--export", "glb:1", "--out", "x.glb"), 2, "must end in .forgepkg"),
                (("export", str(EXAMPLE_RECORD), "--format", "glb"), 2, "FORMAT:VERSION"),
                (("export", str(EXAMPLE_RECORD), "--format", "fbx:1"), 2, "unknown export format"),
                (("export", "missing.json", "--format", "glb:1"), 2, "missing.json"),
                (("validate-package", "nowhere.forgepkg"), 2, "not a package directory"),
            ]
            for argv, want, pattern in cases:
                with self.subTest(argv=argv):
                    code, out, err = run_cli(*argv, cwd=tmp)
                    self.assertEqual(code, want, err)
                    self.assertRegex(err, pattern)
            self.assertFalse((Path(tmp) / "output").exists())               # nothing written on refusal

            tampered = Path(tmp) / "tampered.forgepkg"
            shutil.copytree(GOLDEN_DIR, tampered)
            data = bytearray((tampered / "asset.glb").read_bytes())
            data[-5] ^= 0xFF
            (tampered / "asset.glb").write_bytes(bytes(data))
            code, _, err = run_cli("validate-package", str(tampered))
            self.assertEqual(code, 3)
            self.assertIn("package invalid:", err)

            record = json.loads(EXAMPLE_RECORD.read_text())
            record["presentation"]["materials"]["blade"]["roughness"] = 0.9
            bad = Path(tmp) / "bad.json"
            bad.write_text(json.dumps(record))
            code, _, err = run_cli("export", str(bad), "--format", "glb:1", "--out", str(Path(tmp) / "b.forgepkg"))
            self.assertEqual(code, 3, err)
            self.assertFalse((Path(tmp) / "b.forgepkg").exists())

    def test_52c_validate_package_and_reproduce(self):
        code, out, err = run_cli("validate-package", str(GOLDEN_DIR), "--reproduce", "--json")
        self.assertEqual(code, 0, err)
        report = json.loads(out)
        self.assertEqual(report["status"], "valid")
        self.assertEqual(report["reproduced"], ["asset.glb", "manifest.json"])
        self.assertEqual((report["glb_sha256"], report["manifest_sha256"]), (GOLDEN_GLB_SHA256, GOLDEN_MANIFEST_SHA256))
        self.assertEqual(report["sockets"], {k: v["translation"] for k, v in GOLDEN["sockets"].items()})
        code, out, _ = run_cli("validate-package", str(GOLDEN_DIR))
        self.assertEqual(code, 0)
        self.assertIn("Black Lantern Forge - engine package valid", out)
        self.assertIn("checks passed      24:", out)

        with tempfile.TemporaryDirectory() as tmp:     # valid, but not what Forge produces for that identity
            other = Path(tmp) / "other.forgepkg"
            shutil.copytree(GOLDEN_DIR, other)
            m = json.loads((other / "manifest.json").read_text())
            m["asset"]["seed"] = "7"
            gltf, _, bin_chunk = split((other / "asset.glb").read_bytes())
            gltf["asset"]["extras"]["forge_seed"] = "7"
            glb = repack(gltf, bin_chunk)
            (other / "asset.glb").write_bytes(glb)
            (other / "manifest.json").write_bytes(rehash(glb, m))
            self.assertEqual(run_cli("validate-package", str(other))[0], 0)          # structurally valid
            code, _, err = run_cli("validate-package", str(other), "--reproduce")
            self.assertEqual(code, 3)
            self.assertIn("not reproduced", err)

    def test_52d_cli_subprocess_matches_golden(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
            r = subprocess.run([sys.executable, "-m", "forge", "generate", "short_sword", "--seed", "1337",
                                "--generator-version", "1", "--presentation-version", "1", "--export", "glb:1"],
                               cwd=tmp, env=env, capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)
            pkg = Path(tmp) / "output" / "short_sword_seed1337_v1.forgepkg"
            for name in ("asset.glb", "manifest.json"):
                self.assertEqual((pkg / name).read_bytes(), (GOLDEN_DIR / name).read_bytes())


class TestGoldenFixture(unittest.TestCase):
    def test_golden_fixture_files_and_record(self):
        self.assertEqual(sorted(p.name for p in GOLDEN_DIR.iterdir()), ["asset.glb", "manifest.json"])
        self.assertEqual((GOLDEN_DIR / "asset.glb").read_bytes(), cached().glb)
        self.assertEqual((GOLDEN_DIR / "manifest.json").read_bytes(), cached().manifest)
        self.assertEqual(GOLDEN["files"]["asset.glb"]["sha256"], GOLDEN_GLB_SHA256)
        self.assertEqual(GOLDEN["files"]["manifest.json"]["sha256"], GOLDEN_MANIFEST_SHA256)
        self.assertEqual(GOLDEN["identity"]["contract"], {"id": CONTRACT_ID, "version": 1})
        self.assertEqual(GOLDEN["hashes"], {k: v["sha256"] for k, v in cached().manifest_data["hashes"].items()})
        report = validate_package(GOLDEN_DIR)
        self.assertEqual(report.sockets, tuple((k, tuple(v["translation"])) for k, v in GOLDEN["sockets"].items()))

    def test_earlier_goldens_untouched(self):
        frozen = {   # byte hashes of the Step 2 / 2.75 example fixtures, as shipped before Step 3
            "asset_record_seed1337.json": "376fb576b8525a6caab9df2c359aefbc4e16e792091104160e07ea9e5bd0eda2",
            "preview_seed1337_three_quarter.png": "6454069ef775323a0bf9b828e86809a6fed9576d2641fdbb22283837dc92da3a",
        }
        for name, digest in frozen.items():
            self.assertEqual(sha256((REPO_ROOT / "examples" / name).read_bytes()), digest, name)


class TestEngineSourceGuards(unittest.TestCase):
    def test_validator_is_independent_of_the_writer(self):
        allowed_forge = {"forge.engine.contract", "forge.errors"}
        t = tree(REPO_ROOT / "forge" / "engine" / "validate.py")
        for mod in imports(t):
            if mod.startswith("forge"):
                self.assertIn(mod, allowed_forge, f"validate.py imports {mod}")
            else:
                self.assertIn(mod.split(".")[0], {"__future__", "hashlib", "json", "math", "re", "struct",
                                                  "dataclasses", "pathlib"}, f"validate.py imports {mod}")

    def test_engine_package_is_stdlib_only_and_asset_agnostic(self):
        stdlib = {"__future__", "hashlib", "json", "math", "re", "struct", "dataclasses", "pathlib", "types", "typing"}
        for path in sorted((REPO_ROOT / "forge" / "engine").glob("*.py")):
            with self.subTest(file=path.name):
                t = tree(path)
                for mod in imports(t):
                    top = mod.split(".")[0]
                    self.assertTrue(top == "forge" or top in stdlib, f"{path.name} imports {mod}")
                    self.assertFalse(mod.startswith(("forge.sword", "forge.assets", "forge.catalog", "forge_desktop")),
                                     f"{path.name} imports {mod}")
                hits = [s for s in code_strings(t) if s in {"short_sword", "blade", "guard", "grip", "pommel",
                                                             "forge.sword"}]
                self.assertEqual(hits, [], f"{path.name} names an asset family: {hits}")


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter and a display")
class TestRealWindowEnginePackage(unittest.TestCase):
    def test_real_window_exports_engine_package(self):
        from forge_desktop.session import SyncRunner
        from forge_desktop.window import build_window
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "win.forgepkg"
            root = tk.Tk()
            root.withdraw()
            try:
                w = build_window(root, controller=ForgeController(REGISTRY, preview_size=SMALL_PREVIEW),
                                 seed_source=lambda: 1337, dialogs=FakeDialogs(export_path=target), runner=SyncRunner())
                w.session.select_asset_type("short_sword")          # Step 5A: several families are registered
                root.update()
                values = list(w.export_combo.cget("values"))
                self.assertTrue(values[0].startswith("GLB format 1"))
                self.assertEqual(w.export_button.cget("text"), "Export…")
                w.random_button.invoke()
                w.generate_button.invoke()
                root.update()
                w.export_combo.current(0)
                w._on_export_selected()
                root.update()
                self.assertEqual(w.export_button.cget("text"), "Export Engine Package…")
                w.export_button.invoke()
                root.update()
                self.assertEqual(sha256((target / "asset.glb").read_bytes()), GOLDEN_GLB_SHA256)
                self.assertTrue(w.status_var.get().endswith("forge.engine-contract v1 validated"))
                menu_labels = [w.export_menu.entrycget(i, "label") for i in range(len(values))]
                self.assertEqual(menu_labels, [f"{v}…" for v in values])
            finally:
                root.destroy()


class TestFrozenSuites(unittest.TestCase):
    """53-56: run each frozen step's suite in a fresh interpreter; it must pass at its frozen count."""

    def run_group(self, step):
        modules, count = FROZEN_GROUPS[step]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "tests")]))
        r = subprocess.run([sys.executable, "-m", "unittest", *modules], cwd=REPO_ROOT / "tests", env=env,
                           capture_output=True, text=True, timeout=900)
        ran = re.search(r"^Ran (\d+) tests?", r.stderr, re.M)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIsNotNone(ran)
        self.assertEqual(int(ran.group(1)), count, f"{step} should still have {count} tests")

    def test_53_step_2_75_suite_passes(self):
        self.run_group("Step 2.75")

    def test_54_step_2_5_suite_passes(self):
        self.run_group("Step 2.5")

    def test_55_step_2_suite_passes(self):
        self.run_group("Step 2")

    def test_56_step_1_suite_passes(self):
        self.run_group("Step 1")


if __name__ == "__main__":
    unittest.main()
