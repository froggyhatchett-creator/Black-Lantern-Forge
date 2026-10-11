"""Helpers for the Step 5A arsenal tests (not a test module).

Everything goes through the production registry (forge.catalog.REGISTRY) exactly as the CLI and the
desktop shell do. The mesh checks here are written independently of forge.mesh, so they are a
second opinion on the generator's own checks rather than a re-run of them.
"""

from __future__ import annotations

import functools
import hashlib
import json
import math

from forge.catalog import ASSET_ENTRIES, ENGINE_ADAPTERS, REGISTRY
from forge.engine.package import build_engine_package
from forge.registry import generate_asset, present_asset
from forge_test_support import REPO_ROOT

FAMILIES = ("dagger", "long_sword", "curved_sword", "great_sword")
GENERATOR_IDS = {f: f"forge.{f}" for f in FAMILIES}
BLADE_PRESENTATION = "forge.blade-presentation"
FIT_PREVIEW = "forge.preview.fit"
COMPONENTS = ("blade", "guard", "grip", "pommel")
LINEUP_SEEDS = (1, 2, 3, 7, 42, 1337)
EXAMPLES = REPO_ROOT / "examples"
ARSENAL_GOLDEN = json.loads((EXAMPLES / "arsenal_seed1337.golden.json").read_text(encoding="ascii"))["families"]

# frozen short_sword values (Steps 1-3); Step 5A must not move any of them
FROZEN_OBJ1_1337 = "7d9c4ad5d6ed11eab57517654ea1a2a97b8da36889032327495f890582ffd08a"
FROZEN_RECORD_CONTENT_1337 = "447fcfe4e6dad11650043c47c31b184e1fb3d493473a8bde74f744c15e4cf4f0"
FROZEN_PIXELS_1337 = "52d42d8f293134a06e2abfdd2056bb983415e34aa9624a57a5830358bb960605"
FROZEN_GLB_1337 = "b91900f7a1fc95f3ec6678e3dc8fa875b91bcce115c3231bd14dc5d0e2828bc3"
FROZEN_MANIFEST_1337 = "4a4d552e82a2ff2caf9c55420488005240ece4879db1d191ec725a2acffc7aaf"
FROZEN_GEOMETRY_1337 = "558b91f33db8aba45a74eb390708aae9b12d4532a6c6f9de24681d687d047439"
FROZEN_SOCKET_TIP_1337 = [0.0, 0.60488361120224, 0.0]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@functools.lru_cache(maxsize=None)
def asset(family: str, seed: int = 1337):
    return generate_asset(REGISTRY, family, seed, 1)


@functools.lru_cache(maxsize=None)
def presented(family: str, seed: int = 1337):
    return present_asset(REGISTRY, asset(family, seed), REGISTRY.presentation(BLADE_PRESENTATION, 1).versions)


def build_package(family: str, seed: int = 1337, fresh: bool = False):
    """Build the glb:1 package bytes in memory, as the glb:1 exporter does."""
    p = present_asset(REGISTRY, generate_asset(REGISTRY, family, seed, 1),
                      REGISTRY.presentation(BLADE_PRESENTATION, 1).versions) if fresh else presented(family, seed)
    entry = ASSET_ENTRIES[family]
    return build_engine_package(p.asset, p, entry.descriptor, ENGINE_ADAPTERS[family],
                                source_hashes=tuple((k, f(p.asset, p)) for k, f in entry.integrity),
                                exporter=("glb", 1), contract_version=1)


@functools.lru_cache(maxsize=None)
def package(family: str, seed: int = 1337):
    return build_package(family, seed)


# ------------------------------------------------------------------ independent mesh checks

def edge_problems(mesh) -> list[str]:
    """Closed, consistently wound, outward shell? Written independently of forge.mesh."""
    directed = {}
    problems = []
    for f, (a, b, c) in enumerate(mesh.triangles):
        for e in ((a, b), (b, c), (c, a)):
            directed[e] = directed.get(e, 0) + 1
    for (a, b), n in directed.items():
        if n != 1:
            problems.append(f"directed edge {(a, b)} used {n} times")
        if directed.get((b, a), 0) != 1:
            problems.append(f"edge {(a, b)} has no single opposite")
    vol6 = 0.0
    p = mesh.positions
    for a, b, c in mesh.triangles:
        (ax, ay, az), (bx, by, bz), (cx, cy, cz) = p[a], p[b], p[c]
        vol6 += ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx)
    if not vol6 > 0.0:
        problems.append(f"signed volume {vol6 / 6.0!r} is not positive")
    return problems


def area(a, b, c) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    x, y, z = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
    return 0.5 * math.sqrt(x * x + y * y + z * z)


def axial_extent(mesh, eps: float = 1e-12) -> tuple[float, float]:
    """Lowest and highest points where the vertical line x = 0, z = 0 meets the mesh surface."""
    ys = []
    p = mesh.positions
    for i, j, k in mesh.triangles:
        a, b, c = p[i], p[j], p[k]
        d = (b[0] - a[0]) * (c[2] - a[2]) - (c[0] - a[0]) * (b[2] - a[2])
        if d == 0.0:
            continue
        u = ((0.0 - a[0]) * (c[2] - a[2]) - (c[0] - a[0]) * (0.0 - a[2])) / d
        v = ((b[0] - a[0]) * (0.0 - a[2]) - (0.0 - a[0]) * (b[2] - a[2])) / d
        if u < -eps or v < -eps or u + v > 1.0 + eps:
            continue
        ys.append(a[1] + u * (b[1] - a[1]) + v * (c[1] - a[1]))
    if not ys:
        raise AssertionError(f"{mesh.name}: the central axis misses the mesh")
    return min(ys), max(ys)


def bounds(mesh):
    xs, ys, zs = zip(*mesh.positions)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))
