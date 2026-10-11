"""Step 5A tests 61-71 (+ the architecture test): frozen behavior and generic infrastructure.

61-65  the short_sword's OBJ, record, preview, GLB and manifest hashes are unchanged
66-71  the Step 4, 3, 2.75, 2.5, 2 and 1 suites pass at their frozen test counts, in fresh interpreters
Architecture: every generic source is byte-identical to its Step 4 release; no generic module names a
blade family, imports the blade code, or branches on an asset type; only forge/catalog.py
(registration data) and forge/__init__.py (version string) changed among existing product files.
"""

import ast
import json
import os
import re
import subprocess
import sys
import unittest

from arsenal_support import (
    EXAMPLES,
    FROZEN_GEOMETRY_1337,
    FROZEN_GLB_1337,
    FROZEN_MANIFEST_1337,
    FROZEN_OBJ1_1337,
    FROZEN_PIXELS_1337,
    FROZEN_RECORD_CONTENT_1337,
    FROZEN_SOCKET_TIP_1337,
    sha256,
)
from engine_support import build
from forge.catalog import REGISTRY
from forge.export.obj import obj_bytes
from forge.hashing import geometry_sha256
from forge.record import build_record, load_record
from forge.registry import generate_asset, present_asset, render_asset_preview
from forge.render.settings import PreviewSettings
from forge.sword import generate_sword
from forge_test_support import REPO_ROOT

FROZEN_SOURCES = json.loads((REPO_ROOT / "tests" / "arsenal_frozen_sources.json").read_text())
NEW_IDENTIFIERS = ("dagger", "long_sword", "curved_sword", "great_sword", "forge.dagger", "forge.long_sword",
                   "forge.curved_sword", "forge.great_sword", "forge.blade-presentation", "forge.preview.fit")
ALL_ASSET_TYPES = ("short_sword",) + NEW_IDENTIFIERS[:4]
FROZEN_GROUPS = {   # step -> (modules, frozen test count)
    "Step 4": (("test_viewer_cli", "test_viewer_independence", "test_viewer_ingest", "test_viewer_render"), 94),
    "Step 3": (("test_engine_export", "test_engine_manifest", "test_engine_validator", "test_engine_integration"), 84),
    "Step 2.75": (("test_desktop_controller", "test_desktop_session", "test_desktop_guards", "test_desktop_window"), 49),
    "Step 2.5": (("test_registry_core", "test_registry_dispatch", "test_registry_family", "test_registry_guards"), 44),
    "Step 2": (("test_step2_cli", "test_step2_export", "test_step2_guards", "test_step2_presentation",
                "test_step2_record", "test_step2_render"), 77),
    "Step 1": (("test_prng", "test_seed", "test_determinism", "test_geometry", "test_obj_export", "test_cli"), 68),
}


def short_presented():
    a = generate_asset(REGISTRY, "short_sword", 1337, 1)
    return present_asset(REGISTRY, a, REGISTRY.presentation("forge.presentation", 1).versions)


class TestFrozenShortSword(unittest.TestCase):
    """61-65."""

    def test_61_short_sword_obj_unchanged(self):
        self.assertEqual(sha256(obj_bytes(generate_sword(1337, 1))), FROZEN_OBJ1_1337)
        self.assertEqual(geometry_sha256(generate_sword(1337, 1)), FROZEN_GEOMETRY_1337)
        p = short_presented()
        self.assertEqual(dict(REGISTRY.asset("short_sword").integrity)["obj_format1_sha256"](p.asset, p),
                         FROZEN_OBJ1_1337)

    def test_62_short_sword_record_unchanged(self):
        p = short_presented()
        image = render_asset_preview(REGISTRY, p, PreviewSettings(1, "three_quarter", 480, 960, 2))
        rec = build_record(p, image, forge_version="any")
        self.assertEqual(rec["integrity"]["record_content_sha256"], FROZEN_RECORD_CONTENT_1337)
        loaded = load_record(EXAMPLES / "asset_record_seed1337.json")
        self.assertEqual(len(loaded.verified), 7)
        self.assertEqual(loaded.record_content_sha256, FROZEN_RECORD_CONTENT_1337)

    def test_63_short_sword_preview_unchanged(self):
        p = short_presented()
        image = render_asset_preview(REGISTRY, p, PreviewSettings(1, "three_quarter", 480, 960, 2))
        self.assertEqual(image.pixels_sha256, FROZEN_PIXELS_1337)
        self.assertEqual(REGISTRY.asset("short_sword").descriptor.preview_id, "forge.preview")
        self.assertEqual((image.camera.target, image.camera.half_height), ((0.0, 0.295, 0.0), 0.42))

    def test_64_short_sword_glb_unchanged(self):
        pkg = build(1337)
        self.assertEqual(pkg.glb_sha256, FROZEN_GLB_1337)
        self.assertEqual(sha256((EXAMPLES / "short_sword_seed1337_v1.forgepkg" / "asset.glb").read_bytes()),
                         FROZEN_GLB_1337)

    def test_65_short_sword_manifest_unchanged(self):
        pkg = build(1337)
        self.assertEqual(pkg.manifest_sha256, FROZEN_MANIFEST_1337)
        m = pkg.manifest_data
        self.assertEqual({s["name"]: s["translation"] for s in m["sockets"]}["socket_tip"], FROZEN_SOCKET_TIP_1337)
        self.assertEqual((m["collision"]["vertices"], m["collision"]["triangles"]), (49, 94))
        self.assertEqual(sha256((EXAMPLES / "short_sword_seed1337_v1.forgepkg" / "manifest.json").read_bytes()),
                         FROZEN_MANIFEST_1337)


class TestFrozenSuites(unittest.TestCase):
    """66-71: each earlier step's suite passes, at its frozen count, in a fresh interpreter."""

    def run_group(self, step):
        modules, count = FROZEN_GROUPS[step]
        env = dict(os.environ, PYTHONPATH=os.pathsep.join([str(REPO_ROOT), str(REPO_ROOT / "tests")]))
        r = subprocess.run([sys.executable, "-m", "unittest", *modules], cwd=REPO_ROOT / "tests", env=env,
                           capture_output=True, text=True, timeout=1800)
        ran = re.search(r"^Ran (\d+) tests?", r.stderr, re.M)
        self.assertEqual(r.returncode, 0, r.stderr[-3000:])
        self.assertIsNotNone(ran)
        self.assertEqual(int(ran.group(1)), count, f"{step} should still have {count} tests")

    def test_66_step_4_suite_passes(self):
        self.run_group("Step 4")

    def test_67_step_3_suite_passes(self):
        self.run_group("Step 3")

    def test_68_step_2_75_suite_passes(self):
        self.run_group("Step 2.75")

    def test_69_step_2_5_suite_passes(self):
        self.run_group("Step 2.5")

    def test_70_step_2_suite_passes(self):
        self.run_group("Step 2")

    def test_71_step_1_suite_passes(self):
        self.run_group("Step 1")


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def docstring_ids(t):
    return {id(n.body[0].value) for n in ast.walk(t)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
            and n.body and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}


def code_strings(t):
    skip = docstring_ids(t)
    return [n.value for n in ast.walk(t) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in skip]


def imports(t):
    out = []
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
    return out


class TestArchitecture(unittest.TestCase):
    """Generic infrastructure needed no family branches: it is unchanged, and it names no family."""

    GENERIC = sorted(FROZEN_SOURCES["generic"]) + [f"forge_engine_viewer/{n}" for n in sorted(FROZEN_SOURCES["viewer"])]
    NEW_GENERIC = ["forge/render/fit.py"]          # generic code Step 5A added (geometry-bound framing)

    def test_generic_sources_are_byte_identical_to_step_4(self):
        self.assertGreaterEqual(len(self.GENERIC), 57)
        for must in ("forge/registry.py", "forge/record.py", "forge/cli.py", "forge/hashing.py",
                     "forge/engine/glb.py", "forge/engine/package.py", "forge/engine/validate.py",
                     "forge/render/raster.py", "forge/render/camera.py", "forge/presentation/normals.py",
                     "forge/export/obj_enriched.py", "forge/sword/v1.py", "forge/assets/short_sword.py",
                     "forge_desktop/session.py", "forge_desktop/controller.py", "forge_desktop/window.py",
                     "forge_engine_viewer/ingest.py"):
            self.assertIn(must, self.GENERIC)
        expected = {**FROZEN_SOURCES["generic"],
                    **{f"forge_engine_viewer/{k}": v for k, v in FROZEN_SOURCES["viewer"].items()}}
        changed = [rel for rel, digest in sorted(expected.items()) if sha256((REPO_ROOT / rel).read_bytes()) != digest]
        self.assertEqual(changed, [])
        # every product source that existed in Step 4 is either pinned above or is one of the two
        # disclosed edits; everything else in the product tree is new Step 5A code
        product = sorted(p.relative_to(REPO_ROOT).as_posix() for pkg in ("forge", "forge_desktop", "forge_engine_viewer")
                         for p in (REPO_ROOT / pkg).rglob("*.py"))
        new = sorted(set(product) - set(expected) - {"forge/catalog.py", "forge/__init__.py"})
        new = [p for p in new if not p.startswith(("forge/hafted/", "forge/assets/hafted.py"))]   # Step 5B's own files
        self.assertEqual(new, ["forge/assets/blades.py", "forge/blades/__init__.py", "forge/blades/build.py",
                               "forge/blades/curved_sword.py", "forge/blades/dagger.py", "forge/blades/draws.py",
                               "forge/blades/great_sword.py", "forge/blades/lineage.py", "forge/blades/long_sword.py",
                               "forge/blades/model.py", "forge/blades/presentation.py", "forge/blades/shapes.py",
                               "forge/render/fit.py"])

    def test_no_family_names_or_branches_in_generic_code(self):
        for rel in self.GENERIC + self.NEW_GENERIC:
            with self.subTest(file=rel):
                t = tree(REPO_ROOT / rel)
                strings = code_strings(t)
                own = {"forge/render/fit.py": "forge.preview.fit"}.get(rel)    # a renderer may name itself
                for ident in NEW_IDENTIFIERS:
                    if ident != own:
                        self.assertFalse(any(ident in s for s in strings), f"{rel} names {ident!r}")
                for mod in imports(t):
                    self.assertFalse(mod.startswith(("forge.blades", "forge.assets.blades")), f"{rel} imports {mod}")
                for node in ast.walk(t):
                    if isinstance(node, ast.Compare):
                        consts = [c.value for c in [node.left, *node.comparators] if isinstance(c, ast.Constant)]
                        for c in consts:
                            self.assertNotIn(c, ALL_ASSET_TYPES, f"{rel}:{node.lineno} branches on asset type {c!r}")
                    if isinstance(node, ast.Name) and node.id in ("BladeAsset", "SwordAsset") and rel in self.NEW_GENERIC:
                        self.fail(f"{rel} refers to a family asset class")

    def test_fit_preview_is_asset_agnostic(self):
        t = tree(REPO_ROOT / "forge" / "render" / "fit.py")
        for mod in imports(t):
            self.assertTrue(mod == "__future__" or mod in ("forge.errors", "forge.presentation.model", "forge.render",
                                                            "forge.render.camera", "forge.render.raster",
                                                            "forge.render.settings"), mod)

    def test_catalog_only_registers(self):
        """forge/catalog.py lists the families as data. It has no conditional on an asset type."""
        t = tree(REPO_ROOT / "forge" / "catalog.py")
        for node in ast.walk(t):
            if isinstance(node, (ast.If, ast.IfExp, ast.While)):
                for sub in ast.walk(node.test):
                    if isinstance(sub, ast.Constant):
                        self.assertNotIn(sub.value, ALL_ASSET_TYPES + NEW_IDENTIFIERS)
        strings = code_strings(t)
        for family in ALL_ASSET_TYPES[1:]:
            self.assertNotIn(family, strings, "catalog lists families via forge.assets.blades, not by name")
        self.assertEqual(strings.count("forge.blade-presentation"), 2, "obj:2 and glb:1 accept the blade presentation")
        self.assertIn("forge.assets", imports(t))

    def test_frozen_short_sword_code_untouched_and_not_reused(self):
        for rel in ("forge/sword/__init__.py", "forge/sword/asset.py", "forge/sword/params.py", "forge/sword/v1.py",
                    "forge/assets/short_sword.py", "forge/presentation/__init__.py"):
            self.assertEqual(sha256((REPO_ROOT / rel).read_bytes()), FROZEN_SOURCES["generic"][rel], rel)
        for path in sorted((REPO_ROOT / "forge" / "blades").glob("*.py")):
            for mod in imports(tree(path)):
                self.assertFalse(mod.startswith(("forge.sword", "forge.assets", "forge.catalog")),
                                 f"{path.name} imports {mod}")


if __name__ == "__main__":
    unittest.main()
