"""Shared parameter draws for the hilt (guard, grip, pommel) of every blade family.

Each helper reads one PCG32 stream in a fixed order, drawing every value unconditionally so the
stream position never depends on an earlier choice. The ranges come from the calling family.
These orders are part of every family's v1 contract.

  guard   shape, width_ratio, thickness, depth, end_scale, rise_ratio
  grip    length, radius, swell, flatten, segments
  pommel  shape, radius_ratio, height_t, wheel_thickness
"""

from __future__ import annotations

from forge.blades.model import GripGeom, GuardGeom, PommelGeom

Range = tuple[float, float]


def draw_guard(r, *, base_width: float, shapes: tuple[str, ...], width_ratio: Range, disc_ratio: Range,
               thickness: Range, depth: Range, end_scale: Range = (0.55, 0.85),
               rise_ratio: Range = (0.10, 0.30)) -> GuardGeom:
    shape = r.choice(shapes)
    t_width = r.next_float()
    g_thickness = r.uniform(*thickness)
    g_depth = r.uniform(*depth)
    g_end = r.uniform(*end_scale)
    g_rise = r.uniform(*rise_ratio)
    if shape == "disc":                       # round/oval plate, as deep as ~95% of its width
        width = base_width * (disc_ratio[0] + (disc_ratio[1] - disc_ratio[0]) * t_width)
        return GuardGeom(shape, width, g_thickness, width * 0.95, 1.0, 0.0)
    width = base_width * (width_ratio[0] + (width_ratio[1] - width_ratio[0]) * t_width)
    return GuardGeom(shape, width, g_thickness, g_depth, g_end if shape == "tapered" else 1.0,
                     width * 0.5 * g_rise if shape == "recurved" else 0.0)


def draw_grip(r, *, length: Range, radius: Range, swell: Range, flatten: Range,
              segments: tuple[int, int]) -> GripGeom:
    return GripGeom(length=r.uniform(*length), radius=r.uniform(*radius), swell=r.uniform(*swell),
                    flatten=r.uniform(*flatten), segments=segments[0] + r.next_bounded(segments[1] - segments[0] + 1))


def draw_pommel(r, *, grip_radius: float, shapes: tuple[str, ...], radius_ratio: Range, height: Range,
                cap_height: Range, wheel_thickness: Range) -> PommelGeom:
    shape = r.choice(shapes)
    radius = grip_radius * r.uniform(*radius_ratio)
    t = r.next_float()
    w_thick = r.uniform(*wheel_thickness)
    if shape == "wheel":
        return PommelGeom(shape, radius, 2.0 * radius, w_thick)
    if shape == "cap":
        return PommelGeom(shape, radius, cap_height[0] + (cap_height[1] - cap_height[0]) * t, 0.0)
    return PommelGeom(shape, radius, height[0] + (height[1] - height[0]) * t, 0.0)


def draw_blade(r, *, length: Range, base_width: Range, thickness_ratio: Range, taper: Range, distal_taper: Range,
               sections: tuple[str, ...], flat_fraction: Range, points, leaf_bulge: Range = (0.15, 0.40)) -> dict:
    """Blade fields common to every family, in stream order:
    length, base_width, thickness_ratio, taper, distal_taper, cross_section, flat_fraction,
    point_shape, point_ratio_t, leaf_bulge. Returns BladeGeom keyword arguments; the family adds
    ricasso and curvature from their own streams."""
    b_length = r.uniform(*length)
    b_width = r.uniform(*base_width)
    b_thickness = b_width * r.uniform(*thickness_ratio)
    b_taper = r.uniform(*taper)
    b_distal = r.uniform(*distal_taper)
    section = r.choice(sections)
    flat = r.uniform(*flat_fraction)
    point = r.choice(tuple(points))
    lo, hi = points[point]
    point_ratio = lo + (hi - lo) * r.next_float()
    bulge = r.uniform(*leaf_bulge)
    return dict(length=b_length, base_width=b_width, thickness=b_thickness, taper=b_taper, distal_taper=b_distal,
                cross_section=section, flat_fraction=0.0 if section == "diamond" else flat, point_shape=point,
                point_length_ratio=point_ratio, leaf_bulge=bulge if point == "leaf" else 0.0)
