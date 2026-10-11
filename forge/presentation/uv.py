"""UV coordinates, derived purely from frozen mesh geometry.

uv_version 1
------------
Each component has its own UV space (one material per component, so UV islands
of different components never share a texture). Every coordinate is in [0, 1].
UVs are face-varying: every triangle corner gets a UV, so seams are free.

Let B = the component's axis-aligned bounds and N(a, x) = (x - min_a) / (max_a - min_a).
Each triangle's dominant axis is the largest |component| of its raw face normal,
with ties broken Y, then Z, then X.

  box (blade, guard)
      dominant Z  ->  (N(x), N(y))      front/back flats; mirrored back face
      dominant X  ->  (N(z), N(y))
      dominant Y  ->  (N(x), N(z))      caps / end faces

  cylindrical (grip, pommel)
      dominant Y, or any corner on the Y axis  ->  (N(x), N(z))   planar caps
      otherwise  ->  u = diamond_angle(x, z) / 4,  v = N(y)
      diamond_angle is a trig-free, monotonic stand-in for the polar angle
      ([0, 4) going counter-clockwise from +X). If a triangle's corners span
      more than 0.5 in u it crosses the seam at +X, and corners below 0.5 get
      +1. Every ring has a vertex exactly on +X (z == 0.0), which then lands
      on u == 1.0, so u stays inside [0, 1].

No packing, no texel-density balancing: these UVs exist for stable procedural
texturing, preview, and later export, not artist-quality layouts.
Only + - * / are used.
"""

from __future__ import annotations

from forge.errors import PresentationError
from forge.mesh import Mesh, Tri
from forge.versioning import require_version
from forge.presentation.normals import raw_face_normals

Vec2 = tuple[float, float]

UV_V1_MAPPING = {"blade": "box", "guard": "box", "grip": "cylindrical", "pommel": "cylindrical"}
SUPPORTED_UV_VERSIONS = (1,)


def diamond_angle(x: float, z: float) -> float:
    """Pseudo-angle of (x, z) in [0, 4): 0 at +X, 1 at +Z, 2 at -X, 3 at -Z."""
    if x == 0.0 and z == 0.0:
        raise PresentationError("diamond_angle is undefined at the origin")
    if z >= 0.0:
        return z / (x + z) if x >= 0.0 else 1.0 + (0.0 - x) / (z - x)
    return 2.0 + (0.0 - z) / ((0.0 - x) - z) if x < 0.0 else 3.0 + x / (x - z)


def _dominant_axis(n) -> str:
    ax, ay, az = abs(n[0]), abs(n[1]), abs(n[2])
    if ay >= ax and ay >= az:
        return "y"
    if az >= ax:
        return "z"
    return "x"


def compute_uvs_v1(mesh: Mesh) -> tuple[tuple[Vec2, ...], tuple[Tri, ...]]:
    if mesh.name not in UV_V1_MAPPING:
        raise PresentationError(f"uv v1 has no mapping for component {mesh.name!r}")
    mapping = UV_V1_MAPPING[mesh.name]
    (x0, y0, z0), (x1, y1, z1) = mesh.bounds()
    dx, dy, dz = x1 - x0, y1 - y0, z1 - z0
    if not (dx > 0.0 and dy > 0.0 and dz > 0.0):
        raise PresentationError(f"component {mesh.name!r} has a zero-extent axis; cannot map UVs")

    def nx(x): return (x - x0) / dx
    def ny(y): return (y - y0) / dy
    def nz(z): return (z - z0) / dz

    p = mesh.positions
    corner: list[tuple[Vec2, Vec2, Vec2]] = []
    for tri, n in zip(mesh.triangles, raw_face_normals(mesh)):
        pts = [p[i] for i in tri]
        axis = _dominant_axis(n)
        if mapping == "box":
            if axis == "z":
                uvs = [(nx(q[0]), ny(q[1])) for q in pts]
            elif axis == "x":
                uvs = [(nz(q[2]), ny(q[1])) for q in pts]
            else:
                uvs = [(nx(q[0]), nz(q[2])) for q in pts]
        else:
            on_axis = any(q[0] == 0.0 and q[2] == 0.0 for q in pts)
            if axis == "y" or on_axis:
                uvs = [(nx(q[0]), nz(q[2])) for q in pts]
            else:
                us = [diamond_angle(q[0], q[2]) / 4.0 for q in pts]
                if max(us) - min(us) > 0.5:
                    us = [u + 1.0 if u < 0.5 else u for u in us]
                uvs = [(u, ny(q[1])) for u, q in zip(us, pts)]
        corner.append((uvs[0], uvs[1], uvs[2]))

    index: dict[Vec2, int] = {}
    values: list[Vec2] = []
    triples: list[Tri] = []
    for tri in corner:
        ids = []
        for uv in tri:
            if not (0.0 <= uv[0] <= 1.0 and 0.0 <= uv[1] <= 1.0):
                raise PresentationError(f"component {mesh.name!r}: UV {uv!r} outside [0, 1]")
            i = index.get(uv)
            if i is None:
                i = index[uv] = len(values)
                values.append(uv)
            ids.append(i)
        triples.append((ids[0], ids[1], ids[2]))
    return tuple(values), tuple(triples)


def compute_uvs(mesh: Mesh, uv_version: int) -> tuple[tuple[Vec2, ...], tuple[Tri, ...]]:
    require_version("uv_version", uv_version, SUPPORTED_UV_VERSIONS)
    return compute_uvs_v1(mesh)
