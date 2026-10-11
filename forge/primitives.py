"""Geometry primitives built from IEEE-754 basic operations only.

Determinism note: everything here uses +, -, *, / and sqrt. IEEE 754 requires
all five to be correctly rounded, so results are bit-identical on any platform
with binary64 floats. Transcendental functions (sin, cos, atan...) are NOT
used, because libm implementations may differ in the last bit across
platforms. Circle profiles are built from exact sqrt identities instead.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from forge.errors import GeometryError
from forge.mesh import Mesh, Vec3

Profile = tuple[tuple[float, float], ...]


def _neg(v: float) -> float:
    # 0.0 - v avoids producing -0.0 when v == 0.0 (keeps data tidy; -v would not).
    return 0.0 - v


_C45 = math.sqrt(0.5)                          # cos 45 = sin 45
_C30 = math.sqrt(3.0) * 0.5                    # cos 30 = sin 60
_C22 = math.sqrt(2.0 + math.sqrt(2.0)) * 0.5   # cos 22.5 = sin 67.5
_S22 = math.sqrt(2.0 - math.sqrt(2.0)) * 0.5   # sin 22.5 = cos 67.5

# First-quadrant (cos, sin) pairs, angle 0..90 inclusive, for each supported n.
_QUADRANT: dict[int, tuple[tuple[float, float], ...]] = {
    4: ((1.0, 0.0), (0.0, 1.0)),
    8: ((1.0, 0.0), (_C45, _C45), (0.0, 1.0)),
    12: ((1.0, 0.0), (_C30, 0.5), (0.5, _C30), (0.0, 1.0)),
    16: ((1.0, 0.0), (_C22, _S22), (_C45, _C45), (_S22, _C22), (0.0, 1.0)),
}

# Exposed for components that need latitude angles (orb pommel).
SIN_COS_22_5 = (_S22, _C22)
SIN_COS_45 = (_C45, _C45)


def unit_circle(n: int) -> Profile:
    """n points on the unit circle, counter-clockwise in the (x, z) plane,
    starting at angle 0 = (+1, 0). Exactly symmetric by construction."""
    if n not in _QUADRANT:
        raise GeometryError(f"unit_circle supports n in {sorted(_QUADRANT)}; got {n!r}")
    q = _QUADRANT[n]
    per = n // 4
    pts = []
    for k in range(n):
        quad, j = divmod(k, per)
        c, s = q[j]
        if quad == 0:
            pts.append((c, s))
        elif quad == 1:
            pts.append((_neg(s), c))
        elif quad == 2:
            pts.append((_neg(c), _neg(s)))
        else:
            pts.append((s, _neg(c)))
    return tuple(pts)


# Rectangle with corners at (+-1, +-1), counter-clockwise, in the (x, z) plane.
UNIT_RECTANGLE: Profile = ((1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0))
# Diamond (rhombus) with points on the axes, counter-clockwise: a 4-gon circle.
UNIT_DIAMOND: Profile = unit_circle(4)


@dataclass(frozen=True)
class Station:
    """One cross-section of a loft: profile scaled by (rx, rz) at height y."""

    y: float
    rx: float
    rz: float


def loft(name: str, profile: Profile, stations: list[Station], bottom_y: float, top_y: float) -> Mesh:
    """Closed shell swept along +Y through `stations`.

    The bottom and top are closed by a fan around a single center vertex on the
    Y axis at `bottom_y` / `top_y`. If that equals the end station's y the cap
    is flat; if it lies beyond, the cap is a point (apex), e.g. a blade tip.

    Vertex order: ring 0 (profile order), ring 1, ..., bottom center, top center.
    Profiles must be convex and counter-clockwise in (x, z).
    """
    n = len(profile)
    if n < 3:
        raise GeometryError(f"loft {name!r}: profile needs >= 3 points; got {n}")
    if not stations:
        raise GeometryError(f"loft {name!r}: needs at least one station")
    for i, s in enumerate(stations):
        if not (s.rx > 0.0 and s.rz > 0.0):
            raise GeometryError(f"loft {name!r}: station {i} has non-positive radius {s!r}")
        if i and not s.y > stations[i - 1].y:
            raise GeometryError(f"loft {name!r}: station y must strictly increase at index {i}")
    if not bottom_y <= stations[0].y or not top_y >= stations[-1].y:
        raise GeometryError(f"loft {name!r}: cap centers must lie outside the station range")

    positions: list[Vec3] = []
    for s in stations:
        for px, pz in profile:
            positions.append((s.rx * px, s.y, s.rz * pz))
    bottom = len(positions)
    positions.append((0.0, bottom_y, 0.0))
    top = len(positions)
    positions.append((0.0, top_y, 0.0))

    tris: list[tuple[int, int, int]] = []
    for i in range(len(stations) - 1):
        lo, hi = i * n, (i + 1) * n
        for k in range(n):
            k1 = (k + 1) % n
            a, b, c, d = lo + k, lo + k1, hi + k1, hi + k
            tris.append((a, d, c))
            tris.append((a, c, b))
    last = (len(stations) - 1) * n
    for k in range(n):
        k1 = (k + 1) % n
        tris.append((bottom, k, k1))
        tris.append((top, last + k1, last + k))

    return Mesh(name=name, positions=tuple(positions), triangles=tuple(tris))


def rotate_y_axis_to_x(p: Vec3) -> Vec3:
    """Proper rotation of -90 degrees about Z: (x, y, z) -> (y, -x, z).

    Maps +Y onto +X. Determinant +1, so triangle winding stays outward.
    Pure sign/permutation: exact in floating point.
    """
    return (p[1], _neg(p[0]), p[2])
