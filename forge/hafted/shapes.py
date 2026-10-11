"""Shared geometry for the hafted families (Step 5B): hafts, grip wraps, collars, butt caps, and the
head parts that mount on them (axe eyes, bits and polls, mace heads and their radial elements,
hammer faces and rear picks).

Reuse, unchanged:
  * from the frozen core: Mesh, check_closed_oriented, Station, loft and unit_circle
  * from Step 5A: forge.blades.shapes.sweep and Ring, the general closed sweep through rings
Neither is modified. Nothing in this module changes any frozen output.

Determinism: only + - * / and sqrt. There is no trigonometry anywhere:
  * Radial directions come from unit_circle (exact sqrt identities).
  * Curved picks turn by rational (Cayley) rotations.

Layout. The haft runs along +Y, with the grip zone centered on the origin. A head is built
around the haft's top end:
  * +X is the striking side: the axe edge, the hammer face, the mace's reference flange.
  * -X is the back: the poll, the spike, the pick.
  * Z is the head's thickness.
Every part is a separate closed, outward-wound shell. Parts are seated into each other (the haft
passes through the eye; a bit's back is buried in the eye wall), so the assembly has no gaps.
A part never just touches its neighbour at a single plane.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from forge.blades.shapes import Ring, sweep
from forge.errors import GeometryError
from forge.mesh import Mesh, Vec3, check_closed_oriented
from forge.primitives import Station, loft, unit_circle

Vec2 = tuple[float, float]
Profile = tuple[tuple[float, float], ...]

UP = (0.0, 1.0)
FORWARD = (1.0, 0.0)
BACK = (-1.0, 0.0)
HAFT_PROFILE = unit_circle(12)


def _neg(v: float) -> float:
    return 0.0 - v


def _unit2(x: float, y: float) -> Vec2:
    length = math.sqrt(x * x + y * y)
    if not length > 0.0:
        raise GeometryError("zero-length direction")
    return (x / length, y / length)


# ------------------------------------------------------------------ profiles (convex, counter-clockwise in (x, z))

def chamfered_rect(chamfer_x: float, chamfer_z: float) -> Profile:
    """Rectangle (+-1, +-1) with its four corners cut back by the given fractions."""
    if not (0.0 < chamfer_x < 0.5 and 0.0 < chamfer_z < 0.5):
        raise GeometryError("chamfer fractions must lie in (0, 0.5)")
    a, b = 1.0 - chamfer_x, 1.0 - chamfer_z
    return ((1.0, _neg(b)), (1.0, b), (a, 1.0), (_neg(a), 1.0),
            (-1.0, b), (-1.0, _neg(b)), (_neg(a), -1.0), (a, -1.0))


def wedge(bevel_x: float, bevel_z: float) -> Profile:
    """Cutting wedge: full thickness at x = -1, a secondary bevel at (bevel_x, +-bevel_z), and a sharp
    edge vertex at (1, 0). Profile point 0 is the edge."""
    if not (0.0 < bevel_x < 1.0 and 0.0 < bevel_z < 1.0):
        raise GeometryError("wedge bevel must lie inside the unit square")
    if not bevel_z / (1.0 - bevel_x) >= (1.0 - bevel_z) / (1.0 + bevel_x):
        raise GeometryError("wedge bevel would make the profile concave")
    return ((1.0, 0.0), (bevel_x, bevel_z), (-1.0, 1.0), (-1.0, -1.0), (bevel_x, _neg(bevel_z)))


FLANGE = ((1.0, 0.0), (0.55, 0.45), (-1.0, 1.0), (-1.0, -1.0), (0.55, -0.45))    # thin plate, keen edge
RIB = ((1.0, 0.0), (0.6, 0.8), (-1.0, 1.0), (-1.0, -1.0), (0.6, -0.8))           # low, broad ridge
LOBE = unit_circle(8)                                                             # rounded lobe
ELEMENT_PROFILES = {"flanged": FLANGE, "ribbed": RIB, "lobed": LOBE}


# ------------------------------------------------------------------ mesh helpers

def merge(name: str, meshes) -> Mesh:
    """One mesh holding several closed shells (vertex order: each input in turn)."""
    positions: list[Vec3] = []
    tris: list[tuple[int, int, int]] = []
    for m in meshes:
        base = len(positions)
        positions.extend(m.positions)
        tris.extend((a + base, b + base, c + base) for a, b, c in m.triangles)
    mesh = Mesh(name=name, positions=tuple(positions), triangles=tuple(tris))
    check_closed_oriented(mesh)
    return mesh


def rotate_about_y(mesh: Mesh, direction: Vec2) -> Mesh:
    """Proper rotation about +Y taking +X to `direction` = (x, z), a unit_circle point. Exact for (1, 0)."""
    c, s = direction
    return mesh.mapped(lambda p: (p[0] * c - p[2] * s, p[1], p[0] * s + p[2] * c))


def rotate(d: Vec2, t: float) -> Vec2:
    """Rotate d counter-clockwise by the Cayley angle 2*atan(t), using only + - * /."""
    denom = 1.0 + t * t
    c, s = (1.0 - t * t) / denom, 2.0 * t / denom
    return _unit2(d[0] * c - d[1] * s, d[0] * s + d[1] * c)


# ------------------------------------------------------------------ haft, grip, collars, caps (axial, on Y)

def haft(stations: list[Station], bottom_y: float, top_y: float) -> Mesh:
    """Oval haft: a 12-sided loft, flat-capped at both ends. Its top cap center is a vertex."""
    return loft("haft", HAFT_PROFILE, stations, bottom_y, top_y)


def grip_wrap(length: float, rx: float, rz: float, bevel: float) -> Mesh:
    """Wrap sleeve centered on the origin, enclosing the haft. Its ends are bevelled, never thinner than
    the haft beneath. rx, rz are the outer half-sizes."""
    half = length * 0.5
    lo, hi = _neg(half), half
    end = 1.0 - bevel
    stations = [Station(lo, rx * end, rz * end), Station(lo + length * 0.06, rx, rz),
                Station(hi - length * 0.06, rx, rz), Station(hi, rx * end, rz * end)]
    return loft("grip", HAFT_PROFILE, stations, lo, hi)


def ring(name: str, y0: float, y1: float, rx: float, rz: float, segments: int = 12) -> Mesh:
    """Short collar or band around the axis."""
    profile = unit_circle(segments)
    ch = (y1 - y0) * 0.2
    stations = [Station(y0, rx * 0.93, rz * 0.93), Station(y0 + ch, rx, rz), Station(y1 - ch, rx, rz),
                Station(y1, rx * 0.93, rz * 0.93)]
    return loft(name, profile, stations, y0, y1)


BUTT_CAP_SHAPES = ("knob", "disc", "cone")


def butt_cap(shape: str, haft_bottom: float, haft_rx: float, haft_rz: float, radius: float, height: float) -> Mesh:
    """Metal cap over the haft's end. It rises 40% of its height up the haft, so the haft end sits
    inside it."""
    above = height * 0.4
    top = haft_bottom + above
    bottom = haft_bottom - (height - above)
    sleeve_x, sleeve_z = haft_rx * 1.12, haft_rz * 1.12
    profile = unit_circle(16)
    if shape == "knob":
        stations = [Station(bottom + height * 0.10, radius * 0.55, radius * 0.55),
                    Station(bottom + height * 0.32, radius * 0.95, radius * 0.95),
                    Station(bottom + height * 0.55, radius, radius),
                    Station(bottom + height * 0.80, radius * 0.80, radius * 0.80),
                    Station(top, max(sleeve_x, radius * 0.62), max(sleeve_z, radius * 0.62))]
        return loft("butt_cap", profile, stations, bottom, top)
    if shape == "disc":
        stations = [Station(bottom, radius * 0.92, radius * 0.92),
                    Station(bottom + height * 0.18, radius, radius),
                    Station(bottom + height * 0.42, radius, radius),
                    Station(bottom + height * 0.62, sleeve_x * 1.1, sleeve_z * 1.1),
                    Station(top, sleeve_x, sleeve_z)]
        return loft("butt_cap", profile, stations, bottom, top)
    if shape == "cone":
        stations = [Station(bottom + height * 0.15, radius * 0.45, radius * 0.45),
                    Station(bottom + height * 0.45, radius * 0.85, radius * 0.85),
                    Station(bottom + height * 0.70, radius, radius),
                    Station(top, sleeve_x * 1.05, sleeve_z * 1.05)]
        return loft("butt_cap", profile, stations, bottom, top)
    raise GeometryError(f"unknown butt cap shape {shape!r}")


# ------------------------------------------------------------------ head blocks (vertical stacks)

def eye_block(name: str, x_back: float, x_front: float, y0: float, y1: float, half_thickness: float,
              chamfer: float) -> Mesh:
    """The socket block around the haft: x in [x_back, x_front], y in [y0, y1], z in +-half_thickness.
    The ends are bevelled by 6%."""
    cx, rx = (x_back + x_front) * 0.5, (x_front - x_back) * 0.5
    ch = (y1 - y0) * 0.08
    prof = chamfered_rect(chamfer * half_thickness / rx, chamfer)
    rings = [Ring(center=(cx, y, 0.0), tangent=UP, rx=rx * k, rz=half_thickness * k)
             for y, k in ((y0, 0.94), (y0 + ch, 1.0), (y1 - ch, 1.0), (y1, 0.94))]
    mesh, _ = sweep(name, prof, rings, start=(cx, y0, 0.0), end=(cx, y1, 0.0))
    return mesh


def convex_ccw(where: str, polygon: tuple[Vec2, ...]) -> None:
    """Raise unless polygon is strictly convex and counter-clockwise in (x, z)."""
    n = len(polygon)
    if n < 3:
        raise GeometryError(f"{where}: a slice needs at least 3 points")
    for k in range(n):
        (ax, az), (bx, bz), (cx, cz) = polygon[k - 1], polygon[k], polygon[(k + 1) % n]
        if not (bx - ax) * (cz - bz) - (bz - az) * (cx - bx) > 0.0:
            raise GeometryError(f"{where}: slice is not strictly convex and counter-clockwise at point {k}")


def slice_stack(name: str, rows: list[tuple[float, tuple[Vec2, ...]]], cap_x: tuple[float, float]) -> Mesh:
    """Closed shell through horizontal slices of any convex shape. rows are (y, polygon) with y strictly
    increasing; every polygon has the same number of points, convex and counter-clockwise in (x, z), so
    point k of one slice joins point k of the next. The bottom and top are flat fans around
    (cap_x[0], y_first, 0) and (cap_x[1], y_last, 0), which must lie inside their slices.
    Vertex order: slice 0, slice 1, ..., bottom center, top center (the frozen loft's order)."""
    if len(rows) < 2:
        raise GeometryError(f"slice_stack {name!r}: needs at least two slices")
    n = len(rows[0][1])
    positions: list[Vec3] = []
    for i, (y, poly) in enumerate(rows):
        if len(poly) != n:
            raise GeometryError(f"slice_stack {name!r}: slice {i} has {len(poly)} points, not {n}")
        if i and not y > rows[i - 1][0]:
            raise GeometryError(f"slice_stack {name!r}: slice heights must strictly increase at {i}")
        convex_ccw(f"slice_stack {name!r} slice {i}", poly)
        positions.extend((x, y, z) for x, z in poly)
    for (y, poly), cx in ((rows[0], cap_x[0]), (rows[-1], cap_x[1])):
        for k in range(n):
            (ax, az), (bx, bz) = poly[k], poly[(k + 1) % n]
            if not (bx - ax) * (0.0 - az) - (bz - az) * (cx - ax) > 0.0:
                raise GeometryError(f"slice_stack {name!r}: cap center lies outside its slice at y = {y!r}")
    bottom = len(positions)
    positions.append((cap_x[0], rows[0][0], 0.0))
    top = len(positions)
    positions.append((cap_x[1], rows[-1][0], 0.0))
    tris: list[tuple[int, int, int]] = []
    for i in range(len(rows) - 1):
        lo, hi = i * n, (i + 1) * n
        for k in range(n):
            k1 = (k + 1) % n
            a, b, c, d = lo + k, lo + k1, hi + k1, hi + k
            tris.append((a, d, c))
            tris.append((a, c, b))
    last = (len(rows) - 1) * n
    for k in range(n):
        k1 = (k + 1) % n
        tris.append((bottom, k, k1))
        tris.append((top, last + k1, last + k))
    mesh = Mesh(name=name, positions=tuple(positions), triangles=tuple(tris))
    check_closed_oriented(mesh)
    return mesh


@dataclass(frozen=True)
class BitStation:
    y: float
    x_back: float
    x_edge: float
    half_thickness: float       # at the back of the station; the wedge thins it to a sharp edge


def stack(name: str, profile: Profile, stations: list[BitStation]) -> tuple[Mesh, tuple[int, ...]]:
    """Closed stack of horizontal slices, flat-capped top and bottom. Returns the mesh and, per
    station, the index of the vertex at profile point 0 (the edge or outer apex)."""
    rings = [Ring(center=((s.x_back + s.x_edge) * 0.5, s.y, 0.0), tangent=UP, rx=(s.x_edge - s.x_back) * 0.5,
                  rz=s.half_thickness) for s in stations]
    mesh, _ = sweep(name, profile, rings, start=rings[0].center, end=rings[-1].center)
    n = len(profile)
    return mesh, tuple(k * n for k in range(len(stations)))


# ------------------------------------------------------------------ parts swept along X

def x_sweep(name: str, profile: Profile, sections: list[tuple[float, float, float]], y: float, direction: Vec2,
            apex: float | None = None) -> tuple[Mesh, int]:
    """Straight sweep along +X or -X at height y. sections are (x, half_height, half_thickness).
    The far end is flat-capped at its center or, when `apex` is given, closes on a point at x = apex.
    Returns the mesh and the index of the far-end vertex (the face center or the point)."""
    rings = [Ring(center=(x, y, 0.0), tangent=direction, rx=hh, rz=ht) for x, hh, ht in sections]
    far = (sections[-1][0] if apex is None else apex, y, 0.0)
    return sweep(name, profile, rings, start=rings[0].center, end=far)


def bent_sweep(name: str, profile: Profile, start: Vec2, direction: Vec2, length: float, segments: int,
               turn: float, sizes: list[tuple[float, float]], apex_extra: float) -> tuple[Mesh, int, Vec2]:
    """Sweep that leaves `start` along `direction` and turns by the Cayley parameter `turn` at each of
    `segments` equal steps (a circular arc; turn > 0 is counter-clockwise). sizes gives
    (half_height, half_thickness) at each of the segments + 1 rings. The part closes on a point
    `apex_extra` beyond the last ring along the final tangent. Returns the mesh, the index of
    that point, and the final tangent."""
    if len(sizes) != segments + 1:
        raise GeometryError("bent_sweep: one size per ring")
    step = length / segments
    d = direction
    pts, tans = [start], [d]
    for _ in range(segments):
        x, y = pts[-1]
        pts.append((x + d[0] * step, y + d[1] * step))
        d = rotate(d, turn)
        tans.append(d)
    rings = [Ring(center=(p[0], p[1], 0.0), tangent=t, rx=hh, rz=ht) for p, t, (hh, ht) in zip(pts, tans, sizes)]
    tip = (pts[-1][0] + tans[-1][0] * apex_extra, pts[-1][1] + tans[-1][1] * apex_extra, 0.0)
    mesh, index = sweep(name, profile, rings, start=rings[0].center, end=tip)
    return mesh, index, tans[-1]


# ------------------------------------------------------------------ mace heads

def radial_elements(name: str, form: str, count_profile: tuple[Vec2, ...], r_inner: float,
                    outline: list[tuple[float, float]], half_thickness: float) -> tuple[Mesh, int]:
    """Radial striking elements (flanges, ribs or lobes) around the Y axis.

    One element is built along +X as a stack of slices: outline is (y, r_outer) per slice and the
    inner edge sits at r_inner, buried in the head. It is then copied to every direction in
    count_profile, a unit_circle subset that starts at (1, 0). Returns the mesh and the index of the
    +X element's outer apex at its widest slice."""
    profile = ELEMENT_PROFILES[form]
    stations = [BitStation(y, r_inner, r_out, half_thickness) for y, r_out in outline]
    one, apexes = stack(name, profile, stations)
    widest = max(range(len(outline)), key=lambda k: (outline[k][1], -k))
    if count_profile[0] != (1.0, 0.0):
        raise GeometryError("radial directions must start at +X")
    parts = [one] + [rotate_about_y(one, d) for d in count_profile[1:]]
    return merge(name, parts), apexes[widest]


def directions(count: int) -> tuple[Vec2, ...]:
    """count equally spaced unit directions in the (x, z) plane, starting at +X, without trigonometry."""
    for base in (4, 8, 12, 16):
        if base % count == 0 and count <= base:
            pts = unit_circle(base)
            return tuple(pts[k] for k in range(0, base, base // count))
    raise GeometryError(f"no exact direction set for {count} elements")
