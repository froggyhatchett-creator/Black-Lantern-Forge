"""Shared geometry for the blade families (Step 5A): profiles, centerlines, a general sweep, and
guard/grip/pommel builders.

Frozen short_sword v1 doesn't use this module, and this module changes nothing in it. It reuses
only the frozen pure helpers Mesh, check_closed_oriented, Station, loft and unit_circle, unchanged.

Determinism: only + - * / and sqrt. No trigonometry anywhere.
  * Curved centerlines turn by rational (Cayley) rotations:
        cos = (1 - t^2) / (1 + t^2),  sin = 2t / (1 + t^2)
    Each segment turns exactly by the rotation the parameter t defines, so nothing is
    approximated and nothing depends on a libm.
  * Curvature magnitude is a sagitta ratio: the largest distance of the centerline from its
    chord, divided by the blade length. A fixed-count bisection on the turning scale reaches it.

Frames: every sweep runs through the XY plane. Each station has a center C, a unit tangent T, an
in-plane normal N = (T.y, -T.x, 0), and the world Z axis. Profile x maps to N and profile z maps
to Z. (N, T, Z) is right-handed, just like (X, Y, Z) in the frozen loft, so the same
triangulation stays outward-facing. Every mesh is checked closed and outward before it's used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from forge.errors import GeometryError
from forge.mesh import Mesh, check_closed_oriented
from forge.primitives import Station, loft, unit_circle

Vec2 = tuple[float, float]
Vec3 = tuple[float, float, float]
Profile = tuple[tuple[float, float], ...]


def _neg(v: float) -> float:
    return 0.0 - v


def _unit2(x: float, y: float) -> Vec2:
    length = math.sqrt(x * x + y * y)
    if not length > 0.0:
        raise GeometryError("zero-length direction in a centerline")
    return (x / length, y / length)


# ------------------------------------------------------------------ cross-section profiles
# All counter-clockwise in (x, z), x = across the width (toward the edge), z = thickness.

DIAMOND: Profile = unit_circle(4)            # (1,0) (0,1) (-1,0) (0,-1): central ridge, two edges


def flat_hex(flat_fraction: float) -> Profile:
    """Flat-ground double edge: flats out to +-flat_fraction of the half-width, then edge bevels."""
    f = flat_fraction
    if not 0.2 <= f <= 0.8:
        raise GeometryError(f"flat_fraction {f!r} outside [0.2, 0.8]")
    return ((1.0, 0.0), (f, 1.0), (_neg(f), 1.0), (-1.0, 0.0), (_neg(f), -1.0), (f, -1.0))


def single_edge(flat_fraction: float) -> Profile:
    """Single edge at +x, flat spine at x = -1 (spine thickness = full thickness)."""
    f = flat_fraction
    if not 0.2 <= f <= 0.8:
        raise GeometryError(f"flat_fraction {f!r} outside [0.2, 0.8]")
    return ((1.0, 0.0), (f, 1.0), (-1.0, 1.0), (-1.0, -1.0), (f, -1.0))


# ------------------------------------------------------------------ centerlines

@dataclass(frozen=True)
class Centerline:
    """Samples of a planar curve from s = 0 (base) to s = 1 (end), equally spaced in arc length."""
    points: tuple[Vec2, ...]        # N + 1 points
    tangents: tuple[Vec2, ...]      # unit tangent at each point (bisector of the adjacent segments)
    length: float

    @property
    def segments(self) -> int:
        return len(self.points) - 1

    def point3(self, k: int) -> Vec3:
        return (self.points[k][0], self.points[k][1], 0.0)


def straight_centerline(base_y: float, length: float, s_values: tuple[float, ...]) -> Centerline:
    """A vertical centerline sampled at the given fractions (s_values must start at 0 and end at 1)."""
    if s_values[0] != 0.0 or s_values[-1] != 1.0 or any(b <= a for a, b in zip(s_values, s_values[1:])):
        raise GeometryError("straight centerline fractions must rise strictly from 0 to 1")
    pts = tuple((0.0, base_y + length * s) for s in s_values)
    return Centerline(points=pts, tangents=tuple((0.0, 1.0) for _ in pts), length=length)


def _rotate(d: Vec2, t: float) -> Vec2:
    """Rotate d counter-clockwise by the Cayley angle 2*atan(t), using only + - * /."""
    denom = 1.0 + t * t
    c, s = (1.0 - t * t) / denom, 2.0 * t / denom
    return _unit2(d[0] * c - d[1] * s, d[0] * s + d[1] * c)


def _integrate(base_y: float, length: float, segments: int, scale: float, bias: float):
    step = length / segments
    d = (0.0, 1.0)
    dirs = [d]
    for j in range(segments - 1):                    # turn between segment j and j + 1
        s = (j + 1) / segments
        d = _rotate(d, scale * (1.0 + bias * (2.0 * s - 1.0)))
        dirs.append(d)
    pts = [(0.0, base_y)]
    for d in dirs:
        x, y = pts[-1]
        pts.append((x + d[0] * step, y + d[1] * step))
    return pts, dirs


def _sagitta(pts) -> float:
    (x0, y0), (x1, y1) = pts[0], pts[-1]
    cx, cy = x1 - x0, y1 - y0
    chord = math.sqrt(cx * cx + cy * cy)
    worst = 0.0
    for x, y in pts:
        dist = abs((x - x0) * cy - (y - y0) * cx) / chord
        if dist > worst:
            worst = dist
    return worst


def curved_centerline(base_y: float, length: float, segments: int, sagitta_ratio: float,
                      bias: float) -> Centerline:
    """A progressively curving centerline that bends toward -X (edge on the convex +X side).

    Segment j + 1 turns relative to segment j by the Cayley parameter scale * w(s), where
    w(s) = 1 + bias * (2s - 1) and s = (j + 1) / segments. A bias above 0 puts more curvature
    toward the tip; below 0, toward the base. The base segment always leaves the guard
    vertically. `scale` is found by 60 bisection steps so that the sagitta equals
    sagitta_ratio * length.
    """
    if not (8 <= segments <= 64 and 0.0 < sagitta_ratio <= 0.12 and -1.0 <= bias <= 1.0):
        raise GeometryError("curved centerline: segments, sagitta_ratio or bias out of range")
    target = sagitta_ratio * length
    lo, hi = 0.0, 0.002
    for _ in range(40):                              # bracket: grow hi until it overshoots
        if _sagitta(_integrate(base_y, length, segments, hi, bias)[0]) >= target:
            break
        hi = hi * 2.0
    else:
        raise GeometryError("curved centerline: target sagitta not reachable")
    for _ in range(60):
        mid = (lo + hi) * 0.5
        if _sagitta(_integrate(base_y, length, segments, mid, bias)[0]) < target:
            lo = mid
        else:
            hi = mid
    pts, dirs = _integrate(base_y, length, segments, hi, bias)
    tangents = [dirs[0]]
    for k in range(1, segments):
        a, b = dirs[k - 1], dirs[k]
        tangents.append(_unit2(a[0] + b[0], a[1] + b[1]))
    tangents.append(dirs[-1])
    return Centerline(points=tuple(pts), tangents=tuple(tangents), length=length)


def parabolic_centerline(center_y: float, half_span: float, rise: float, segments: int) -> Centerline:
    """Along +X from -half_span to +half_span, y = center_y + rise * (x / half_span)^2 (recurved guard)."""
    pts, tans = [], []
    for k in range(segments + 1):
        x = (0.0 - half_span) + 2.0 * half_span * k / segments
        q = x / half_span
        pts.append((x, center_y + rise * q * q))
        tans.append(_unit2(1.0, 2.0 * rise * q / half_span))
    return Centerline(points=tuple(pts), tangents=tuple(tans), length=2.0 * half_span)


# ------------------------------------------------------------------ the sweep

@dataclass(frozen=True)
class Ring:
    center: Vec3
    tangent: Vec2         # in-plane unit tangent
    rx: float             # profile x scale (along N)
    rz: float             # profile z scale (along Z)
    offset: float = 0.0   # shift of the profile along N (a clipped point keeps its spine straight)


def sweep(name: str, profile: Profile, rings: list[Ring], *, start: Vec3, end: Vec3) -> tuple[Mesh, int]:
    """Closed shell through `rings`, capped by fans around `start` and `end`.

    A cap point that lies on its end ring's center gives a flat cap; one beyond it gives a point
    (an apex). Returns the mesh and the index of the `end` vertex.
    """
    n = len(profile)
    if len(rings) < 1 or n < 3:
        raise GeometryError(f"sweep {name!r}: needs >= 1 ring and a profile of >= 3 points")
    positions: list[Vec3] = []
    for r in rings:
        if not (r.rx > 0.0 and r.rz > 0.0):
            raise GeometryError(f"sweep {name!r}: non-positive ring scale")
        nx, ny = r.tangent[1], _neg(r.tangent[0])
        cx, cy, cz = r.center
        for px, pz in profile:
            a = r.offset + r.rx * px
            positions.append((cx + nx * a, cy + ny * a, cz + r.rz * pz))
    first = len(positions)
    positions.append(start)
    last_point = len(positions)
    positions.append(end)
    tris: list[tuple[int, int, int]] = []
    for i in range(len(rings) - 1):
        lo, hi = i * n, (i + 1) * n
        for k in range(n):
            k1 = (k + 1) % n
            a, b, c, d = lo + k, lo + k1, hi + k1, hi + k
            tris.append((a, d, c))
            tris.append((a, c, b))
    tail = (len(rings) - 1) * n
    for k in range(n):
        k1 = (k + 1) % n
        tris.append((first, k, k1))
        tris.append((last_point, tail + k1, tail + k))
    mesh = Mesh(name=name, positions=tuple(positions), triangles=tuple(tris))
    check_closed_oriented(mesh)
    return mesh, last_point


# ------------------------------------------------------------------ blades

@dataclass(frozen=True)
class BladeShape:
    """Everything the blade sweep needs, already resolved to numbers."""
    centerline: Centerline
    profile: Profile
    half_widths: tuple[float, ...]       # per centerline sample, except the last (the apex)
    half_thicknesses: tuple[float, ...]
    offsets: tuple[float, ...]           # profile shift along N (clipped points)
    apex_offset: float                   # apex shift along N at the final sample


def build_blade(shape: BladeShape) -> tuple[Mesh, Vec3, Vec2]:
    """Blade mesh, its terminal point (the apex vertex) and the tangent there."""
    cl = shape.centerline
    count = cl.segments                  # rings at samples 0 .. N - 1; the apex is sample N
    if not (len(shape.half_widths) == len(shape.half_thicknesses) == len(shape.offsets) == count):
        raise GeometryError("blade: per-ring widths, thicknesses and offsets must match the centerline")
    rings = [Ring(center=cl.point3(k), tangent=cl.tangents[k], rx=shape.half_widths[k],
                  rz=shape.half_thicknesses[k], offset=shape.offsets[k]) for k in range(count)]
    tx, ty = cl.tangents[-1]
    ex, ey = cl.points[-1]
    apex = (ex + ty * shape.apex_offset, ey + _neg(tx) * shape.apex_offset, 0.0)
    mesh, apex_index = sweep("blade", shape.profile, rings, start=cl.point3(0), end=apex)
    if mesh.positions[apex_index] != apex:
        raise GeometryError("blade: apex vertex moved")
    return mesh, apex, cl.tangents[-1]


def point_width_factor(shape: str, q: float, bulge: float = 0.0) -> float:
    """Width multiplier across the point region, q in [0, 1): 1 at the shoulder, toward 0 at the apex."""
    if shape in ("spear", "acute", "clipped"):
        return 1.0 - q
    if shape == "ogive":
        return math.sqrt(1.0 - q * q)
    if shape == "leaf":
        return (1.0 - q) * (1.0 + bulge * (1.0 - q) * q * 4.0)
    raise GeometryError(f"unknown point shape {shape!r}")


# ------------------------------------------------------------------ guards

def guard_bar(bottom_y: float, width: float, thickness: float, depth: float, end_scale: float,
              segments: int = 6) -> Mesh:
    """Straight crossguard along X; end_scale < 1 tapers toward both ends (1.0 = plain bar)."""
    half_t, half_d, half_w = thickness * 0.5, depth * 0.5, width * 0.5
    s_values = tuple(k / segments for k in range(segments + 1))
    rings = []
    for s in s_values:
        x = (0.0 - half_w) + width * s
        m = 1.0 - (1.0 - end_scale) * abs(2.0 * s - 1.0)
        rings.append(Ring(center=(x, bottom_y + half_t, 0.0), tangent=(1.0, 0.0), rx=half_t * m, rz=half_d * m))
    mesh, _ = sweep("guard", ((1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0)), rings,
                    start=rings[0].center, end=rings[-1].center)
    return mesh


def guard_recurved(bottom_y: float, width: float, thickness: float, depth: float, rise: float,
                   segments: int = 12) -> Mesh:
    """Crossguard whose quillons curve toward the blade (+Y). The center stays flat where blade and grip meet."""
    half_t, half_d = thickness * 0.5, depth * 0.5
    cl = parabolic_centerline(bottom_y + half_t, width * 0.5, rise, segments)
    rings = [Ring(center=cl.point3(k), tangent=cl.tangents[k], rx=half_t, rz=half_d) for k in range(segments + 1)]
    mesh, _ = sweep("guard", ((1.0, 1.0), (-1.0, 1.0), (-1.0, -1.0), (1.0, -1.0)), rings,
                    start=rings[0].center, end=rings[-1].center)
    return mesh


def guard_disc(bottom_y: float, width: float, thickness: float, depth: float) -> Mesh:
    """Oval plate guard (axis along Y): width along X, depth along Z."""
    top_y = bottom_y + thickness
    stations = [Station(bottom_y, width * 0.5, depth * 0.5), Station(top_y, width * 0.5, depth * 0.5)]
    return loft("guard", unit_circle(16), stations, bottom_y, top_y)


# ------------------------------------------------------------------ grips and pommels

def grip(length: float, radius: float, swell: float, flatten: float, segments: int) -> Mesh:
    """Octagonal grip centered on the origin. swell > 0 bulges mid-grip; < 0 waists it. flatten = rz/rx."""
    half = length * 0.5
    bottom = 0.0 - half
    stations = []
    for i in range(segments + 1):
        s = i / segments
        r = radius * (1.0 + swell * (4.0 * s * (1.0 - s)))
        stations.append(Station(bottom + length * s, r, r * flatten))
    return loft("grip", unit_circle(8), stations, bottom, half)


def _to_wheel(p: Vec3, center_y: float) -> Vec3:
    """Proper rotation +90 degrees about X: (x, y, z) -> (x, -z, y), then lift to center_y. Exact."""
    return (p[0], center_y - p[2], p[1])


def pommel(shape: str, top_y: float, radius: float, height: float, thickness: float) -> Mesh:
    """Pommel hanging below top_y (the grip's bottom).

    wheel    disc whose axis is Z (the classic wheel pommel); diameter along Y = 2 * radius,
             thickness along Z; its top edge touches the grip
    orb      squashed sphere, flat where it meets the grip
    faceted  octagonal double frustum
    cap      short rounded end cap, only slightly wider than the grip
    """
    if shape == "wheel":
        half = thickness * 0.5
        bevel = half * 0.45
        rb = radius * 0.86
        stations = [Station(0.0 - half, rb, rb), Station((0.0 - half) + bevel, radius, radius),
                    Station(half - bevel, radius, radius), Station(half, rb, rb)]
        local = loft("pommel", unit_circle(16), stations, 0.0 - half, half)
        center_y = top_y - radius
        mesh = local.mapped(lambda q: _to_wheel(q, center_y))
        check_closed_oriented(mesh)
        return mesh
    bottom_y = top_y - height
    if shape == "orb":
        stations = [Station(bottom_y + height * 0.12, radius * 0.55, radius * 0.55),
                    Station(bottom_y + height * 0.35, radius * 0.92, radius * 0.92),
                    Station(bottom_y + height * 0.60, radius, radius),
                    Station(bottom_y + height * 0.85, radius * 0.88, radius * 0.88),
                    Station(top_y, radius * 0.62, radius * 0.62)]
        return loft("pommel", unit_circle(16), stations, bottom_y, top_y)
    if shape == "faceted":
        stations = [Station(bottom_y, radius * 0.6, radius * 0.6),
                    Station(bottom_y + height * 0.45, radius, radius),
                    Station(top_y, radius * 0.75, radius * 0.75)]
        return loft("pommel", unit_circle(8), stations, bottom_y, top_y)
    if shape == "cap":
        stations = [Station(bottom_y + height * 0.25, radius * 0.9, radius * 0.9),
                    Station(top_y, radius, radius)]
        return loft("pommel", unit_circle(16), stations, bottom_y, top_y)
    raise GeometryError(f"unknown pommel shape {shape!r}")
