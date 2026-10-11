"""Step 5B tests 61-72 (+ the architectural source guard): frozen behavior stays frozen.

61     short_sword hashes unchanged (OBJ, record, preview, GLB, manifest)
62-65  dagger, long_sword, curved_sword, great_sword seed-1337 goldens unchanged, byte for byte
66-72  the Step 5A, 4, 3, 2.75, 2.5, 2 and 1 suites pass at their frozen counts, in fresh interpreters
Architecture:
  * every generic source is byte-identical to Step 4, and every Step 5A blade source to Step 5A
  * no generic module names a hafted family, imports the hafted code, or branches on an asset
    type: persistence, registry, CLI, package exporter and validator, desktop, viewer, preview
  * forge/catalog.py only registers
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from arsenal_support import (
    FROZEN_GLB_1337,
    FROZEN_MANIFEST_1337,
    FROZEN_OBJ1_1337,
    FROZEN_PIXELS_1337,
    FROZEN_RECORD_CONTENT_1337,
)
from arsenal_support import build_package as build_blade_package
from arsenal_support import presented as blade_presented
from engine_support import build as build_short_package
from forge.catalog import REGISTRY
from forge.export.obj import obj_bytes
from forge.hashing import geometry_sha256
from forge.record import build_record, dumps_record
from forge.registry import export_asset, generate_asset, present_asset, render_asset_preview
from forge.render import encode_preview_png, preview_metadata
from forge.render.settings import PreviewSettings
from forge.sword import generate_sword
from forge_test_support import REPO_ROOT
from hafted_support import BLADE_GOLDEN, EXAMPLES, FAMILIES, NEW_IDENTIFIERS, sha256

STEP4 = json.loads((REPO_ROOT / "tests" / "arsenal_frozen_sources.json").read_text())
STEP5A = json.loads((REPO_ROOT / "tests" / "hafted_frozen_sources.json").read_text())["step5a"]
ASSET_TYPES = ("short_sword", "dagger", "long_sword", "curved_sword", "great_sword") + FAMILIES
FROZEN_GROUPS = {   # step -> (modules, frozen test count)
    "Step 5A": (("test_arsenal_families", "test_arsenal_geometry", "test_arsenal_presentation",
                 "test_arsenal_persistence", "test_arsenal_engine", "test_arsenal_viewer", "test_arsenal_desktop",
                 "test_arsenal_frozen"), 112),
    "Step 4": (("test_viewer_cli", "test_viewer_independence", "test_viewer_ingest", "test_viewer_render"), 94),
    "Step 3": (("test_engine_export", "test_engine_manifest", "test_engine_validator", "test_engine_integration"), 84),
    "Step 2.75": (("test_desktop_controller", "test_desktop_session", "test_desktop_guards", "test_desktop_window"), 49),
    "Step 2.5": (("test_registry_core", "test_registry_dispatch", "test_registry_family", "test_registry_guards"), 44),
    "Step 2": (("test_step2_cli", "test_step2_export", "test_step2_guards", "test_step2_presentation",
                "test_step2_record", "test_step2_render"), 77),
    "Step 1": (("test_prng", "test_seed", "test_determinism", "test_geometry", "test_obj_export", "test_cli"), 68),
}


class TestFrozenShortSword(unittest.TestCase):
    def test_61_short_sword_hashes_unchanged(self):
        self.assertEqual(sha256(obj_bytes(generate_sword(1337, 1))), FROZEN_OBJ1_1337)
        a = generate_asset(REGISTRY, "short_sword", 1337, 1)
        p = present_asset(REGISTRY, a, REGISTRY.presentation("forge.presentation", 1).versions)
        image = render_asset_preview(REGISTRY, p, PreviewSettings(1, "three_quarter", 480, 960, 2))
        self.assertEqual(image.pixels_sha256, FROZEN_PIXELS_1337)
        self.assertEqual(build_record(p, image, forge_version="x")["integrity"]["record_content_sha256"],
                         FROZEN_RECORD_CONTENT_1337)
        pkg = build_short_package(1337)
        self.assertEqual((pkg.glb_sha256, pkg.manifest_sha256), (FROZEN_GLB_1337, FROZEN_MANIFEST_1337))


class TestFrozenBlades(unittest.TestCase):
    """62-65: every Step 5A seed-1337 artifact, rebuilt now, equals the file Step 5A wrote."""

    def check(self, family):
        g = BLADE_GOLDEN[family]
        p = blade_presented(family)
        self.assertEqual(geometry_sha256(p.asset), g["integrity"]["geometry_sha256"])
        gp = g["preview"]
        image = render_asset_preview(REGISTRY, p, PreviewSettings(1, gp["view"], gp["width"], gp["height"], gp["ssaa"]))
        self.assertEqual(image.pixels_sha256, gp["pixels_sha256"])
        record = dumps_record(build_record(p, image, forge_version="0.5.0")).encode("ascii")
        self.assertEqual(record, (EXAMPLES / f"{family}_record_seed1337.json").read_bytes())
        self.assertEqual(json.loads(record)["integrity"], g["integrity"])
        png = encode_preview_png(image, preview_metadata(p, image, g["integrity"]["record_content_sha256"]))
        self.assertEqual(png, (EXAMPLES / f"{family}_preview_seed1337_three_quarter.png").read_bytes())
        pkg = build_blade_package(family, 1337, fresh=True)
        self.assertEqual(pkg.glb, (EXAMPLES / f"{family}_seed1337_v1.forgepkg" / "asset.glb").read_bytes())
        self.assertEqual(pkg.manifest, (EXAMPLES / f"{family}_seed1337_v1.forgepkg" / "manifest.json").read_bytes())
        self.assertEqual({s["name"]: {"translation": s["translation"], "rotation": s["rotation"]}
                          for s in pkg.manifest_data["sockets"]}, g["sockets"])
        self.assertEqual((pkg.manifest_data["collision"]["vertices"], pkg.manifest_data["collision"]["triangles"]),
                         (g["collision"]["vertices"], g["collision"]["triangles"]))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / g["obj2"]["file"]
            export_asset(REGISTRY, p.asset, p, "obj", 2, out)
            self.assertEqual(sha256(out.read_bytes()), g["obj2"]["obj_sha256"])

    def test_62_dagger_unchanged(self):
        self.check("dagger")

    def test_63_long_sword_unchanged(self):
        self.check("long_sword")

    def test_64_curved_sword_unchanged(self):
        self.check("curved_sword")

    def test_65_great_sword_unchanged(self):
        self.check("great_sword")


class TestFrozenSuites(unittest.TestCase):
    """66-72: each earlier step's suite passes, at its frozen count, in a fresh interpreter."""

    def run_group(self, step):
        modules, count = FROZEN_GROUPS[step]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "tests")]))
        r = subprocess.run([sys.executable, "-m", "unittest", *modules], cwd=REPO_ROOT / "tests", env=env,
                           capture_output=True, text=True, timeout=3600)
        ran = re.search(r"^Ran (\d+) tests?", r.stderr, re.M)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIsNotNone(ran)
        self.assertEqual(int(ran.group(1)), count, f"{step} should still have {count} tests")

    def test_66_step_5a_suite_passes(self):
        self.run_group("Step 5A")

    def test_67_step_4_suite_passes(self):
        self.run_group("Step 4")

    def test_68_step_3_suite_passes(self):
        self.run_group("Step 3")

    def test_69_step_2_75_suite_passes(self):
        self.run_group("Step 2.75")

    def test_70_step_2_5_suite_passes(self):
        self.run_group("Step 2.5")

    def test_71_step_2_suite_passes(self):
        self.run_group("Step 2")

    def test_72_step_1_suite_passes(self):
        self.run_group("Step 1")


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def code_strings(t):
    skip = {id(n.body[0].value) for n in ast.walk(t)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(t) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip]


def imports(t):
    out = []
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
    return out


class TestArchitecture(unittest.TestCase):
    """The architectural source guard."""

    GENERIC = sorted(STEP4["generic"]) + [f"forge_engine_viewer/{n}" for n in sorted(STEP4["viewer"])] + \
        ["forge/render/fit.py"]
    GUARDED = ("forge/record.py", "forge/registry.py", "forge/cli.py", "forge/engine/package.py",
               "forge/engine/glb.py", "forge/engine/validate.py", "forge_desktop/session.py",
               "forge_desktop/controller.py", "forge_desktop/window.py", "forge_engine_viewer/ingest.py")

    def test_frozen_sources_are_byte_identical(self):
        expected = {**STEP4["generic"], **{f"forge_engine_viewer/{k}": v for k, v in STEP4["viewer"].items()}, **STEP5A}
        changed = [rel for rel, digest in sorted(expected.items()) if sha256((REPO_ROOT / rel).read_bytes()) != digest]
        self.assertEqual(changed, [], "Step 5B changed a frozen source")
        product = {p.relative_to(REPO_ROOT).as_posix() for pkg in ("forge", "forge_desktop", "forge_engine_viewer")
                   for p in (REPO_ROOT / pkg).rglob("*.py")}
        new = sorted(product - set(expected) - {"forge/catalog.py", "forge/__init__.py"})
        self.assertEqual(new, ["forge/assets/hafted.py", "forge/hafted/__init__.py", "forge/hafted/axe.py",
                               "forge/hafted/haft.py", "forge/hafted/mace.py", "forge/hafted/model.py",
                               "forge/hafted/one_hand_axe.py", "forge/hafted/presentation.py",
                               "forge/hafted/shapes.py", "forge/hafted/two_hand_axe.py", "forge/hafted/war_hammer.py"])

    def test_generic_code_names_no_hafted_family(self):
        for must in self.GUARDED:
            self.assertIn(must, self.GENERIC)
        for rel in self.GENERIC + sorted(STEP5A):
            with self.subTest(file=rel):
                t = tree(REPO_ROOT / rel)
                strings = code_strings(t)
                for ident in NEW_IDENTIFIERS:
                    self.assertFalse(any(ident in s for s in strings), f"{rel} names {ident!r}")
                for mod in imports(t):
                    self.assertFalse(mod.startswith(("forge.hafted", "forge.assets.hafted")), f"{rel} imports {mod}")
                for node in ast.walk(t):
                    if isinstance(node, ast.Compare):
                        for c in [node.left, *node.comparators]:
                            if isinstance(c, ast.Constant) and rel != "forge/cli.py":
                                self.assertNotIn(c.value, ASSET_TYPES, f"{rel}:{node.lineno} branches on an asset type")

    def test_catalog_only_registers(self):
        t = tree(REPO_ROOT / "forge" / "catalog.py")
        for node in ast.walk(t):
            if isinstance(node, (ast.If, ast.IfExp, ast.While)):
                for sub in ast.walk(node.test):
                    if isinstance(sub, ast.Constant):
                        self.assertNotIn(sub.value, ASSET_TYPES + NEW_IDENTIFIERS)
        strings = code_strings(t)
        for family in FAMILIES:
            self.assertNotIn(family, strings, "catalog lists families through forge.assets.hafted, not by name")
        self.assertEqual(strings.count("forge.hafted-presentation"), 2, "obj:2 and glb:1 accept the hafted presentation")
        self.assertIn("forge.assets", imports(t))

    def test_no_contract_v2(self):
        from forge.engine.contract import SUPPORTED_CONTRACT_VERSIONS
        from forge_engine_viewer import contract_v1
        self.assertEqual(SUPPORTED_CONTRACT_VERSIONS, (1,))
        self.assertEqual(contract_v1.REQUIRED_SOCKETS, ("socket_grip", "socket_tip"))


if __name__ == "__main__":
    unittest.main()
