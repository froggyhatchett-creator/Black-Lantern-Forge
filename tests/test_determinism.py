"""Determinism contract: same (seed, generator_version) -> same sword, every time."""

import ast
import contextlib
import hashlib
import json
import os
import random
import subprocess
import sys
import unittest
from unittest import mock

from forge import (
    LATEST_SWORD_VERSION,
    SUPPORTED_SWORD_VERSIONS,
    EnvironmentNotSupportedError,
    UnsupportedGeneratorVersionError,
    export_obj,
    generate_sword,
    obj_bytes,
)
from forge.determinism import float_environment_problems
from forge.sword.params import GUARD_SHAPES, POINT_SHAPES, POMMEL_SHAPES
from forge_test_support import REPO_ROOT, VERSION, faces, float_bits, sha256

SEEDS = (0, 1, 2, 42, 1337, 987654321, (1 << 64) - 1)


def params_digest(asset) -> str:
    # json uses repr() for floats: shortest round-trip, so this pins exact float values.
    return sha256(json.dumps(asset.params.to_dict(), sort_keys=True).encode("ascii"))


def vertex_digest(asset) -> str:
    return sha256(repr(float_bits(asset)).encode("ascii"))


# Golden values recorded from generator v1 (and verified identical on CPython
# 3.10, 3.11, 3.12 and 3.13). They are a regression lock, not independent truth:
# if one of these fails, generator v1 output changed. Do not "update the hash" --
# restore v1 behavior, and put the new behavior in a new generator version.
GOLDEN_V1 = {
    0: ("4616124b1b3c738057a15a094e0123b4c2ea75feead946f93af64e3098f699dd",
        "cb48f28646d2aee232e8b8456f695e23a280b4e62aa4461ced7a05839f625d45",
        "35b07aceb4398f6a50a6e89df11a86143d37af057c43ed287329e0fdefaa253f"),
    1: ("de1548fc6b8b6b0793772b9e33e18e48fe511db909d72146a70c0c60cfd67142",
        "72915f873a809cb78b2fdbe30b1598e6353181323a2ed6cb4a1779310310abfb",
        "fe770b3e307da564026949092967c2726db169396eccb2cfa0e43b3e4dae9cad"),
    1337: ("7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a",
           "a75e48eba0859ca4e872fc184bb7093d34d17444c3d37f383954e6772b250d0a",
           "3980880f767922cf125332594c9ea3d38ad7c3311e35b08596ebe8e14021e445"),
    (1 << 64) - 1: ("763722760279e0230a75227c24f161b8bc3a28c310619621f8c2c9f828d1bfc7",
                    "cccc07b73a64872172863ffbd94fc2f1210b1ba07367907f2233abb63eacb35d",
                    "cacebf17643674bc10f72b0b445fa97ab84af21402aaf782d3e9c9396ba7946a"),
}


class TestSameSeedSameSword(unittest.TestCase):
    def test_1_same_seed_same_parameters(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                a, b = generate_sword(seed, VERSION), generate_sword(seed, VERSION)
                self.assertEqual(a.params, b.params)
                self.assertEqual(params_digest(a), params_digest(b))

    def test_2_same_seed_same_vertex_data_bit_for_bit(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(float_bits(generate_sword(seed, VERSION)),
                                 float_bits(generate_sword(seed, VERSION)))

    def test_3_same_seed_same_face_data(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(faces(generate_sword(seed, VERSION)), faces(generate_sword(seed, VERSION)))

    def test_4_same_seed_same_obj_bytes(self):
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(obj_bytes(generate_sword(seed, VERSION)),
                                 obj_bytes(generate_sword(seed, VERSION)))

    def test_generation_order_does_not_matter(self):
        forward = {s: obj_bytes(generate_sword(s, VERSION)) for s in SEEDS}
        backward = {s: obj_bytes(generate_sword(s, VERSION)) for s in reversed(SEEDS)}
        self.assertEqual(forward, backward)

    def test_golden_v1_outputs_are_unchanged(self):
        for seed, (obj_hash, param_hash, vert_hash) in GOLDEN_V1.items():
            with self.subTest(seed=seed):
                asset = generate_sword(seed, 1)
                self.assertEqual(sha256(obj_bytes(asset)), obj_hash, "OBJ bytes changed")
                self.assertEqual(params_digest(asset), param_hash, "parameters changed")
                self.assertEqual(vertex_digest(asset), vert_hash, "full-precision vertices changed")


class TestDifferentSeedsDiffer(unittest.TestCase):
    def test_5_different_seeds_produce_different_swords(self):
        seeds = range(64)
        params = {json.dumps(generate_sword(s, VERSION).params.to_dict(), sort_keys=True) for s in seeds}
        objs = {sha256(obj_bytes(generate_sword(s, VERSION))) for s in seeds}
        self.assertEqual(len(params), 64)
        self.assertEqual(len(objs), 64)

    def test_variation_is_meaningful_not_just_noise(self):
        assets = [generate_sword(s, VERSION) for s in range(200)]
        lengths = [a.params.blade.length for a in assets]
        self.assertGreater(max(lengths) - min(lengths), 0.12, "blade length barely varies")
        self.assertEqual({a.params.blade.point_shape for a in assets}, set(POINT_SHAPES))
        self.assertEqual({a.params.guard.shape for a in assets}, set(GUARD_SHAPES))
        self.assertEqual({a.params.pommel.shape for a in assets}, set(POMMEL_SHAPES))
        self.assertGreater(len({a.vertex_count for a in assets}), 3, "topology never varies")


class TestNoAmbientState(unittest.TestCase):
    def test_6a_does_not_consume_global_random_state(self):
        random.seed(20260101)
        before = random.getstate()
        for seed in SEEDS:
            export_obj(generate_sword(seed, VERSION))
        self.assertEqual(random.getstate(), before)

    def test_6b_output_independent_of_global_random_seed(self):
        random.seed(1)
        a = obj_bytes(generate_sword(42, VERSION))
        random.seed(999)
        random.random()
        b = obj_bytes(generate_sword(42, VERSION))
        self.assertEqual(a, b)

    def test_6c_never_calls_ambient_entropy_clock_or_pid(self):
        forbidden = [
            "random.random", "random.randint", "random.randrange", "random.uniform",
            "random.choice", "random.getrandbits", "random.seed", "random.shuffle",
            "os.urandom", "os.getpid", "time.time", "time.time_ns", "time.perf_counter",
            "time.monotonic", "uuid.uuid4", "secrets.randbits", "secrets.token_bytes",
        ]
        with contextlib.ExitStack() as stack:
            for target in forbidden:
                stack.enter_context(mock.patch(target, side_effect=AssertionError(f"{target} was called")))
            asset = generate_sword(1337, VERSION)
            data = obj_bytes(asset)
        self.assertEqual(sha256(data), GOLDEN_V1[1337][0])

    def test_6d_source_has_no_nondeterministic_dependencies(self):
        """Static AST guard over the package source (ignores comments/docstrings)."""
        banned_modules = {"random", "time", "datetime", "secrets", "uuid"}
        banned_attrs = {("os", "getpid"), ("os", "urandom")}
        # Generation code must stick to correctly rounded IEEE ops (+ - * / sqrt):
        # these libm functions are not guaranteed bit-identical across platforms.
        banned_math = {"sin", "cos", "tan", "asin", "acos", "atan", "atan2", "exp", "expm1",
                       "log", "log1p", "log2", "log10", "pow", "hypot", "fsum", "dist"}
        generation_files = {"prng.py", "primitives.py", "mesh.py", "v1.py", "params.py"}
        files = sorted((REPO_ROOT / "forge").rglob("*.py"))
        self.assertGreater(len(files), 5)
        for path in files:
            rel = path.relative_to(REPO_ROOT)
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn(alias.name.split(".")[0], banned_modules, f"{rel}: imports {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    self.assertNotIn((node.module or "").split(".")[0], banned_modules, f"{rel}: imports from {node.module}")
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    self.assertNotEqual(node.func.id, "hash", f"{rel}: builtin hash() is salted per process")
                elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    pair = (node.value.id, node.attr)
                    self.assertNotIn(pair, banned_attrs, f"{rel}: uses {pair[0]}.{pair[1]}")
                    if path.name in generation_files and node.value.id == "math":
                        self.assertNotIn(node.attr, banned_math, f"{rel}: uses math.{node.attr}")

    def test_cross_process_with_different_hash_seeds(self):
        """Fresh interpreters with different PYTHONHASHSEED values produce identical bytes."""
        script = (
            "import hashlib\n"
            "from forge import generate_sword, obj_bytes\n"
            "print(hashlib.sha256(b''.join(obj_bytes(generate_sword(s, 1)) for s in (0, 1, 1337))).hexdigest())\n"
        )
        expected = hashlib.sha256(b"".join(obj_bytes(generate_sword(s, 1)) for s in (0, 1, 1337))).hexdigest()
        for hash_seed in ("0", "1", "4242", "random"):
            with self.subTest(PYTHONHASHSEED=hash_seed):
                env = dict(os.environ, PYTHONHASHSEED=hash_seed, PYTHONPATH=str(REPO_ROOT))
                out = subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=env,
                                     capture_output=True, text=True, check=True)
                self.assertEqual(out.stdout.strip(), expected)

    def test_unsupported_float_environment_fails_loudly(self):
        self.assertEqual(float_environment_problems(), [])
        with mock.patch.object(sys, "float_repr_style", "legacy"):
            with self.assertRaises(EnvironmentNotSupportedError):
                generate_sword(1, VERSION)


class TestGeneratorVersion(unittest.TestCase):
    def test_7_generator_version_is_recorded(self):
        asset = generate_sword(1337, VERSION)
        self.assertEqual(asset.generator_version, VERSION)
        self.assertEqual(asset.to_dict()["generator_version"], VERSION)
        self.assertIn(f"# generator_version: {VERSION}\n", export_obj(asset))
        self.assertIn("# seed: 1337\n", export_obj(asset))

    def test_registry(self):
        self.assertEqual(SUPPORTED_SWORD_VERSIONS, (1,))
        self.assertEqual(LATEST_SWORD_VERSION, 1)

    def test_version_is_required(self):
        with self.assertRaises(TypeError):
            generate_sword(1)  # no implicit "latest" in the API

    def test_unsupported_versions_rejected(self):
        for bad in (0, 2, -1, 999, "1", 1.0, True, None):
            with self.subTest(version=bad):
                with self.assertRaises(UnsupportedGeneratorVersionError) as ctx:
                    generate_sword(1, bad)
                self.assertIsInstance(ctx.exception, ValueError)


if __name__ == "__main__":
    unittest.main()
