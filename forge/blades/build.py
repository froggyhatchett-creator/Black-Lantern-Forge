"""Turn validated blade-family parameters into geometry (shared by every blade family).

Layout along +Y, as for every Forge sword:
  pommel | grip (centered on the origin) | guard | blade
The grip spans [-G/2, +G/2]. The guard sits on the grip's top. The blade's base sits on the
guard's top center, and the pommel hangs from the grip's bottom. Components are separate closed
shells that touch at these interfaces. They are not welded.

Blade stations:
  * Straight blades are sampled where the outline changes:
      - base
      - ricasso end and flare (great swords)
      - point shoulder
      - extra point stations for ogive and leaf points
  * Curved blades are sampled at CURVED_SEGMENTS equal arc-length steps along their curved
    centerline. The width and thickness rules are the same.
In every case the last centerline sample is the apex vertex: the blade's terminal point.
"""

from __future__ import annotations

from forge.blades.model import BladeAsset, BladeGeom, BladeWeaponParams, FamilyRules, validate
from forge.blades.shapes import (
    DIAMOND,
    BladeShape,
    build_blade,
    curved_centerline,
    flat_hex,
    grip,
    guard_bar,
    guard_disc,
    guard_recurved,
    point_width_factor,
    pommel,
    single_edge,
    straight_centerline,
)
from forge.errors import GenerationError
from forge.mesh import check_closed_oriented

CURVED_SEGMENTS = 24
_POINT_STATIONS = {"ogive": (0.35, 0.65, 0.85), "leaf": (0.2, 0.4, 0.6, 0.8)}
_RICASSO_FLARE = 0.015               # fraction of blade length over which the ricasso flares to full width
MIN_CURVE_END_TANGENT_Y = 0.80       # curved blades turn by at most ~36.9 degrees in total


def _profile(b: BladeGeom):
    if b.cross_section == "diamond":
        return DIAMOND
    if b.cross_section == "hex":
        return flat_hex(b.flat_fraction)
    return single_edge(b.flat_fraction)


def _s_values(b: BladeGeom) -> tuple[float, ...]:
    s_sh = b.shoulder_fraction
    out = [0.0]
    if b.ricasso_length > 0.0:
        s_r = b.ricasso_length / b.length
        out += [s_r, s_r + _RICASSO_FLARE]
    out.append(s_sh)
    out += [s_sh + (1.0 - s_sh) * q for q in _POINT_STATIONS.get(b.point_shape, ())]
    out.append(1.0)
    return tuple(out)


def blade_shape(b: BladeGeom, base_y: float) -> BladeShape:
    if b.sagitta_ratio > 0.0:
        cl = curved_centerline(base_y, b.length, CURVED_SEGMENTS, b.sagitta_ratio, b.curve_bias)
        s_values = tuple(k / CURVED_SEGMENTS for k in range(CURVED_SEGMENTS + 1))
        if not cl.tangents[-1][1] >= MIN_CURVE_END_TANGENT_Y:
            raise GenerationError(f"curved blade turns too far (end tangent {cl.tangents[-1]!r})")
    else:
        s_values = _s_values(b)
        cl = straight_centerline(base_y, b.length, s_values)
    s_sh = b.shoulder_fraction
    s_r = b.ricasso_length / b.length
    half_base, half_thick = b.base_width * 0.5, b.thickness * 0.5
    half_sh = half_base * (1.0 - b.taper)
    thick_sh = half_thick * (1.0 - b.distal_taper)
    widths, thicks, offsets = [], [], []
    for s in s_values[:-1]:
        if s <= s_sh:
            f = s / s_sh
            w = half_base * (1.0 - b.taper * f)
            t = half_thick * (1.0 - b.distal_taper * f)
            if s_r > 0.0 and s <= s_r:
                w = half_base * b.ricasso_width_ratio
            off = 0.0
        else:
            q = (s - s_sh) / (1.0 - s_sh)
            w = half_sh * point_width_factor(b.point_shape, q, b.leaf_bulge)
            t = thick_sh * (1.0 - 0.8 * q)
            off = (w - half_sh) if b.point_shape == "clipped" else 0.0
        widths.append(w)
        thicks.append(t)
        offsets.append(off)
    apex_offset = (0.0 - half_sh) if b.point_shape == "clipped" else 0.0
    return BladeShape(centerline=cl, profile=_profile(b), half_widths=tuple(widths),
                      half_thicknesses=tuple(thicks), offsets=tuple(offsets), apex_offset=apex_offset)


def build_asset(*, asset_type: str, generator_id: str, generator_version: int, seed: int,
                params: BladeWeaponParams, rules: FamilyRules) -> BladeAsset:
    """Validate, build every component, check every shell, record landmarks. Never repairs."""
    validate(params, rules)
    b, g, h, m = params.blade, params.guard, params.grip, params.pommel
    grip_top = h.length * 0.5
    grip_bottom = 0.0 - grip_top
    base_y = grip_top + g.thickness
    blade, apex, tangent = build_blade(blade_shape(b, base_y))
    if g.shape in ("bar", "tapered"):
        guard = guard_bar(grip_top, g.width, g.thickness, g.depth, g.end_scale)
    elif g.shape == "recurved":
        guard = guard_recurved(grip_top, g.width, g.thickness, g.depth, g.rise)
    else:
        guard = guard_disc(grip_top, g.width, g.thickness, g.depth)
    meshes = (blade, guard, grip(h.length, h.radius, h.swell, h.flatten, h.segments),
              pommel(m.shape, grip_bottom, m.radius, m.height, m.thickness))
    for mesh in meshes:
        check_closed_oriented(mesh)
    landmarks = (
        ("blade_base_center", (0.0, base_y, 0.0)),
        ("blade_tip", apex),
        ("blade_tip_tangent", (tangent[0], tangent[1], 0.0)),
        ("grip_bottom_center", (0.0, grip_bottom, 0.0)),
        ("grip_center", (0.0, 0.0, 0.0)),
        ("grip_top_center", (0.0, grip_top, 0.0)),
    )
    return BladeAsset(asset_type=asset_type, generator=generator_id, generator_version=generator_version,
                      seed=seed, params=params, components=meshes, landmarks=landmarks)
