"""Triangle mesh container with strict, fail-loud validation.

A Mesh can only exist in a valid state: __post_init__ validates everything and
raises GeometryError otherwise. Nothing is repaired.

Conventions:
  * positions: tuple of (x, y, z) float triples, meters.
  * triangles: tuple of (i, j, k) zero-based vertex indices.
  * Front faces are counter-clockwise when viewed from outside (outward normals).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Callable

from forge.errors import GeometryError

Vec3 = tuple[float, float, float]
Tri = tuple[int, int, int]

# Triangles with area at or below this are rejected as degenerate (1 square micrometer).
MIN_TRIANGLE_AREA_M2 = 1e-12

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]*")


@dataclass(frozen=True)
class Mesh:
    name: str
    positions: tuple[Vec3, ...]
    triangles: tuple[Tri, ...]

    def __post_init__(self) -> None:
        _validate(self)

    @property
    def vertex_count(self) -> int:
        return len(self.positions)

    @property
    def triangle_count(self) -> int:
        return len(self.triangles)

    def bounds(self) -> tuple[Vec3, Vec3]:
        """Axis-aligned bounding box: ((min_x, min_y, min_z), (max_x, max_y, max_z))."""
        xs = [p[0] for p in self.positions]
        ys = [p[1] for p in self.positions]
        zs = [p[2] for p in self.positions]
        return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs))

    def signed_volume(self) -> float:
        """Divergence-theorem volume. Positive for a closed, outward-wound shell.

        Uses a plain sequential loop (not sum()) so the float result does not
        depend on Python's summation algorithm, which changed in 3.12.
        """
        total = 0.0
        p = self.positions
        for a, b, c in self.triangles:
            ax, ay, az = p[a]
            bx, by, bz = p[b]
            cx, cy, cz = p[c]
            total += (ax * (by * cz - bz * cy) - ay * (bx * cz - bz * cx) + az * (bx * cy - by * cx))
        return total / 6.0

    def mapped(self, fn: Callable[[Vec3], Vec3], name: str | None = None) -> "Mesh":
        """New mesh with fn applied to every position. fn must be a proper rigid
        transform (rotation/translation) or winding will no longer be outward."""
        return Mesh(
            name=self.name if name is None else name,
            positions=tuple(fn(p) for p in self.positions),
            triangles=self.triangles,
        )

    def translated(self, dx: float = 0.0, dy: float = 0.0, dz: float = 0.0) -> "Mesh":
        return self.mapped(lambda p: (p[0] + dx, p[1] + dy, p[2] + dz))


def _validate(mesh: Mesh) -> None:
    if not isinstance(mesh.name, str) or _NAME.fullmatch(mesh.name) is None:
        raise GeometryError(f"mesh name must match {_NAME.pattern!r}; got {mesh.name!r}")
    where = f"mesh {mesh.name!r}"

    if not isinstance(mesh.positions, tuple) or not isinstance(mesh.triangles, tuple):
        raise GeometryError(f"{where}: positions and triangles must be tuples")
    if len(mesh.positions) == 0:
        raise GeometryError(f"{where}: has no vertices")
    if len(mesh.triangles) == 0:
        raise GeometryError(f"{where}: has no faces")

    for i, p in enumerate(mesh.positions):
        if not isinstance(p, tuple) or len(p) != 3:
            raise GeometryError(f"{where}: vertex {i} is not a 3-tuple: {p!r}")
        for c in p:
            if type(c) is not float:
                raise GeometryError(f"{where}: vertex {i} has non-float coordinate {c!r}")
            if not math.isfinite(c):
                raise GeometryError(f"{where}: vertex {i} has non-finite coordinate {p!r}")

    n = len(mesh.positions)
    used = bytearray(n)
    for f, tri in enumerate(mesh.triangles):
        if not isinstance(tri, tuple) or len(tri) != 3:
            raise GeometryError(f"{where}: face {f} is not a 3-tuple: {tri!r}")
        for idx in tri:
            if type(idx) is not int:
                raise GeometryError(f"{where}: face {f} has non-int index {idx!r}")
            if not 0 <= idx < n:
                raise GeometryError(f"{where}: face {f} index {idx} out of range [0, {n})")
        a, b, c = tri
        if a == b or b == c or a == c:
            raise GeometryError(f"{where}: face {f} repeats a vertex: {tri!r}")
        area = triangle_area(mesh.positions[a], mesh.positions[b], mesh.positions[c])
        if not area > MIN_TRIANGLE_AREA_M2:
            raise GeometryError(f"{where}: face {f} is degenerate (area {area!r} m^2)")
        used[a] = used[b] = used[c] = 1

    if not all(used):
        raise GeometryError(f"{where}: vertex {used.index(0)} is not referenced by any face")


def triangle_area(a: Vec3, b: Vec3, c: Vec3) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    cx = uy * vz - uz * vy
    cy = uz * vx - ux * vz
    cz = ux * vy - uy * vx
    return 0.5 * math.sqrt(cx * cx + cy * cy + cz * cz)


def check_closed_oriented(mesh: Mesh) -> None:
    """Raise GeometryError unless the mesh is a closed, consistently oriented,
    outward-facing shell:

      * every directed edge (a->b) occurs exactly once, and
      * its reverse (b->a) occurs exactly once (each edge has exactly 2 faces), and
      * signed volume is positive (normals point outward).
    """
    directed: dict[tuple[int, int], int] = {}
    for f, (a, b, c) in enumerate(mesh.triangles):
        for e in ((a, b), (b, c), (c, a)):
            if e in directed:
                raise GeometryError(
                    f"mesh {mesh.name!r}: directed edge {e} used by faces {directed[e]} and {f} "
                    "(inconsistent winding or non-manifold edge)"
                )
            directed[e] = f
    for (a, b), f in directed.items():
        if (b, a) not in directed:
            raise GeometryError(f"mesh {mesh.name!r}: edge {(a, b)} of face {f} has no opposite face (open shell)")
    volume = mesh.signed_volume()
    if not volume > 0.0:
        raise GeometryError(f"mesh {mesh.name!r}: signed volume {volume!r} is not positive (inward winding?)")
