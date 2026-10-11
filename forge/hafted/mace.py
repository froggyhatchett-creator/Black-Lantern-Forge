"""Mace generator, version 1 (forge.mace v1): a rigid, one-handed mace with a radial striking head.

FROZEN CONTRACT once released: for a given seed this module must keep producing identical
parameters and geometry. A changed draw, bound, constant or vertex order needs a new version.

Components, in order: haft, grip, collar, head, flanges, butt_cap.
  head      the core: a turned body on the haft's top end, either round (16 sides) or
            faceted (8), with a domed top whose point is the weapon's tip
  flanges   the radial striking elements, all in one part:
              flanged  thin, tall plates (a tube-like core)
              ribbed   low, broad ridges (a bulbous core)
              lobed    rounded lobes (a bulbous core)
            Each element's inner edge is buried in the core. Their outline follows the core's
            silhouette. The element at +X carries the strike point at its widest slice.
  collar    a ring under the head, rising into the core's base
  butt_cap  a metal cap over the haft's end
No chains, no flails: every part is rigid and fixed.

Directions come from unit_circle(8 | 12) (exact). There is no trigonometry.

Streams (one per component; every value drawn unconditionally, in this order):
  forge.mace.haft      draw_haft
  forge.mace.grip      draw_grip
  forge.mace.flanges   form, count index, projection_t, thickness_t, peak, span
  forge.mace.head      core shape, core_ratio_t, height_t, seat, bottom_wall, top_ratio, dome
  forge.mace.collar    height, thickness
  forge.mace.butt_cap  draw_butt_cap
The flanges stream is read before the head stream because the form sets the core's ranges.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from types import MappingProxyType

from forge.errors import GenerationError
from forge.hafted.haft import (
    bore_volume,
    build_butt_cap,
    build_grip,
    build_haft,
    draw_butt_cap,
    draw_grip,
    draw_haft,
    layout,
    top_radii,
)
from forge.hafted.model import (
    ButtCapGeom,
    GripGeom,
    HaftedAsset,
    HaftGeom,
    Joint,
    check,
    check_ranges,
    require,
)
from forge.hafted.shapes import directions, radial_elements, ring
from forge.mesh import Mesh
from forge.prng import derive_stream
from forge.primitives import Station, loft, unit_circle

ASSET_TYPE = "mace"
GENERATOR_ID = "forge.mace"
GENERATOR_VERSION = 1
COMPONENTS = ("haft", "grip", "collar", "head", "flanges", "butt_cap")
HEAD_PARTS = ("head", "flanges", "collar")
STREAM_LABELS = MappingProxyType({c: f"forge.mace.{c}" for c in COMPONENTS})
CORE_SIDES = MappingProxyType({"round": 16, "faceted": 8})
COLLAR_OVERLAP = 0.004
_CORE_V = (0.0, 0.18, 0.40, 0.70, 1.0)          # core stations, as fractions of its height
_ELEMENT_W = (0.0, 0.18, 0.82, 1.0)             # element slices (plus the drawn peak)
_ELEMENT_CENTER = 0.55                          # elements are centered here on the core


@dataclass(frozen=True)
class Form:
    counts: tuple[int, ...]
    projection: tuple[float, float]
    half_thickness: tuple[float, float]
    core_ratio: tuple[float, float]       # core radius / (haft top radius + bottom wall)
    height: tuple[float, float]


FORMS = MappingProxyType({
    "flanged": Form(counts=(6, 8), projection=(0.014, 0.024), half_thickness=(0.0018, 0.0030),
                    core_ratio=(1.02, 1.15), height=(0.070, 0.100)),
    "ribbed": Form(counts=(8, 12), projection=(0.004, 0.008), half_thickness=(0.0020, 0.0032),
                   core_ratio=(1.18, 1.32), height=(0.056, 0.080)),
    "lobed": Form(counts=(6, 8), projection=(0.008, 0.013), half_thickness=(0.0042, 0.0065),
                  core_ratio=(1.16, 1.30), height=(0.054, 0.076)),
})


@dataclass(frozen=True)
class MaceHeadGeom:
    core_shape: str          # round | faceted
    core_radius: float       # widest core radius (m)
    height: float            # core height (m)
    seat: float              # depth of the haft inside the core / core height
    bottom_wall: float       # core wall around the haft at the core's base (m)
    top_ratio: float         # top ring radius / core radius
    dome: float              # rise of the top point above the top ring (m)
    collar_height: float     # (m)
    collar_thickness: float  # (m)


@dataclass(frozen=True)
class MaceElementsGeom:
    form: str
    count: int
    projection: float        # beyond the core surface where the element is widest (m)
    half_thickness: float    # (m)
    peak: float              # where along its height the element is widest (0..1)
    span: float              # element height / core height


@dataclass(frozen=True)
class MaceParams:
    haft: HaftGeom
    grip: GripGeom
    head: MaceHeadGeom
    elements: MaceElementsGeom
    butt_cap: ButtCapGeom

    def to_dict(self) -> dict:
        return asdict(self)


RULES = MappingProxyType({
    "haft": MappingProxyType({"length": (0.37, 0.66), "radius": (0.0115, 0.0145), "flatten": (0.92, 1.0),
                              "taper": (0.0, 0.08), "knob": (0.0, 0.0), "butt_margin": (0.010, 0.025),
                              "protrusion": (0.0, 0.0)}),
    "grip": MappingProxyType({"length": (0.10, 0.14), "wrap": (0.0015, 0.0028)}),
    "head": MappingProxyType({"core_radius": (0.015, 0.034), "seat": (0.45, 0.65), "bottom_wall": (0.003, 0.005),
                              "top_ratio": (0.55, 0.80), "dome": (0.004, 0.012), "collar_height": (0.010, 0.022),
                              "collar_thickness": (0.0012, 0.0024)}),
    "elements": MappingProxyType({"peak": (0.35, 0.65), "span": (0.55, 0.85)}),
    "butt_cap": MappingProxyType({"radius": (0.014, 0.025), "height": (0.014, 0.026)}),
    "butt_cap_ratio": (1.25, 1.70),
    "head_radius_to_haft": (1.6, 4.6),      # (core + projection) / haft radius
    "head_width": (0.040, 0.110),           # overall head diameter (m)
    "projection_to_core": (0.10, 1.60),
    "clearance": (0.06, 1.0),
    "overall": (0.40, 0.80),
    "head_mass": (0.30, 1.60),
    "lever_max": (0.0, 0.85),
})


# ------------------------------------------------------------------ derived

def _core_v(head: MaceHeadGeom, r_bottom: float) -> list[tuple[float, float]]:
    rc = head.core_radius
    radii = (r_bottom, 0.86 * rc, rc, rc, rc * head.top_ratio)
    return list(zip(_CORE_V, radii))


def _core_radius_at(stations: list[tuple[float, float]], v: float) -> float:
    for (v0, r0), (v1, r1) in zip(stations, stations[1:]):
        if v0 <= v <= v1:
            return r0 + (r1 - r0) * (v - v0) / (v1 - v0)
    raise GenerationError(f"core height fraction {v!r} outside the core")


def _shape(form: str, w: float, peak: float) -> float:
    if form == "flanged":                         # rises to the peak, falls to 45% at the top
        return 0.30 + 0.70 * w / peak if w <= peak else 1.0 - 0.55 * (w - peak) / (1.0 - peak)
    if form == "ribbed":                          # nearly constant, eased at both ends
        d = abs(w - peak) / max(peak, 1.0 - peak)
        return 1.0 - 0.5 * d * d
    half = max(peak, 1.0 - peak)                  # lobed: a rounded swell
    d = (w - peak) / half
    return 0.35 + 0.65 * math.sqrt(max(0.0, 1.0 - d * d))


def _element_outline(p: MaceParams, core: list[tuple[float, float]], core_bot: float):
    e, h = p.elements, p.head
    v0 = _ELEMENT_CENTER - 0.5 * e.span
    ws = sorted(set(_ELEMENT_W) | {e.peak})
    outline = []
    for w in ws:
        v = v0 + e.span * w
        outline.append((core_bot + h.height * v, _core_radius_at(core, v) + e.projection * _shape(e.form, w, e.peak)))
    r_min = min(_core_radius_at(core, v0 + e.span * w) for w in ws)
    return outline, 0.6 * r_min


def validate(p: MaceParams) -> None:
    w, R = ASSET_TYPE, RULES
    h, g, hd, e, c = p.haft, p.grip, p.head, p.elements, p.butt_cap
    check_ranges(w, h, R["haft"], "haft")
    check_ranges(w, g, R["grip"], "grip")
    check_ranges(w, hd, R["head"], "head")
    check_ranges(w, e, R["elements"], "elements")
    check_ranges(w, c, R["butt_cap"], "butt_cap")
    check(w, "butt_cap.radius_to_haft", c.radius / h.radius, R["butt_cap_ratio"])
    if hd.core_shape not in CORE_SIDES:
        raise GenerationError(f"{w}: core shape {hd.core_shape!r} not in {sorted(CORE_SIDES)}")
    if e.form not in FORMS:
        raise GenerationError(f"{w}: element form {e.form!r} not in {sorted(FORMS)}")
    f = FORMS[e.form]
    require(w, e.count in f.counts, f"{e.form} heads carry {list(f.counts)} elements, not {e.count}")
    check(w, "elements.projection", e.projection, f.projection)
    check(w, "elements.half_thickness", e.half_thickness, f.half_thickness)
    check(w, "head.height", hd.height, f.height)
    rt, _ = top_radii(h)
    check(w, "head.core_ratio", hd.core_radius / (rt + hd.bottom_wall), f.core_ratio)
    require(w, hd.collar_thickness < 0.9 * hd.bottom_wall, "the collar would stand proud of the head's base")
    radius = hd.core_radius + e.projection
    check(w, "head.radius_to_haft", radius / h.radius, R["head_radius_to_haft"])
    check(w, "head.width", 2.0 * radius, R["head_width"])
    check(w, "elements.projection_to_core", e.projection / hd.core_radius, R["projection_to_core"])
    y_bottom, y_top, grip_lo, grip_hi = layout(h, g)
    core_bot = y_top - hd.seat * hd.height
    check(w, "clearance", core_bot - hd.collar_height - grip_hi, R["clearance"])


def validate_assembly(asset: HaftedAsset) -> None:
    w = ASSET_TYPE
    check(w, "overall_length", asset.overall_length, RULES["overall"])
    mass = asset.head_mass_kg
    check(w, "head_mass_kg", mass, RULES["head_mass"])
    check(w, "head_leverage", mass * asset.landmark("head_center")[1], RULES["lever_max"])


# ------------------------------------------------------------------ geometry

def build(*, asset_type: str, generator_id: str, generator_version: int, seed: int, params: MaceParams) -> HaftedAsset:
    validate(params)
    h, g, hd, e = params.haft, params.grip, params.head, params.elements
    y_bottom, y_top, grip_lo, grip_hi = layout(h, g)
    rt, rzt = top_radii(h)
    core_bot = y_top - hd.seat * hd.height
    core_top = core_bot + hd.height
    core = _core_v(hd, rt + hd.bottom_wall)
    head = loft("head", unit_circle(CORE_SIDES[hd.core_shape]),
                [Station(core_bot + hd.height * v, r, r) for v, r in core], core_bot, core_top + hd.dome)
    outline, r_inner = _element_outline(params, core, core_bot)
    flanges, strike_index = radial_elements("flanges", e.form, directions(e.count), r_inner, outline,
                                            e.half_thickness)
    collar = ring("collar", core_bot - hd.collar_height, core_bot + COLLAR_OVERLAP, rt + hd.collar_thickness,
                  rzt + hd.collar_thickness)
    haft: Mesh = build_haft(h, g, core_bot, y_top, (core_bot - 0.5 * hd.collar_height,))
    grip = build_grip(h, g)
    cap = build_butt_cap(h, g, params.butt_cap)
    inner_reach = math.sqrt(r_inner * r_inner + e.half_thickness * e.half_thickness) * (1.0 + 1e-9)
    joints = (
        Joint("haft", "head", "the haft's end is seated in the head", y_lo=core_bot + 0.05 * hd.height),
        Joint("collar", "head", "the collar rises into the head's base", y_lo=core_bot + 0.001),
        Joint("haft", "collar", "the collar rings the haft", y_lo=core_bot - 0.8 * hd.collar_height,
              y_hi=core_bot - 0.2 * hd.collar_height),
        Joint("flanges", "head", "every element's inner edge is buried in the head", r_max=inner_reach),
        Joint("haft", "grip", "the wrap encloses the haft", y_lo=grip_lo + 0.1 * g.length, y_hi=grip_hi - 0.1 * g.length),
        Joint("haft", "butt_cap", "the haft's end sits in the butt cap", y_hi=y_bottom + 1e-9),
    )
    landmarks = {
        "grip_bottom_center": (0.0, grip_lo, 0.0),
        "grip_center": (0.0, 0.0, 0.0),
        "grip_top_center": (0.0, grip_hi, 0.0),
        "head_bottom": (0.0, core_bot, 0.0),
        "head_center": (0.0, core_bot + 0.5 * hd.height, 0.0),
        "strike_point": flanges.positions[strike_index],
        "tip": (0.0, core_top + hd.dome, 0.0),
    }
    asset = HaftedAsset(asset_type=asset_type, generator=generator_id, generator_version=generator_version, seed=seed,
                        params=params, components=(haft, grip, collar, head, flanges, cap),
                        landmarks=tuple(sorted(landmarks.items())), joints=joints, head_components=HEAD_PARTS,
                        head_bore_volume=bore_volume(rt, rzt, (y_top - core_bot) + hd.collar_height))
    if asset.landmark("tip") not in head.positions:
        raise GenerationError("the head's top point is not a head vertex")
    validate_assembly(asset)
    return asset


# ------------------------------------------------------------------ draws

def _lerp(rng, t: float) -> float:
    return rng[0] + (rng[1] - rng[0]) * t


def draw_params(seed: int) -> MaceParams:
    h = draw_haft(derive_stream(seed, STREAM_LABELS["haft"]), length=(0.37, 0.66), radius=(0.0115, 0.0145),
                  flatten=(0.92, 1.0), taper=(0.0, 0.08), knob=(0.0, 0.0), butt_margin=(0.010, 0.025),
                  protrusion=(0.0, 0.0))
    g = draw_grip(derive_stream(seed, STREAM_LABELS["grip"]), length=(0.10, 0.14), wrap=(0.0015, 0.0028))
    r = derive_stream(seed, STREAM_LABELS["flanges"])
    form = r.choice(tuple(FORMS))
    count_i = r.next_bounded(2)
    proj_t, thick_t = r.next_float(), r.next_float()
    peak = r.uniform(0.35, 0.65)
    span = r.uniform(0.55, 0.85)
    f = FORMS[form]
    elements = MaceElementsGeom(form=form, count=f.counts[count_i], projection=_lerp(f.projection, proj_t),
                                half_thickness=_lerp(f.half_thickness, thick_t), peak=peak, span=span)
    r = derive_stream(seed, STREAM_LABELS["head"])
    shape = r.choice(tuple(CORE_SIDES))
    ratio_t, height_t = r.next_float(), r.next_float()
    seat = r.uniform(0.45, 0.65)
    wall = r.uniform(0.003, 0.005)
    top = r.uniform(0.55, 0.80)
    dome = r.uniform(0.004, 0.012)
    r = derive_stream(seed, STREAM_LABELS["collar"])
    collar_h = r.uniform(0.010, 0.022)
    collar_t = r.uniform(0.0012, 0.0024)
    rt, _ = top_radii(h)
    head = MaceHeadGeom(core_shape=shape, core_radius=(rt + wall) * _lerp(f.core_ratio, ratio_t),
                        height=_lerp(f.height, height_t), seat=seat, bottom_wall=wall, top_ratio=top, dome=dome,
                        collar_height=collar_h, collar_thickness=collar_t)
    cap = draw_butt_cap(derive_stream(seed, STREAM_LABELS["butt_cap"]), haft_radius=h.radius,
                        shapes=("knob", "disc", "cone"), radius_ratio=(1.25, 1.70), height=(0.014, 0.026))
    return MaceParams(haft=h, grip=g, head=head, elements=elements, butt_cap=cap)


def generate(seed: int):
    """forge.mace v1. `seed` must already be validated."""
    return build(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION, seed=seed,
                 params=draw_params(seed))
