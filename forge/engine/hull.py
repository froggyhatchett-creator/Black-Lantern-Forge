"""Exact 3D convex hull, used for the contract's collision_hull.

Every input coordinate is a binary float (here, float32 values held in Python
floats). Each one is converted exactly to an integer over a shared power-of-two
denominator, and every orientation test is an exact integer determinant. So
the result has no epsilons and no rounding, and it is identical on every
platform.

Algorithm: incremental hull over the distinct points, in sorted order.
  * The seed is a tetrahedron made of the first non-degenerate points.
  * A point that is strictly outside one or more faces replaces those faces
    with a fan from the horizon edges to the point.
  * Points on or inside the current hull are skipped.
A point added early can end up lying flat inside a later face or edge. So
the hull is rebuilt once from its extreme vertices only: those whose incident
triangles span at least three distinct planes. The result's vertices are then
exactly the extreme points of the input. A flat facet with more than three
corners is still split into several coplanar triangles.

The result is checked before it is returned, and GeometryError is raised
otherwise:
  * the mesh is closed and 2-manifold (every directed edge appears once, and
    its reverse appears once)
  * the Euler characteristic is 2
  * no face is degenerate
  * every input point is on or inside every face plane, so the hull is convex,
    outward-facing and contains everything

The output is canonical:
  * vertices are sorted by value
  * each triangle is rotated so its smallest index comes first, keeping its winding
  * the triangles are sorted
-0.0 is stored as 0.0.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import gcd

from forge.errors import GeometryError

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class Hull:
    positions: tuple[Vec3, ...]
    triangles: tuple[tuple[int, int, int], ...]


def _orient(a, b, c, d) -> int:
    """Exact sign source: > 0 if d lies on the side (b - a) x (c - a) points to."""
    abx, aby, abz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    acx, acy, acz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    adx, ady, adz = d[0] - a[0], d[1] - a[1], d[2] - a[2]
    return (abx * (acy * adz - acz * ady)
            - aby * (acx * adz - acz * adx)
            + abz * (acx * ady - acy * adx))


def _cross_is_zero(a, b, c) -> bool:
    abx, aby, abz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    acx, acy, acz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return (aby * acz - abz * acy == 0 and abz * acx - abx * acz == 0 and abx * acy - aby * acx == 0)


def exact_integer_points(points) -> list[tuple[int, int, int]]:
    """Scale binary floats to integers with one shared power-of-two denominator (exact)."""
    ratios = [tuple(float(v).as_integer_ratio() for v in p) for p in points]
    denominator = 1
    for r in ratios:
        for _, d in r:
            if d > denominator:
                denominator = d
    return [tuple(n * (denominator // d) for n, d in r) for r in ratios]


def convex_hull(points) -> Hull:
    distinct = sorted({(p[0] + 0.0, p[1] + 0.0, p[2] + 0.0) for p in points})
    n = len(distinct)
    if n < 4:
        raise GeometryError(f"convex hull needs at least 4 distinct points; got {n}")
    P = exact_integer_points(distinct)

    faces = _incremental(P, range(n))
    extreme = _extreme_vertices(P, faces)
    if len(extreme) < len({i for f in faces for i in f}):
        faces = _incremental(P, extreme)
    _verify(P, faces)

    used = sorted({i for f in faces for i in f})
    remap = {old: new for new, old in enumerate(used)}
    canonical = []
    for f in faces:
        a, b, c = (remap[i] for i in f)
        if b < a and b < c:
            a, b, c = b, c, a
        elif c < a and c < b:
            a, b, c = c, a, b
        canonical.append((a, b, c))
    canonical.sort()
    return Hull(positions=tuple(distinct[i] for i in used), triangles=tuple(canonical))


def _incremental(P, candidates) -> list[tuple[int, int, int]]:
    order = list(candidates)
    i0, i1 = order[0], order[1]
    i2 = next((i for i in order[2:] if not _cross_is_zero(P[i0], P[i1], P[i])), None)
    if i2 is None:
        raise GeometryError("convex hull input is collinear")
    i3 = next((i for i in order[2:] if _orient(P[i0], P[i1], P[i2], P[i]) != 0), None)
    if i3 is None:
        raise GeometryError("convex hull input is coplanar")
    if _orient(P[i0], P[i1], P[i2], P[i3]) > 0:
        i1, i2 = i2, i1
    faces = [(i0, i1, i2), (i0, i3, i1), (i1, i3, i2), (i2, i3, i0)]
    seeded = {i0, i1, i2, i3}
    for k in order:
        if k in seeded:
            continue
        p = P[k]
        visible = [f for f in faces if _orient(P[f[0]], P[f[1]], P[f[2]], p) > 0]
        if not visible:
            continue
        visible_edges = set()
        for a, b, c in visible:
            visible_edges.update(((a, b), (b, c), (c, a)))
        horizon = [(a, b) for f in visible for a, b in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0]))
                   if (b, a) not in visible_edges]
        gone = set(visible)
        faces = [f for f in faces if f not in gone] + [(a, b, k) for a, b in horizon]
    return faces


def _extreme_vertices(P, faces) -> list[int]:
    """Hull vertices whose incident triangles lie in >= 3 distinct planes (true corners), sorted."""
    planes: dict[int, set] = {}
    for f in faces:
        a, b, c = P[f[0]], P[f[1]], P[f[2]]
        ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
        vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
        n = (uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx)
        g = gcd(gcd(abs(n[0]), abs(n[1])), abs(n[2]))
        if g == 0:
            raise GeometryError(f"convex hull: degenerate face {f}")
        key = (n[0] // g, n[1] // g, n[2] // g)
        for v in f:
            planes.setdefault(v, set()).add(key)
    return sorted(v for v, s in planes.items() if len(s) >= 3)


def _verify(P, faces) -> None:
    edges = {}
    for f in faces:
        for e in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            if e in edges:
                raise GeometryError(f"convex hull: directed edge {e} used twice")
            edges[e] = f
    for a, b in edges:
        if (b, a) not in edges:
            raise GeometryError(f"convex hull: edge {(a, b)} has no opposite (open shell)")
    vertices = {i for f in faces for i in f}
    if len(vertices) - len(edges) // 2 + len(faces) != 2:
        raise GeometryError("convex hull: Euler characteristic is not 2")
    for f in faces:
        a, b, c = P[f[0]], P[f[1]], P[f[2]]
        if _cross_is_zero(a, b, c):
            raise GeometryError(f"convex hull: degenerate face {f}")
        for q in P:
            if _orient(a, b, c, q) > 0:
                raise GeometryError(f"convex hull: face {f} has a point outside it")
