"""Short-sword generator, version 1.

FROZEN CONTRACT: for a given seed, this module must keep producing identical
parameters, geometry, and OBJ bytes. Any change that alters output -- a new
draw, a reordered draw, a bound, a constant, a vertex order -- belongs in a new
module (v2.py) registered under a new version number. Golden hashes in
tests/test_determinism.py enforce this.

Coordinate convention: right-handed, +Y up, meters. Blade tip points +Y,
blade edges lie along +/-X, blade flats face +/-Z. Origin = center of the grip.
"""

from __future__ import annotations

import math

from forge.mesh import Mesh, check_closed_oriented
from forge.prng import derive_stream
from forge.primitives import (
    SIN_COS_22_5,
    SIN_COS_45,
    UNIT_DIAMOND,
    UNIT_RECTANGLE,
    Station,
    loft,
    rotate_y_axis_to_x,
    unit_circle,
)
from forge.sword.asset import SwordAsset
from forge.sword.params import (
    BLADE_BOUNDS,
    GRIP_BOUNDS,
    GRIP_SEGMENTS,
    GUARD_BOUNDS,
    GUARD_SHAPES,
    POINT_LENGTH_RATIO,
    POINT_SHAPES,
    POMMEL_BOUNDS,
    POMMEL_SHAPES,
    BladeParams,
    GripParams,
    GuardParams,
    PommelParams,
    SwordParams,
)

GENERATOR_VERSION = 1

# One independent PCG32 stream per component. Labels are part of the contract.
STREAM_LABELS = {
    "blade": "forge.sword.blade",
    "guard": "forge.sword.guard",
    "grip": "forge.sword.grip",
    "pommel": "forge.sword.pommel",
}

# Fractions of the point length where the ogive point gets extra cross-sections.
_OGIVE_STATIONS = (0.35, 0.65, 0.85)


# ------------------------------------------------------------------ parameters
# Draw order inside each stream is part of the contract. Do not reorder.

def draw_params(seed: int) -> SwordParams:
    r = derive_stream(seed, STREAM_LABELS["blade"])
    point_shape = r.choice(POINT_SHAPES)
    blade = BladeParams(
        length=r.uniform(*BLADE_BOUNDS["length"]),
        base_width=r.uniform(*BLADE_BOUNDS["base_width"]),
        thickness=r.uniform(*BLADE_BOUNDS["thickness"]),
        taper=r.uniform(*BLADE_BOUNDS["taper"]),
        distal_taper=r.uniform(*BLADE_BOUNDS["distal_taper"]),
        point_shape=point_shape,
        point_length_ratio=r.uniform(*POINT_LENGTH_RATIO[point_shape]),
    )

    r = derive_stream(seed, STREAM_LABELS["guard"])
    guard = GuardParams(
        shape=r.choice(GUARD_SHAPES),
        width=r.uniform(*GUARD_BOUNDS["width"]),
        thickness=r.uniform(*GUARD_BOUNDS["thickness"]),
        depth=r.uniform(*GUARD_BOUNDS["depth"]),
        end_scale=r.uniform(*GUARD_BOUNDS["end_scale"]),
    )

    r = derive_stream(seed, STREAM_LABELS["grip"])
    lo, hi = GRIP_SEGMENTS
    grip = GripParams(
        length=r.uniform(*GRIP_BOUNDS["length"]),
        radius=r.uniform(*GRIP_BOUNDS["radius"]),
        swell=r.uniform(*GRIP_BOUNDS["swell"]),
        segments=lo + r.next_bounded(hi - lo + 1),
    )

    r = derive_stream(seed, STREAM_LABELS["pommel"])
    pommel = PommelParams(
        shape=r.choice(POMMEL_SHAPES),
        radius=r.uniform(*POMMEL_BOUNDS["radius"]),
        height=r.uniform(*POMMEL_BOUNDS["height"]),
    )
    return SwordParams(blade=blade, guard=guard, grip=grip, pommel=pommel)


# ------------------------------------------------------------------ geometry
# Layout along +Y (bottom to top): pommel | grip (centered on origin) | guard | blade.

def _blade(p: BladeParams, base_y: float) -> Mesh:
    y_shoulder = base_y + (p.length - p.point_length)
    y_tip = base_y + p.length
    half_w = p.shoulder_width * 0.5
    half_t = p.shoulder_thickness * 0.5
    stations = [
        Station(base_y, p.base_width * 0.5, p.thickness * 0.5),
        Station(y_shoulder, half_w, half_t),
    ]
    if p.point_shape == "ogive":
        # Elliptical edge profile w(s) = w_sh * sqrt(1 - s^2); thickness tapers linearly.
        for s in _OGIVE_STATIONS:
            stations.append(Station(y_shoulder + p.point_length * s,
                                    half_w * math.sqrt(1.0 - s * s),
                                    half_t * (1.0 - s)))
    # 'spear' and 'acute' run straight from the shoulder to the apex.
    return loft("blade", UNIT_DIAMOND, stations, bottom_y=base_y, top_y=y_tip)


def _guard(p: GuardParams, bottom_y: float) -> Mesh:
    half_w, half_t, half_d = p.width * 0.5, p.thickness * 0.5, p.depth * 0.5
    if p.shape == "oval":
        top_y = bottom_y + p.thickness
        stations = [Station(bottom_y, half_w, half_d), Station(top_y, half_w, half_d)]
        return loft("guard", unit_circle(16), stations, bottom_y, top_y)

    # 'bar' and 'tapered': loft along local +Y across the span, then rotate the
    # span onto world X. Local x (thickness) becomes world -y, local z stays z.
    if p.shape == "bar":
        stations = [Station(0.0 - half_w, half_t, half_d), Station(half_w, half_t, half_d)]
    else:  # tapered
        e = p.end_scale
        stations = [
            Station(0.0 - half_w, half_t * e, half_d * e),
            Station(0.0, half_t, half_d),
            Station(half_w, half_t * e, half_d * e),
        ]
    local = loft("guard", UNIT_RECTANGLE, stations, 0.0 - half_w, half_w)
    center_y = bottom_y + half_t
    return local.mapped(lambda q: _offset_y(rotate_y_axis_to_x(q), center_y))


def _offset_y(q: tuple[float, float, float], dy: float) -> tuple[float, float, float]:
    return (q[0], q[1] + dy, q[2])


def _grip(p: GripParams) -> Mesh:
    half = p.length * 0.5
    bottom = 0.0 - half
    stations = []
    for i in range(p.segments + 1):
        s = i / p.segments
        r = p.radius * (1.0 + p.swell * (4.0 * s * (1.0 - s)))  # swell peaks mid-grip
        stations.append(Station(bottom + p.length * s, r, r))
    return loft("grip", unit_circle(8), stations, bottom, half)


def _pommel(p: PommelParams, top_y: float) -> Mesh:
    r = p.radius
    bottom_y = top_y - p.height
    if p.shape == "disc":
        bevel = p.height * 0.2
        rb = r * 0.85
        stations = [
            Station(bottom_y, rb, rb),
            Station(bottom_y + bevel, r, r),
            Station(top_y - bevel, r, r),
            Station(top_y, rb, rb),
        ]
        return loft("pommel", unit_circle(16), stations, bottom_y, top_y)

    if p.shape == "orb":
        # Squashed sphere, pointed at the bottom pole, truncated flat at
        # +45 degrees latitude where it meets the grip.
        s22, c22 = SIN_COS_22_5
        s45, c45 = SIN_COS_45
        ry = p.height / (1.0 + s45)
        yc = top_y - ry * s45
        latitudes = ((0.0 - c22, s22), (0.0 - s45, c45), (0.0 - s22, c22), (0.0, 1.0), (s22, c22))
        stations = [Station(yc + ry * sin_l, r * cos_l, r * cos_l) for sin_l, cos_l in latitudes]
        stations.append(Station(top_y, r * c45, r * c45))
        return loft("pommel", unit_circle(16), stations, bottom_y, top_y)

    # faceted: octagonal double frustum
    stations = [
        Station(bottom_y, r * 0.6, r * 0.6),
        Station(bottom_y + p.height * 0.45, r, r),
        Station(top_y, r * 0.75, r * 0.75),
    ]
    return loft("pommel", unit_circle(8), stations, bottom_y, top_y)


def build_geometry(params: SwordParams) -> tuple[Mesh, ...]:
    grip_top = params.grip.length * 0.5
    grip_bottom = 0.0 - grip_top
    guard_top = grip_top + params.guard.thickness
    meshes = (
        _blade(params.blade, base_y=guard_top),
        _guard(params.guard, bottom_y=grip_top),
        _grip(params.grip),
        _pommel(params.pommel, top_y=grip_bottom),
    )
    for m in meshes:
        check_closed_oriented(m)  # raises GeometryError; never repaired
    return meshes


def generate(seed: int) -> SwordAsset:
    """Generate a v1 short sword. `seed` must already be validated."""
    params = draw_params(seed)
    params.validate()  # raises GenerationError if a draw escaped its bounds
    return SwordAsset(
        seed=seed,
        generator_version=GENERATOR_VERSION,
        params=params,
        components=build_geometry(params),
    )
