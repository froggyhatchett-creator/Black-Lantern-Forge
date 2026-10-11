"""Helpers for the Step 5B hafted-family tests (not a test module).

Everything goes through the production registry, as the CLI and the desktop shell do. The
point-in-solid test here is written independently of Forge. It counts signed ray crossings
(a winding number), so it also works for a part made of several overlapping closed shells.
"""

from __future__ import annotations

import functools
import json

from arsenal_support import area, bounds, edge_problems, sha256  # noqa: F401  (re-exported for the 5B tests)
from forge.catalog import ASSET_ENTRIES, ENGINE_ADAPTERS, REGISTRY
from forge.engine.package import build_engine_package
from forge.registry import generate_asset, present_asset
from forge_test_support import REPO_ROOT

FAMILIES = ("one_hand_axe", "two_hand_axe", "mace", "war_hammer")
GENERATOR_IDS = {f: f"forge.{f}" for f in FAMILIES}
HAFTED_PRESENTATION = "forge.hafted-presentation"
FIT_PREVIEW = "forge.preview.fit"
COMPONENTS = {
    "one_hand_axe": ("haft", "grip", "head", "bit"),
    "two_hand_axe": ("haft", "grip", "head", "bit"),
    "mace": ("haft", "grip", "collar", "head", "flanges", "butt_cap"),
    "war_hammer": ("haft", "grip", "head", "face", "rear", "butt_cap"),
}
STRIKE_PART = {"one_hand_axe": "bit", "two_hand_axe": "bit", "mace": "flanges", "war_hammer": "face"}
LINEUP_SEEDS = (1, 2, 3, 7, 42, 1337)
SWEEP = LINEUP_SEEDS + tuple(range(300, 340))
EXAMPLES = REPO_ROOT / "examples"
HAFTED_GOLDEN = json.loads((EXAMPLES / "hafted_seed1337.golden.json").read_text(encoding="ascii"))["families"]
BLADE_GOLDEN = json.loads((EXAMPLES / "arsenal_seed1337.golden.json").read_text(encoding="ascii"))["families"]
NEW_IDENTIFIERS = ("one_hand_axe", "two_hand_axe", "mace", "war_hammer", "forge.one_hand_axe", "forge.two_hand_axe",
                   "forge.mace", "forge.war_hammer", "forge.hafted-presentation")


@functools.lru_cache(maxsize=None)
def asset(family: str, seed: int = 1337):
    return generate_asset(REGISTRY, family, seed, 1)


@functools.lru_cache(maxsize=None)
def presented(family: str, seed: int = 1337):
    return present_asset(REGISTRY, asset(family, seed), REGISTRY.presentation(HAFTED_PRESENTATION, 1).versions)


def build_package(family: str, seed: int = 1337, fresh: bool = False):
    p = present_asset(REGISTRY, generate_asset(REGISTRY, family, seed, 1),
                      REGISTRY.presentation(HAFTED_PRESENTATION, 1).versions) if fresh else presented(family, seed)
    entry = ASSET_ENTRIES[family]
    return build_engine_package(p.asset, p, entry.descriptor, ENGINE_ADAPTERS[family],
                                source_hashes=tuple((k, f(p.asset, p)) for k, f in entry.integrity),
                                exporter=("glb", 1), contract_version=1)


@functools.lru_cache(maxsize=None)
def package(family: str, seed: int = 1337):
    return build_package(family, seed)


# ------------------------------------------------------------------ independent point-in-solid

_RAY = (1.0, 0.3183098861837907, 0.1415926535897932)     # a fixed, generic direction (no axis-aligned hits)


def winding(mesh, p) -> int:
    """Signed count of the triangles a ray from p crosses (Moller-Trumbore). Nonzero = inside."""
    dx, dy, dz = _RAY
    total = 0
    pos = mesh.positions
    for i, j, k in mesh.triangles:
        a, b, c = pos[i], pos[j], pos[k]
        e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
        e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
        h = (dy * e2[2] - dz * e2[1], dz * e2[0] - dx * e2[2], dx * e2[1] - dy * e2[0])
        det = e1[0] * h[0] + e1[1] * h[1] + e1[2] * h[2]
        if det == 0.0:
            continue
        inv = 1.0 / det
        s = (p[0] - a[0], p[1] - a[1], p[2] - a[2])
        u = (s[0] * h[0] + s[1] * h[1] + s[2] * h[2]) * inv
        if u < 0.0 or u > 1.0:
            continue
        q = (s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0])
        v = (dx * q[0] + dy * q[1] + dz * q[2]) * inv
        if v < 0.0 or u + v > 1.0:
            continue
        t = (e2[0] * q[0] + e2[1] * q[1] + e2[2] * q[2]) * inv
        if t > 0.0:
            total += 1 if det > 0.0 else -1
    return total


def inside(mesh, p) -> bool:
    return winding(mesh, p) != 0


def joint_points(a, joint):
    """The inner part's vertices that the joint selects."""
    return [q for q in a.component(joint.inner).positions if joint.selects(q)]


def seated(a, joint) -> tuple[int, int]:
    """(selected inner vertices, how many of them lie inside the outer part)."""
    pts = joint_points(a, joint)
    outer = a.component(joint.outer)
    return len(pts), sum(1 for q in pts if inside(outer, q))


def face_normal(p, tri):
    a, b, c = (p[i] for i in tri)
    u = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    v = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])


def object_rows_cols(image, tolerance: int = 6):
    """Rows and columns that hold anything other than the (vertical-gradient) background."""
    w, h, px = image.width, image.height, image.pixels
    rows, cols = set(), set()
    for y in range(h):
        bg = px[(y * w) * 3:(y * w) * 3 + 3]
        for x in range(w):
            i = (y * w + x) * 3
            if max(abs(px[i + k] - bg[k]) for k in range(3)) > tolerance:
                rows.add(y)
                cols.add(x)
    return rows, cols
