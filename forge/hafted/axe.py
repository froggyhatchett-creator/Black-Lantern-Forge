"""Axe heads and assembly, shared by one_hand_axe and two_hand_axe (Step 5B).

Components, in order: haft, grip, head, bit.
  head  the forged eye around the haft's top end, the poll behind it, and an optional collar ring
        under it, as one part of up to three closed shells
  bit   the cutting blade. Its back is buried in the eye's cheeks.

The eye is forged, not a block. Each horizontal slice of it is a convex teardrop in (x, z), 16 points:
  * behind the haft, a quarter-ellipse rounds the side walls into the poll's face
  * beside the haft, the full wall thickness
  * in front of the haft, the cheeks taper along a line of slope EYE_TAPER (with a slight swell)
    to a narrow front at x_cheek, whose half-thickness is just above the bit's there
At the neck the cheeks reach furthest forward and blend into the bit's flats. Above and below the
neck they draw back toward the haft along a parabola, w = CHEEK_END + (1 - CHEEK_END)(1 - q^2), so
the eye ends at its top and bottom as rounded lugs around the haft, as a drifted eye does, not as
a box. The poll's top and bottom corners are rounded (POLL_ROUND) and the end slices bevelled.
Inside the eye the bit's back follows the cheek front, BIT_OVERLAP behind it, so the hidden bit
does not double the head's volume; outside the eye the bit is exactly its drawn shape.

The bit is a stack of horizontal slices (y = const), each a wedge in the (x, z) plane:
  * full cheek thickness at the back
  * a secondary bevel
  * a sharp edge vertex at the front
In side view (x, y):
  * neck   for y in [neck_bot, neck_top], inside the eye's height, the bit runs from inside the
           eye's cheeks straight out to the edge
  * beard  below the neck the back line curves forward along a quarter ellipse,
           x_back = x_neck + span * (1 - sqrt(1 - q^2)), down to the beard toe
  * horn   the same curve above the neck, up to the bit's top
  * edge   x_edge(y) = projection - bulge * u^2, a convex arc; u runs -1..1 over the edge height,
           so the edge is furthest forward at its middle, the strike point
The cheek thins toward the edge at a constant wedge slope: half_thickness = slope * (x_edge - x_back).
Only + - * / and sqrt are used.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Mapping

from forge.errors import GenerationError
from forge.hafted.haft import bore_volume, build_grip, build_haft, layout, top_radii
from forge.hafted.model import GripGeom, HaftedAsset, HaftGeom, Joint, check, check_ranges, require
from forge.hafted.shapes import (
    BACK,
    BitStation,
    bent_sweep,
    chamfered_rect,
    merge,
    ring,
    slice_stack,
    stack,
    wedge,
    x_sweep,
)
from forge.primitives import unit_circle

COMPONENTS = ("haft", "grip", "head", "bit")
HEAD_PARTS = ("head", "bit")
POLLS = ("flat", "hammer", "spike")
USABLE_EYE = 0.72                # the bit's neck thickness is drawn as a fraction of this much of the eye's
COLLAR_OVERLAP = 0.003           # the collar rises this far into the eye
EYE_TAPER = 0.30                 # cheek slope dz/dx in front of the haft (about 17 degrees a side)
CHEEK_SWELL = 0.2                # the cheek bulges this fraction of the way from its straight line to the wall
CHEEK_END = 0.25                 # at the eye's top and bottom the cheeks keep this fraction of their reach
LUG_Q = (0.4, 0.7, 0.9, 1.0)     # slices between the neck and each end of the eye (fraction of the way)
POLL_ROUND = MappingProxyType({0.7: 0.97, 0.9: 0.88, 1.0: 0.70})   # poll length kept near the eye's ends
EYE_BEVEL = 0.94                 # the end slices are scaled by this about the haft axis
BIT_OVERLAP = 0.0015             # inside the eye the bit's back sits this far behind the cheek front (m)
CHEEK_MARGIN = 0.0003            # the cheek front is this much thicker than the bit there (m)
POLL_FACE = MappingProxyType({"flat": 0.70, "spike": 0.74, "hammer": 0.84})   # poll face / wall half-thickness
_BACK_S = (0.55, 0.85, 0.97)     # quarter-ellipse samples rounding the walls into the poll
_SIDE_BACK = 0.35                # the full-thickness wall runs from -0.35 * haft radius to the haft axis
_LOWER_Q = (1.0, 0.9, 0.75, 0.55, 0.3)
_UPPER_Q = (0.4, 0.75, 1.0)
Range = tuple[float, float]


@dataclass(frozen=True)
class AxeHeadGeom:
    style: str
    eye_height: float        # (m)
    wall_front: float        # eye wall in front of the haft (m)
    wall_side: float         # cheek wall beside the haft (m)
    poll: str                # flat | hammer | spike
    poll_length: float       # eye wall behind the haft (m)
    poll_reach: float        # hammer or spike length beyond the eye (m); 0.0 for a flat poll
    poll_size: float         # hammer face size, or spike base height (m); 0.0 for a flat poll
    collar_height: float     # 0.0 = no collar (m)
    collar_thickness: float  # (m)


@dataclass(frozen=True)
class AxeBitGeom:
    neck_ratio: float        # neck height / eye height
    horn: float              # rise of the bit's top above the neck (m)
    beard: float             # drop of the beard toe below the neck (m)
    projection: float        # haft axis to the edge's furthest point (m)
    bulge: float             # edge sagitta (m)
    thickness_ratio: float   # cheek half-thickness at the neck / usable eye half-thickness
    bevel_x: float
    bevel_z: float


@dataclass(frozen=True)
class AxeParams:
    haft: HaftGeom
    grip: GripGeom
    head: AxeHeadGeom
    bit: AxeBitGeom
    upper_grip: float = 0.0      # two-handed: length of the upper hand's zone below the head (m)
    throat_gap: float = 0.0      # two-handed: bare haft between that zone and the head (m)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class AxeStyle:
    eye_height: Range
    neck_ratio: Range
    horn: Range
    beard: Range
    projection: Range
    bulge_ratio: Range       # bulge / edge height
    poll_length: Range
    poll_reach: Range
    poll_size: Range


@dataclass(frozen=True)
class AxeRules:
    asset_type: str
    hands: tuple[str, ...]
    styles: Mapping[str, AxeStyle]
    polls: tuple[str, ...]
    haft: Mapping[str, Range]
    grip: Mapping[str, Range]
    head: Mapping[str, Range]          # wall_front, wall_side, collar_height, collar_thickness
    bit: Mapping[str, Range]           # thickness_ratio, bevel_x, bevel_z
    edge_height: Range
    head_length: Range                 # poll back (or spike tip) to edge (m)
    head_to_haft: Range                # head length / haft length
    projection_to_thickness: Range     # bit reach beyond the eye / eye thickness
    clearance: float                   # minimum bare haft between the grip zone and the head (m)
    overall: Range                     # overall length (m)
    head_mass: Range                   # kg, steel-equivalent from the head's volume
    mass_per_haft_area: Range          # kg per m^2 of haft cross-section under the head
    lever_max: float                   # head mass x head height above the grip center (kg m)
    upper_grip: Range = (0.0, 0.0)
    throat_gap: Range = (0.0, 0.0)
    hand_spacing: float = 0.0          # minimum gap between the two grip zones (m)


# ------------------------------------------------------------------ derived layout

@dataclass(frozen=True)
class _AxeLayout:
    y_bottom: float
    y_top: float
    grip_lo: float
    grip_hi: float
    eye_bot: float
    eye_top: float
    x_front: float
    x_back: float
    eye_half_thickness: float
    neck_bot: float
    neck_top: float
    bit_top: float
    toe: float
    x_neck: float
    tip_width: float
    rz_neck: float
    rt: float                # haft half-width under the eye (m)
    bit_slope: float         # the bit's back half-thickness per meter of slice length
    flat_slope: float        # how fast the bit's flats thin along x (dz/dx)
    x_cheek: float           # the cheeks' front at the neck (m)


def _layout(p: AxeParams) -> _AxeLayout:
    h, g, e, b = p.haft, p.grip, p.head, p.bit
    y_bottom, y_top, grip_lo, grip_hi = layout(h, g)
    rt, rzt = top_radii(h)
    eye_top = y_top - h.protrusion
    eye_bot = eye_top - e.eye_height
    x_front = rt + e.wall_front
    x_back = 0.0 - (rt + e.poll_length)
    rz_eye = rzt + e.wall_side
    neck = b.neck_ratio * e.eye_height
    neck_top = eye_top - max(0.1 * e.eye_height, 0.4 * (e.eye_height - neck))
    neck_bot = neck_top - neck
    tip = min(0.014, max(0.006, 0.08 * (b.projection - x_front)))
    x_neck = x_front - 0.5 * e.wall_front
    rz_neck = b.thickness_ratio * rz_eye * USABLE_EYE
    slope = rz_neck / (b.projection - x_neck)
    # The wedge's flat runs from its back corner to the bevel point at (1 + bevel_x) / 2 of the slice,
    # losing (1 - bevel_z) of the back half-thickness: dz/dx = slope * k.
    flat = slope * 2.0 * (1.0 - b.bevel_z) / (1.0 + b.bevel_x)
    # The cheek line z = rz_eye - EYE_TAPER * x meets the thickest the bit can be at x (with its back
    # BIT_OVERLAP behind x, at the edge's furthest reach), plus CHEEK_MARGIN.
    x_cheek = (rz_eye - _bit_bound(slope, flat, b.projection, 0.0) - CHEEK_MARGIN) / (EYE_TAPER - slope)
    return _AxeLayout(y_bottom, y_top, grip_lo, grip_hi, eye_bot, eye_top, x_front, x_back, rz_eye, neck_bot,
                      neck_top, neck_top + b.horn, neck_bot - b.beard, x_neck, tip, rz_neck, rt, slope, flat, x_cheek)


def _bit_bound(slope: float, flat: float, projection: float, x: float) -> float:
    """The bit's greatest half-thickness at x when its back is clipped to x - BIT_OVERLAP: the back
    half-thickness slope * (edge - back), less the flat's thinning over BIT_OVERLAP, at the furthest edge."""
    return slope * (projection - x + BIT_OVERLAP) - flat * BIT_OVERLAP


def _cheek_front(L: _AxeLayout, b: AxeBitGeom, w: float) -> tuple[float, float]:
    """(x, half-thickness) of the cheek front at reach fraction w (1 at the neck, CHEEK_END at the ends)."""
    x = L.x_front + (L.x_cheek - L.x_front) * w
    return x, _bit_bound(L.bit_slope, L.flat_slope, b.projection, x) + CHEEK_MARGIN


def _edge(b: AxeBitGeom, L: _AxeLayout, y: float) -> float:
    half = (L.bit_top - L.toe) * 0.5
    u = (y - (L.bit_top + L.toe) * 0.5) / half
    return b.projection - b.bulge * u * u


def _spans(b: AxeBitGeom, L: _AxeLayout) -> tuple[float, float]:
    lower = _edge(b, L, L.toe) - L.tip_width - L.x_neck
    upper = _edge(b, L, L.bit_top) - L.tip_width - L.x_neck
    return lower, upper


def _x_back(b: AxeBitGeom, L: _AxeLayout, y: float) -> float:
    lower, upper = _spans(b, L)
    if y < L.neck_bot:
        q = (L.neck_bot - y) / b.beard
        return L.x_neck + lower * (1.0 - _sqrt(1.0 - q * q))
    if y > L.neck_top:
        q = (y - L.neck_top) / b.horn
        return L.x_neck + upper * (1.0 - _sqrt(1.0 - q * q))
    return L.x_neck


def _sqrt(v: float) -> float:
    # 1 - q^2 at q = 1 can round to a tiny negative; the curve ends exactly at its tip there
    return math.sqrt(v) if v > 0.0 else 0.0


def _eye_slice(L: _AxeLayout, e: AxeHeadGeom, b: AxeBitGeom, w: float, k: float,
               poll: float) -> tuple[tuple[float, float], ...]:
    """One horizontal slice of the forged eye, convex and counter-clockwise in (x, z), 16 points:
    the cheek front pair, then the upper side from the front back to the poll face, then the lower
    side forward again. k scales the slice about the haft axis (the end bevel); poll is the fraction
    of the poll's length kept (it rounds the poll's top and bottom corners)."""
    rz = L.eye_half_thickness
    xc, zc = _cheek_front(L, b, w)
    xm = 0.45 * xc
    zl = rz + (zc - rz) * 0.45
    zm = zl + (rz - zl) * CHEEK_SWELL
    xr = 0.0 - _SIDE_BACK * L.rt
    zp = POLL_FACE[e.poll] * rz
    xb = 0.0 - (L.rt + e.poll_length * poll)
    upper = [(xc, zc), (xm, zm), (0.0, rz), (xr, rz)]
    upper += [(xr + (xb - xr) * s, zp + (rz - zp) * _sqrt(1.0 - s * s)) for s in _BACK_S]
    upper.append((xb, zp))
    lower = [(x, 0.0 - z) for x, z in reversed(upper[1:])]
    return tuple((x * k, z * k) for x, z in [(xc, 0.0 - zc)] + upper + lower)


def _eye_rows(L: _AxeLayout, e: AxeHeadGeom, b: AxeBitGeom):
    """The eye's slices bottom to top, as (y, polygon), and the cheek front x of each slice."""
    plan = [(L.eye_bot if q == 1.0 else L.neck_bot - q * (L.neck_bot - L.eye_bot), q) for q in reversed(LUG_Q)]
    plan += [(L.neck_bot, 0.0), (L.neck_top, 0.0)]
    plan += [(L.eye_top if q == 1.0 else L.neck_top + q * (L.eye_top - L.neck_top), q) for q in LUG_Q]
    rows, fronts = [], []
    for y, q in plan:
        w = CHEEK_END + (1.0 - CHEEK_END) * (1.0 - q * q)
        k = EYE_BEVEL if q == 1.0 else 1.0
        poly = _eye_slice(L, e, b, w, k, POLL_ROUND.get(q, 1.0))
        rows.append((y, poly))
        fronts.append((y, poly[0][0]))
    return rows, fronts


def _front_at(fronts: list[tuple[float, float]], y: float) -> float:
    """The eye's cheek front x at height y, interpolated along the mesh's front edge."""
    for (y0, x0), (y1, x1) in zip(fronts, fronts[1:]):
        if y0 <= y <= y1:
            return x0 + (x1 - x0) * (y - y0) / (y1 - y0)
    raise GenerationError(f"height {y!r} is outside the eye")


def head_length(p: AxeParams) -> float:
    L = _layout(p)
    back = L.x_back - (p.head.poll_reach if p.head.poll in ("hammer", "spike") else 0.0)
    return p.bit.projection - back


# ------------------------------------------------------------------ validation

def validate(p: AxeParams, rules: AxeRules) -> None:
    """Parameter plausibility. Raises GenerationError; never repairs."""
    w = rules.asset_type
    h, g, e, b = p.haft, p.grip, p.head, p.bit
    check_ranges(w, h, rules.haft, "haft")
    check_ranges(w, g, rules.grip, "grip")
    if e.style not in rules.styles:
        raise GenerationError(f"{w}: head style {e.style!r} not in {sorted(rules.styles)}")
    s = rules.styles[e.style]
    check(w, "head.eye_height", e.eye_height, s.eye_height)
    check(w, "bit.neck_ratio", b.neck_ratio, s.neck_ratio)
    check(w, "bit.horn", b.horn, s.horn)
    check(w, "bit.beard", b.beard, s.beard)
    check(w, "bit.projection", b.projection, s.projection)
    check(w, "head.poll_length", e.poll_length, s.poll_length)
    if e.poll not in rules.polls:
        raise GenerationError(f"{w}: poll {e.poll!r} not in {list(rules.polls)}")
    if e.poll == "flat":
        require(w, (e.poll_reach, e.poll_size) == (0.0, 0.0), "a flat poll has no reach or face")
    else:
        check(w, "head.poll_reach", e.poll_reach, s.poll_reach)
        check(w, "head.poll_size", e.poll_size, s.poll_size)
    check_ranges(w, e, rules.head, "head")
    require(w, e.collar_height == 0.0 or e.collar_thickness < e.wall_side * 0.9,
            "the collar would stand proud of the eye")
    check_ranges(w, b, rules.bit, "bit")
    require(w, b.bevel_z / (1.0 - b.bevel_x) >= (1.0 - b.bevel_z) / (1.0 + b.bevel_x), "edge bevel is concave")
    check(w, "upper_grip", p.upper_grip, rules.upper_grip)
    check(w, "throat_gap", p.throat_gap, rules.throat_gap)

    L = _layout(p)
    edge_height = L.bit_top - L.toe
    check(w, "bit.edge_height", edge_height, rules.edge_height)
    check(w, "bit.bulge_ratio", b.bulge / edge_height, s.bulge_ratio)
    lower, upper = _spans(b, L)
    require(w, lower >= 0.006 and upper >= 0.0, "the beard or horn tip does not reach forward of the neck")
    require(w, L.neck_top <= L.eye_top - 0.09 * e.eye_height and L.neck_bot >= L.eye_bot + 0.09 * e.eye_height,
            "the bit's neck must lie inside the eye's height")
    check(w, "bit.projection_to_thickness", (b.projection - L.x_front) / (2.0 * L.eye_half_thickness),
          rules.projection_to_thickness)
    require(w, L.bit_slope < 0.5 * EYE_TAPER, "the bit is too thick for the cheeks to taper into it")
    require(w, L.x_cheek >= L.x_front + 0.004, "the cheeks are too short to blend the eye into the bit")
    require(w, L.x_cheek <= L.x_front + 0.5 * (b.projection - L.x_front), "the cheeks would reach past half the bit")
    hl = head_length(p)
    check(w, "head.length", hl, rules.head_length)
    check(w, "head.length_to_haft", hl / h.length, rules.head_to_haft)
    if e.poll == "hammer":
        require(w, e.poll_size * 0.5 <= 0.45 * e.eye_height, "the hammer poll is taller than the eye that carries it")
    if e.poll == "spike":
        require(w, e.poll_size * 0.5 <= 0.35 * e.eye_height, "the spike base is larger than the eye")
    collar_bottom = L.eye_bot - e.collar_height
    if rules.upper_grip[1] > 0.0:
        upper_top = collar_bottom - p.throat_gap
        upper_bot = upper_top - p.upper_grip
        require(w, upper_bot - L.grip_hi >= rules.hand_spacing,
                f"only {upper_bot - L.grip_hi:.3f} m between the hands; needs {rules.hand_spacing} m")
    else:
        require(w, collar_bottom - L.grip_hi >= rules.clearance,
                f"only {collar_bottom - L.grip_hi:.3f} m of haft between the grip and the head")


def validate_assembly(asset: HaftedAsset, rules: AxeRules) -> None:
    """Checks on the built weapon: overall length, head mass and leverage."""
    w = rules.asset_type
    check(w, "overall_length", asset.overall_length, rules.overall)
    mass = asset.head_mass_kg
    check(w, "head_mass_kg", mass, rules.head_mass)
    h = asset.params.haft
    rt, rzt = top_radii(h)
    check(w, "head_mass_per_haft_area", mass / (3.141592653589793 * rt * rzt), rules.mass_per_haft_area)
    lever = mass * asset.landmark("head_center")[1]
    require(w, lever <= rules.lever_max, f"head leverage {lever:.3f} kg m exceeds {rules.lever_max} kg m")


# ------------------------------------------------------------------ geometry

def _bit_stations(b: AxeBitGeom, L: _AxeLayout, fronts: list[tuple[float, float]]) -> tuple[list[BitStation], int]:
    """Slices of the bit. Inside the eye's height the back follows the cheek front, BIT_OVERLAP behind
    it, wherever the drawn back line lies further back; the eye's own slice heights are added there so
    the two follow each other. Outside the eye the bit is exactly its drawn shape."""
    ys = [L.neck_bot - b.beard * q for q in _LOWER_Q] + [L.neck_bot, L.neck_top] + \
         [L.neck_top + b.horn * q for q in _UPPER_Q]
    mid = (L.bit_top + L.toe) * 0.5
    for y, _ in fronts:
        if L.toe < y < L.bit_top and all(abs(y - other) >= 0.0005 for other in ys):
            ys.append(y)
    ys = [y for y in ys if abs(y - mid) >= 0.0005] + [mid]
    ys.sort()
    for a, c in zip(ys, ys[1:]):
        if not c - a > 1e-4:
            raise GenerationError("bit stations collide")
    stations = []
    for y in ys:
        xb, xe = _x_back(b, L, y), _edge(b, L, y)
        if L.eye_bot <= y <= L.eye_top:
            xb = max(xb, _front_at(fronts, y) - BIT_OVERLAP)
        stations.append(BitStation(y=y, x_back=xb, x_edge=xe, half_thickness=L.bit_slope * (xe - xb)))
    return stations, ys.index(mid)


def build(*, asset_type: str, generator_id: str, generator_version: int, seed: int, params: AxeParams,
          rules: AxeRules) -> HaftedAsset:
    validate(params, rules)
    h, g, e, b = params.haft, params.grip, params.head, params.bit
    L = _layout(params)
    rt, rzt = top_radii(h)
    head_y = (L.eye_bot + L.eye_top) * 0.5

    rows, fronts = _eye_rows(L, e, b)
    parts = [slice_stack("head", rows, (0.0, 0.0))]
    extra: tuple[float, ...] = ()
    if e.collar_height > 0.0:
        parts.append(ring("head", L.eye_bot - e.collar_height, L.eye_bot + COLLAR_OVERLAP,
                          rt + e.collar_thickness, rzt + e.collar_thickness))
        extra = (L.eye_bot - 0.5 * e.collar_height,)
    if e.poll == "hammer":
        hh = e.poll_size * 0.5                     # face height from the draw
        ht = L.eye_half_thickness * 0.78           # face thickness follows the eye's cheeks
        x0, x1 = L.x_back + 0.004, L.x_back - e.poll_reach
        mesh, _ = x_sweep("head", chamfered_rect(0.15, 0.15),
                          [(x0, hh, ht), (L.x_back - 0.35 * e.poll_reach, hh, ht), (x1 + 0.0015, hh, ht),
                           (x1, hh * 0.93, ht * 0.93)], head_y, BACK)
        parts.append(mesh)
    elif e.poll == "spike":
        base = e.poll_size * 0.5
        sizes = [(base, base * 0.75), (base * 0.8, base * 0.6), (base * 0.6, base * 0.45),
                 (base * 0.4, base * 0.3), (base * 0.22, base * 0.17)]
        mesh, _, _ = bent_sweep("head", unit_circle(4), (L.x_back + 0.004, head_y), BACK, e.poll_reach * 0.85, 4,
                                0.0, sizes, e.poll_reach * 0.15 + 0.004)
        parts.append(mesh)
    head = merge("head", parts)

    stations, mid = _bit_stations(b, L, fronts)
    bit, edges = stack("bit", wedge(b.bevel_x, b.bevel_z), stations)
    strike = bit.positions[edges[mid]]

    haft = build_haft(h, g, L.eye_bot, L.eye_top, extra)
    grip = build_grip(h, g)
    margin = 0.1 * e.eye_height
    joints = [
        Joint("haft", "head", "the haft passes through the eye", y_lo=L.eye_bot + margin, y_hi=L.eye_top - margin),
        Joint("bit", "head", "the bit's back is buried in the eye's cheeks", y_lo=L.neck_bot, y_hi=L.neck_top,
              x_hi=L.x_cheek - 0.5 * BIT_OVERLAP),
        Joint("haft", "grip", "the wrap encloses the haft", y_lo=L.grip_lo + 0.1 * g.length,
              y_hi=L.grip_hi - 0.1 * g.length),
    ]
    if e.collar_height > 0.0:
        joints.append(Joint("haft", "head", "the collar rings the haft", y_lo=L.eye_bot - 0.8 * e.collar_height,
                            y_hi=L.eye_bot - 0.2 * e.collar_height))
    landmarks = {
        "eye_bottom": (0.0, L.eye_bot, 0.0),
        "eye_top": (0.0, L.eye_top, 0.0),
        "grip_bottom_center": (0.0, L.grip_lo, 0.0),
        "grip_center": (0.0, 0.0, 0.0),
        "grip_top_center": (0.0, L.grip_hi, 0.0),
        "head_center": (0.0, head_y, 0.0),
        "strike_point": strike,
        "tip": (0.0, L.y_top, 0.0),
    }
    if params.upper_grip > 0.0:
        upper_top = L.eye_bot - e.collar_height - params.throat_gap
        landmarks["upper_grip_top"] = (0.0, upper_top, 0.0)
        landmarks["upper_grip_bottom"] = (0.0, upper_top - params.upper_grip, 0.0)
    asset = HaftedAsset(asset_type=asset_type, generator=generator_id, generator_version=generator_version, seed=seed,
                        params=params, components=(haft, grip, head, bit),
                        landmarks=tuple(sorted(landmarks.items())), joints=tuple(joints), head_components=HEAD_PARTS,
                        head_bore_volume=bore_volume(rt, rzt, e.eye_height + e.collar_height))
    if asset.landmark("tip") not in haft.positions:
        raise GenerationError("the haft's top center is not a haft vertex")
    validate_assembly(asset, rules)
    return asset


# ------------------------------------------------------------------ draws (fixed order, every value drawn)

def lerp(rng: Range, t: float) -> float:
    return rng[0] + (rng[1] - rng[0]) * t


def draw_head(r, rules: AxeRules, *, wall_front: Range, wall_side: Range, collar_height: Range,
              collar_thickness: Range, poll_for) -> AxeHeadGeom:
    """Head stream order: style, eye_t, wall_front, wall_side, poll choice, poll_length_t, poll_reach_t,
    poll_size_t, collar flag, collar_height, collar_thickness."""
    style = r.choice(tuple(rules.styles))
    eye_t = r.next_float()
    wf = r.uniform(*wall_front)
    ws = r.uniform(*wall_side)
    drawn_poll = r.choice(rules.polls)
    length_t, reach_t, size_t = r.next_float(), r.next_float(), r.next_float()
    collar = r.next_bounded(2) == 1
    ch = r.uniform(*collar_height)
    ct = r.uniform(*collar_thickness)
    s = rules.styles[style]
    poll = poll_for(style, drawn_poll)
    flat = poll == "flat"
    return AxeHeadGeom(style=style, eye_height=lerp(s.eye_height, eye_t), wall_front=wf, wall_side=ws, poll=poll,
                       poll_length=lerp(s.poll_length, length_t),
                       poll_reach=0.0 if flat else lerp(s.poll_reach, reach_t),
                       poll_size=0.0 if flat else lerp(s.poll_size, size_t),
                       collar_height=ch if collar else 0.0, collar_thickness=ct if collar else 0.0)


def draw_bit(r, rules: AxeRules, head: AxeHeadGeom, *, thickness_ratio: Range, bevel_x: Range,
             bevel_z: Range) -> AxeBitGeom:
    """Bit stream order: neck_t, horn_t, beard_t, projection_t, bulge_t, thickness_ratio, bevel_x, bevel_z.
    The style's ranges come from the head stream's style choice."""
    s = rules.styles[head.style]
    neck_t, horn_t, beard_t, proj_t, bulge_t = (r.next_float() for _ in range(5))
    thick = r.uniform(*thickness_ratio)
    bx = r.uniform(*bevel_x)
    bz = r.uniform(*bevel_z)
    neck = lerp(s.neck_ratio, neck_t)
    horn = lerp(s.horn, horn_t)
    beard = lerp(s.beard, beard_t)
    edge_height = neck * head.eye_height + horn + beard
    return AxeBitGeom(neck_ratio=neck, horn=horn, beard=beard, projection=lerp(s.projection, proj_t),
                      bulge=lerp(s.bulge_ratio, bulge_t) * edge_height, thickness_ratio=thick, bevel_x=bx,
                      bevel_z=bz)
