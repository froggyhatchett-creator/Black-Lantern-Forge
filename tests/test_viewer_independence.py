"""Step 4 tests 33-38 and 64-68 (+ independence, immutability and cross-process evidence).

33-38  source guards: the consumer imports nothing from Forge (generator, PRNG, presentation,
       preview renderer, GLB writer, package writer, or anything else)
64-68  every earlier suite still passes at its frozen test count, each in a fresh interpreter

Plus:
  * a contract-drift check against Forge's own table
  * a fresh-process ingestion with Forge absent from disk
  * package immutability
  * agreement with Forge's validator, which is supplementary evidence only
"""

import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from forge_engine_viewer import contract_v1 as V
from forge_engine_viewer.cli import main
from forge_engine_viewer.ingest import ingest
from forge_engine_viewer.render import Camera, build_frame
from forge_engine_viewer.session import ViewerSession
from forge_test_support import REPO_ROOT
from viewer_support import FROZEN_GLB_SHA256, FROZEN_MANIFEST_SHA256, GOLDEN_DIR, VIEWER_PKG, sha256

SOURCES = sorted(VIEWER_PKG.glob("*.py"))
FROZEN_GROUPS = {   # step -> (modules, frozen test count)
    "Step 3": (("test_engine_export", "test_engine_manifest", "test_engine_validator", "test_engine_integration"), 84),
    "Step 2.75": (("test_desktop_controller", "test_desktop_session", "test_desktop_guards", "test_desktop_window"), 49),
    "Step 2.5": (("test_registry_core", "test_registry_dispatch", "test_registry_family", "test_registry_guards"), 44),
    "Step 2": (("test_step2_cli", "test_step2_export", "test_step2_guards", "test_step2_presentation",
                "test_step2_record", "test_step2_render"), 77),
    "Step 1": (("test_prng", "test_seed", "test_determinism", "test_geometry", "test_obj_export", "test_cli"), 68),
}


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def imports(t):
    out = []
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
    return out


def names(t):
    for n in ast.walk(t):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr
        elif isinstance(n, ast.alias):
            yield n.asname or n.name


class TestSourceGuards(unittest.TestCase):
    def assert_never_imported(self, prefixes, forbidden_names=()):
        self.assertGreaterEqual(len(SOURCES), 9)
        for path in SOURCES:
            t = tree(path)
            for mod in imports(t):
                self.assertFalse(mod == "forge" or mod.startswith(prefixes), f"{path.name} imports {mod}")
            for name in names(t):
                self.assertNotIn(name, forbidden_names, f"{path.name} references {name}")

    def test_33_consumer_does_not_import_forge_sword(self):
        self.assert_never_imported(("forge.sword", "forge.assets", "forge.catalog", "forge.registry"),
                                   ("SwordAsset", "generate_asset"))

    def test_34_consumer_does_not_import_generate_sword(self):
        self.assert_never_imported(("forge.",), ("generate_sword", "generate_short_sword_v1"))

    def test_35_consumer_does_not_import_pcg32(self):
        self.assert_never_imported(("forge.prng", "forge.seed"), ("PCG32", "derive_stream"))

    def test_36_consumer_does_not_import_the_forge_preview_renderer(self):
        self.assert_never_imported(("forge.render", "forge.presentation"),
                                   ("render_preview", "derive_presentation", "write_preview_png"))

    def test_37_consumer_does_not_import_the_glb_writer(self):
        self.assert_never_imported(("forge.engine.glb", "forge.export"), ("GlbBuilder", "pack_glb", "write_obj"))

    def test_38_consumer_does_not_import_the_package_writer(self):
        self.assert_never_imported(("forge.engine.package", "forge.engine.validate", "forge.engine.hull"),
                                   ("build_engine_package", "write_engine_package", "validate_package",
                                    "convex_hull"))

    def test_consumer_imports_nothing_from_forge_at_all(self):
        allowed_stdlib = {"__future__", "argparse", "copy", "dataclasses", "hashlib", "json", "math", "pathlib", "re",
                          "struct", "sys", "traceback", "tkinter", "types", "typing"}
        for path in SOURCES:
            for mod in imports(tree(path)):
                top = mod.split(".")[0]
                self.assertTrue(top == "forge_engine_viewer" or top in allowed_stdlib, f"{path.name} imports {mod}")

    def test_dependency_direction_forge_never_imports_the_consumer(self):
        for root in (REPO_ROOT / "forge", REPO_ROOT / "forge_desktop"):
            for path in sorted(root.rglob("*.py")):
                for mod in imports(tree(path)):
                    self.assertFalse(mod.startswith("forge_engine_viewer"), f"{path} imports {mod}")

    def test_consumer_never_writes_files(self):
        writers = {"write_bytes", "write_text", "unlink", "rename", "replace", "mkdir", "rmdir", "remove",
                   "rmtree", "touch", "chmod", "copyfile", "copytree", "dump"}
        for path in SOURCES:
            t = tree(path)
            for n in ast.walk(t):
                if isinstance(n, ast.Attribute):
                    self.assertNotIn(n.attr, writers, f"{path.name} uses .{n.attr}")
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "open":
                    modes = [a.value for a in n.args[1:2] if isinstance(a, ast.Constant)]
                    modes += [k.value.value for k in n.keywords if k.arg == "mode" and isinstance(k.value, ast.Constant)]
                    self.assertEqual(modes, ["rb"], f"{path.name}: open() must be read-only binary")

    def test_tkinter_only_in_the_window_module(self):
        for path in SOURCES:
            uses_tk = any(m.split(".")[0] == "tkinter" for m in imports(tree(path)))
            self.assertEqual(uses_tk, path.name == "window.py", path.name)


class TestContractDrift(unittest.TestCase):
    """The viewer copies the contract instead of importing it; this catches any drift between the copies."""

    def test_viewer_contract_table_matches_forge_contract_v1(self):
        from forge.engine import contract as F
        spec = F.CONTRACT_V1
        self.assertEqual((V.CONTRACT_ID, V.SUPPORTED_VERSIONS), (F.CONTRACT_ID, F.SUPPORTED_CONTRACT_VERSIONS))
        self.assertEqual((V.GLB_FILE, V.MANIFEST_FILE, V.PACKAGE_SUFFIX),
                         (spec.glb_file, spec.manifest_file, spec.package_suffix))
        self.assertEqual((V.RENDER_SCENE, V.COLLISION_SCENE), (spec.render_scene, spec.collision_scene))
        self.assertEqual((V.REQUIRED_SOCKETS, V.SOCKET_PREFIX, V.ORIGIN_SOCKET),
                         (spec.required_sockets, spec.socket_prefix, spec.origin_socket))
        self.assertEqual((V.COLLISION_NODE, V.COLLISION_REPRESENTATIONS),
                         (spec.collision_node, spec.collision_representations))
        self.assertEqual(dict(V.COORDINATES), dict(spec.coordinates))
        self.assertEqual((V.MANIFEST_SECTIONS, V.MATERIAL_MODEL, V.CHANNELS, V.LOD_LEVELS),
                         (spec.manifest_sections, spec.material_model, spec.channels, spec.lod_levels))
        self.assertEqual(set(V.BYTE_HASHES) | set(V.SEMANTIC_HASHES), set(spec.package_hashes))
        self.assertEqual((V.CONTENT_HASH, V.SOURCE_HASH_PREFIX), (spec.content_hash, spec.source_hash_prefix))
        self.assertEqual((V.GLB_MAGIC, V.GLB_VERSION, V.CHUNK_JSON, V.CHUNK_BIN, V.GLTF_VERSION),
                         (F.GLB_MAGIC, F.GLB_VERSION, F.CHUNK_JSON, F.CHUNK_BIN, F.GLTF_VERSION))


def snapshot(directory: Path):
    return sorted((p.name, p.stat().st_mtime_ns, p.stat().st_size, sha256(p.read_bytes())) for p in directory.iterdir())


class TestImmutability(unittest.TestCase):
    def test_package_is_byte_identical_after_ingestion_rendering_and_cli(self):
        before = snapshot(GOLDEN_DIR)
        dir_mtime = GOLDEN_DIR.stat().st_mtime_ns
        refuse_writes = mock.patch.multiple(Path, write_bytes=mock.DEFAULT, write_text=mock.DEFAULT,
                                            unlink=mock.DEFAULT, rename=mock.DEFAULT, replace=mock.DEFAULT,
                                            mkdir=mock.DEFAULT, touch=mock.DEFAULT)
        with refuse_writes as patched, mock.patch("os.replace") as os_replace, mock.patch("os.remove") as os_remove:
            pkg = ingest(GOLDEN_DIR)
            for view in ("three_quarter", "front", "side"):
                build_frame(pkg, width=640, height=800, camera=Camera.preset(view), mode="render+collision",
                            show_sockets=True)
            s = ViewerSession()
            s.open(GOLDEN_DIR)
            with mock.patch("sys.stdout"):
                self.assertEqual(main([str(GOLDEN_DIR), "--dump-summary"]), 0)
                self.assertEqual(main([str(GOLDEN_DIR), "--validate-only", "--json"]), 0)
            for name, m in patched.items():
                self.assertFalse(m.called, f"Path.{name} was called")
            self.assertFalse(os_replace.called or os_remove.called)
        self.assertEqual(snapshot(GOLDEN_DIR), before)
        self.assertEqual(GOLDEN_DIR.stat().st_mtime_ns, dir_mtime)
        self.assertEqual(sha256((GOLDEN_DIR / "asset.glb").read_bytes()), FROZEN_GLB_SHA256)
        self.assertEqual(sha256((GOLDEN_DIR / "manifest.json").read_bytes()), FROZEN_MANIFEST_SHA256)

    def test_invalid_package_is_left_exactly_as_found(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "bad.forgepkg"
            shutil.copytree(GOLDEN_DIR, d)
            data = bytearray((d / "asset.glb").read_bytes())
            data[-9] ^= 0x10
            (d / "asset.glb").write_bytes(bytes(data))
            before = snapshot(d)
            with mock.patch("sys.stderr"):
                self.assertEqual(main([str(d), "--validate-only"]), 3)
            self.assertEqual(snapshot(d), before)                          # not "fixed", not normalized


class TestCrossProcess(unittest.TestCase):
    def test_fresh_process_with_forge_absent_from_disk(self):
        """Only the viewer and the frozen package exist in the directory; Forge is not importable at all."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            shutil.copytree(VIEWER_PKG, tmp / "forge_engine_viewer", ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(GOLDEN_DIR, tmp / "golden.forgepkg")
            env = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
            run = lambda *args: subprocess.run([sys.executable, "-E", "-s", *args], cwd=tmp, env=env,
                                               capture_output=True, text=True, timeout=120)
            probe = run("-c", "import forge")
            self.assertNotEqual(probe.returncode, 0)
            self.assertIn("No module named 'forge'", probe.stderr)
            r = run("-m", "forge_engine_viewer", "golden.forgepkg", "--dump-summary", "--json")
            self.assertEqual(r.returncode, 0, r.stderr)
            d = json.loads(r.stdout)
            self.assertEqual(d["hashes"]["glb_sha256"], FROZEN_GLB_SHA256)
            self.assertEqual(d["hashes"]["manifest_file_sha256"], FROZEN_MANIFEST_SHA256)
            self.assertEqual({s["name"]: s["translation"] for s in d["sockets"]},
                             {"socket_grip": [0.0, 0.0, 0.0], "socket_tip": [0.0, 0.60488361120224, 0.0]})
            self.assertEqual((d["collision"]["vertices"], d["collision"]["triangles"]), (49, 94))
            r = run("-c", "import sys, runpy; sys.argv = ['x', 'golden.forgepkg', '--validate-only'];"
                          "\ntry: runpy.run_module('forge_engine_viewer', run_name='__main__')"
                          "\nexcept SystemExit as e: code = e.code"
                          "\nloaded = sorted(m for m in sys.modules if m == 'forge' or m.startswith('forge.'))"
                          "\nprint('EXIT', code, 'FORGE_MODULES', loaded)")
            self.assertIn("EXIT 0 FORGE_MODULES []", r.stdout, r.stderr)
            self.assertEqual(sha256((tmp / "golden.forgepkg" / "asset.glb").read_bytes()), FROZEN_GLB_SHA256)

    def test_fresh_process_with_forge_present_but_blocked(self):
        script = (
            "import sys\n"
            "class Block:\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        if name == 'forge' or name.startswith('forge.'):\n"
            "            raise ImportError('forge is blocked in this test: ' + name)\n"
            "sys.meta_path.insert(0, Block())\n"
            "from forge_engine_viewer.ingest import ingest\n"
            "from forge_engine_viewer.render import build_frame, Camera\n"
            f"pkg = ingest({str(GOLDEN_DIR)!r})\n"
            "f = build_frame(pkg, width=640, height=800, camera=Camera.preset('front'), mode='render+collision', show_sockets=True)\n"
            "print(pkg.glb_sha256, f.stats['render_triangles'], f.stats['collision_edges'], f.stats['sockets'])\n"
        )
        env = dict(os.environ, PYTHONPATH=str(REPO_ROOT))
        r = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=env, capture_output=True, text=True,
                           timeout=120)
        self.assertEqual(r.returncode, 0, r.stderr)
        digest, drawn, edges, sockets = r.stdout.split()
        self.assertEqual((digest, int(edges), int(sockets)), (FROZEN_GLB_SHA256, 141, 2))
        self.assertGreater(int(drawn), 0)


class TestSupplementaryAgreementWithForgeValidator(unittest.TestCase):
    """Forge's own validator is consulted here only as a second opinion, never by the viewer."""

    def test_both_accept_the_golden_package_and_agree_on_what_it_holds(self):
        from forge.engine.validate import validate_package
        forge_report = validate_package(GOLDEN_DIR)
        viewer = ingest(GOLDEN_DIR)
        self.assertEqual(set(forge_report.hashes_verified), set(viewer.hashes_verified))
        self.assertEqual(dict(forge_report.sockets), {s.name: s.world.translation for s in viewer.sockets})
        self.assertEqual((forge_report.collision_vertices, forge_report.collision_triangles),
                         (len(viewer.collision.positions), viewer.collision.triangle_count))
        self.assertEqual((forge_report.vertices, forge_report.triangles), (viewer.lods[0].vertices, viewer.lods[0].triangles))

    def test_both_refuse_the_same_damaged_packages(self):
        from forge.engine.validate import validate_package
        from forge.errors import EngineContractError
        from forge_engine_viewer.errors import IngestionError
        from viewer_support import node, prim, variant
        cases = {
            "no socket_tip": dict(gltf_fn=lambda g: node(g, "socket_tip")[1].__setitem__("name", "tip")),
            "lines": dict(gltf_fn=lambda g: prim(g, "blade").__setitem__("mode", 1)),
            "units": dict(manifest_fn=lambda m: m["coordinates"].__setitem__("units", "centimeters")),
            "version 2": dict(manifest_fn=lambda m: m["contract"].__setitem__("version", 2)),
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, kwargs in cases.items():
                with self.subTest(case=name):
                    d = variant(Path(tmp) / re.sub(r"\W", "_", name), **kwargs)
                    with self.assertRaises(EngineContractError):
                        validate_package(d)
                    with self.assertRaises(IngestionError):
                        ingest(d)


class TestFrozenSuites(unittest.TestCase):
    """64-68: each earlier step's suite passes, at its frozen count, in a fresh interpreter."""

    def run_group(self, step):
        modules, count = FROZEN_GROUPS[step]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "tests")]))
        r = subprocess.run([sys.executable, "-m", "unittest", *modules], cwd=REPO_ROOT / "tests", env=env,
                           capture_output=True, text=True, timeout=900)
        ran = re.search(r"^Ran (\d+) tests?", r.stderr, re.M)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIsNotNone(ran)
        self.assertEqual(int(ran.group(1)), count, f"{step} should still have {count} tests")

    def test_64_step_3_suite_passes(self):
        self.run_group("Step 3")

    def test_65_step_2_75_suite_passes(self):
        self.run_group("Step 2.75")

    def test_66_step_2_5_suite_passes(self):
        self.run_group("Step 2.5")

    def test_67_step_2_suite_passes(self):
        self.run_group("Step 2")

    def test_68_step_1_suite_passes(self):
        self.run_group("Step 1")


if __name__ == "__main__":
    unittest.main()
