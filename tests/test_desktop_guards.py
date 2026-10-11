"""Step 2.75 source guards: the shell stays a shell; the core stays the core."""

import ast
import unittest

from forge_test_support import REPO_ROOT

SHELL = REPO_ROOT / "forge_desktop"
CORE = REPO_ROOT / "forge"
ASSET_SPECIFIC = {"short_sword", "forge.sword", "blade", "guard", "grip", "pommel", "procedural short sword"}
BYPASS_NAMES = {"generate_sword", "derive_presentation", "render_preview", "obj_bytes", "write_obj", "export_obj",
                "write_enriched_obj", "SwordAsset", "generate_short_sword_v1", "render_pixels"}
ENTROPY_MODULES = {"random", "secrets", "time", "datetime", "uuid"}


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
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            yield n.name


def code_strings(t):
    doc = {id(n.body[0].value) for n in ast.walk(t)
           if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
           and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n.value for n in ast.walk(t) if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in doc]


class TestShellRoutesThroughRegistry(unittest.TestCase):
    def files(self):
        files = sorted(SHELL.glob("*.py"))
        self.assertGreaterEqual(len(files), 6)
        return files

    def test_02_shell_never_reaches_around_the_registry(self):
        for path in self.files():
            t = tree(path)
            for mod in imports(t):
                self.assertFalse(mod.startswith(("forge.sword", "forge.assets", "forge.export", "forge.presentation",
                                                 "forge.render.raster", "forge.hashing")),
                                 f"{path.name} imports {mod}")
            for name in names(t):
                self.assertNotIn(name, BYPASS_NAMES, f"{path.name} names {name}")

    def test_generic_ui_has_no_asset_specific_literals(self):
        for path in self.files():
            hits = [s for s in code_strings(tree(path)) if s in ASSET_SPECIFIC]
            self.assertEqual(hits, [], f"{path.name} hard-codes {hits}")

    def test_no_implicit_latest(self):
        for path in self.files():
            for name in names(tree(path)):
                self.assertNotIn("latest", name.lower(), f"{path.name}: {name}")

    def test_entropy_is_confined_to_the_random_seed_button(self):
        for path in self.files():
            t = tree(path)
            used = {m.split(".")[0] for m in imports(t)} & ENTROPY_MODULES
            if path.name == "entropy.py":
                self.assertEqual(used, {"secrets"})
            else:
                self.assertEqual(used, set(), f"{path.name} imports {used}")
            self.assertNotIn("urandom", set(names(t)) if path.name != "entropy.py" else set())
        for path in (SHELL / "controller.py", SHELL / "session.py"):
            self.assertNotIn("forge_desktop.entropy", imports(tree(path)), f"{path.name} must take seeds injected")

    def test_controller_and_session_are_headless(self):
        for path in (SHELL / "controller.py", SHELL / "session.py", SHELL / "entropy.py"):
            self.assertFalse(any(m.split(".")[0] == "tkinter" for m in imports(tree(path))), path.name)
        top_level_tk = [path.name for path in self.files()
                        if any(isinstance(n, (ast.Import, ast.ImportFrom)) and "tkinter" in ast.dump(n)
                               for n in tree(path).body)]
        self.assertEqual(top_level_tk, ["window.py"])   # app.py imports tkinter lazily, inside main()


class TestCoreStaysCore(unittest.TestCase):
    def test_core_does_not_depend_on_the_shell(self):
        for path in sorted(CORE.rglob("*.py")):
            t = tree(path)
            shell_imports = [n for n in ast.walk(t) if isinstance(n, (ast.Import, ast.ImportFrom))
                             and "forge_desktop" in ast.dump(n)]
            if path.name == "gui.py" and path.parent == CORE:
                # the launcher may import the shell, but only when run as a script
                for n in shell_imports:
                    self.assertNotIn(n, t.body, "forge/gui.py must import the shell only under __main__")
                continue
            self.assertEqual(shell_imports, [], f"{path.relative_to(REPO_ROOT)} imports the desktop shell")

    def test_importing_the_launcher_does_not_launch(self):
        import forge.gui  # noqa: F401  (no window, no Tk, no side effects)
        import sys
        self.assertNotIn("forge_desktop.window", sys.modules)


if __name__ == "__main__":
    unittest.main()
