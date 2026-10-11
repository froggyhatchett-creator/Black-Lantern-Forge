"""Step 2.5 source guards: generic code stays generic; no implicit latest; no plugin loading."""

import ast
import unittest

from forge_test_support import REPO_ROOT

PKG = REPO_ROOT / "forge"
GENERIC = [PKG / "record.py", PKG / "registry.py", PKG / "cli.py", PKG / "conventions.py"]
REGISTRATION = [PKG / "catalog.py", PKG / "assets" / "short_sword.py", PKG / "assets" / "__init__.py"]
SWORD_LITERALS = {"short_sword", "forge.sword", "blade", "guard", "grip", "pommel",
                  "forge.presentation", "procedural short sword"}


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def string_constants(t):
    docstrings = {id(n.body[0].value) for n in ast.walk(t)
                  if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
                  and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n for n in ast.walk(t) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings]


def imported_modules(t):
    out = []
    for n in ast.walk(t):
        if isinstance(n, ast.Import):
            out += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom):
            out.append(n.module or "")
    return out


def identifiers(t):
    for n in ast.walk(t):
        if isinstance(n, ast.Name):
            yield n.id
        elif isinstance(n, ast.Attribute):
            yield n.attr
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            yield n.name
        elif isinstance(n, ast.alias):
            yield n.asname or n.name
        elif isinstance(n, ast.keyword) and n.arg:
            yield n.arg


class TestGenericCodeIsGeneric(unittest.TestCase):
    def test_18_record_loader_and_registry_have_no_asset_specific_knowledge(self):
        for path in (PKG / "record.py", PKG / "registry.py"):
            t = tree(path)
            hits = [c.value for c in string_constants(t) if c.value in SWORD_LITERALS]
            self.assertEqual(hits, [], f"{path.name} hard-codes {hits}")
            for mod in imported_modules(t):
                self.assertFalse(mod.startswith(("forge.sword", "forge.assets", "forge.export")),
                                 f"{path.name} imports {mod}")
            for name in identifiers(t):
                self.assertNotIn(name, {"SwordAsset", "generate_sword", "derive_presentation", "COMPONENT_ORDER",
                                        "obj_bytes", "render_preview", "write_obj", "write_enriched_obj"},
                                 f"{path.name} reaches around the registry via {name}")

    def test_cli_routes_through_registry(self):
        t = tree(PKG / "cli.py")
        sword_strings = [c for c in string_constants(t) if c.value == "short_sword"]
        self.assertEqual(len(sword_strings), 1, "the pinned `sword` alias should name short_sword exactly once")
        for n in ast.walk(t):
            if isinstance(n, ast.Compare):
                for c in ast.walk(n):
                    if isinstance(c, ast.Constant) and c.value in SWORD_LITERALS:
                        self.fail(f"cli.py branches on {c.value!r}")
        for mod in imported_modules(t):
            self.assertFalse(mod.startswith(("forge.sword", "forge.assets", "forge.export", "forge.presentation")),
                             f"cli.py imports {mod} directly")
        for name in identifiers(t):
            self.assertNotIn(name, {"generate_sword", "derive_presentation", "obj_bytes", "render_preview",
                                    "write_enriched_obj", "SwordAsset"}, f"cli.py bypasses the registry via {name}")

    def test_no_implicit_latest_in_registry_layer(self):
        for path in GENERIC + REGISTRATION:
            for name in identifiers(tree(path)):
                self.assertNotIn("latest", name.lower(), f"{path.name}: identifier {name}")


class TestNoPluginMachinery(unittest.TestCase):
    BANNED_MODULES = ("importlib", "pkgutil", "imp", "runpy", "zipimport", "site", "socket", "urllib", "http",
                      "ftplib", "requests", "xmlrpc", "multiprocessing", "subprocess", "ctypes")
    BANNED_CALLS = {"__import__", "exec", "eval", "compile", "setattr", "delattr", "globals"}

    def test_no_dynamic_loading_network_or_runtime_mutation_anywhere(self):
        files = sorted(PKG.rglob("*.py"))
        self.assertGreater(len(files), 20)
        for path in files:
            t = tree(path)
            rel = path.relative_to(REPO_ROOT)
            for mod in imported_modules(t):
                self.assertNotIn(mod.split(".")[0], self.BANNED_MODULES, f"{rel} imports {mod}")
            for n in ast.walk(t):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                    self.assertNotIn(n.func.id, self.BANNED_CALLS, f"{rel} calls {n.func.id}()")
                if isinstance(n, ast.Attribute):
                    self.assertNotIn(n.attr, {"import_module", "entry_points", "load_module", "exec_module"},
                                     f"{rel} uses .{n.attr}")

    def test_registration_layer_never_assigns_attributes(self):
        """Registration wraps frozen code; it must not patch module or object attributes."""
        for path in GENERIC + REGISTRATION:
            for n in ast.walk(tree(path)):
                targets = []
                if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                    targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                elif isinstance(n, ast.Delete):
                    targets = n.targets
                for target in targets:
                    self.assertNotIsInstance(target, ast.Attribute, f"{path.name}: attribute assignment")

    def test_frozen_modules_untouched_after_dispatch(self):
        import forge.sword as sword_pkg
        from forge.catalog import REGISTRY
        from forge.presentation import derive_presentation
        from forge.registry import generate_asset, present_asset
        from forge.sword import v1
        before = (dict(sword_pkg._GENERATORS), dict(v1.STREAM_LABELS), v1.GENERATOR_VERSION, derive_presentation)
        a = generate_asset(REGISTRY, "short_sword", 7, 1)
        present_asset(REGISTRY, a, REGISTRY.presentation("forge.presentation", 1).versions)
        from forge.presentation import derive_presentation as again
        self.assertEqual(before, (dict(sword_pkg._GENERATORS), dict(v1.STREAM_LABELS), v1.GENERATOR_VERSION, again))
        self.assertEqual(sword_pkg._GENERATORS, {1: v1.generate})


if __name__ == "__main__":
    unittest.main()
