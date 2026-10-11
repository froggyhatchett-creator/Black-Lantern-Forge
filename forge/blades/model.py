"""Parameter model, plausibility rules and the immutable asset type for the blade families (Step 5A).

One parameter model serves all four families. Each family fills in the fields it uses and states
its own ranges and proportion rules (a FamilyRules table). Fields a family doesn't use hold
neutral values (sagitta_ratio 0.0 for straight blades, ricasso_length 0.0 when there is no
ricasso), and validation insists on exactly those values.

Plausibility is enforced, not hoped for. validate() raises GenerationError for:
  * any value outside the family's range
  * any proportion outside the family's ratio range (thickness to width, width to length,
    guard to blade, pommel to grip, and so on)
Nothing is clamped or repaired.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Mapping

from forge.blades.lineage import HANDS, grip_hands
from forge.errors import GenerationError
from forge.mesh import Mesh, Vec3

CROSS_SECTIONS = ("diamond", "hex", "single_edge")
GUARD_SHAPES = ("bar", "tapered", "recurved", "disc")
POMMEL_SHAPES = ("wheel", "orb", "faceted", "cap")
POINT_SHAPES = ("spear", "acute", "ogive", "leaf", "clipped")


@dataclass(frozen=True)
class BladeGeom:
    length: float               # base (guard top) to tip, along the centerline (arc length if curved)
    base_width: float           # full width at the base: edge to edge, or spine to edge
    thickness: float            # full thickness at the base (spine thickness if single-edged)
    taper: float                # fraction of width lost by the point shoulder
    distal_taper: float         # fraction of thickness lost by the point shoulder
    cross_section: str          # diamond | hex | single_edge
    flat_fraction: float        # hex / single_edge: where the edge bevel starts (fraction of half-width)
    point_shape: str
    point_length_ratio: float   # point length / blade length
    leaf_bulge: float           # leaf point only: extra width swell inside the point region
    ricasso_length: float       # unsharpened narrower base section (0.0 = none)
    ricasso_width_ratio: float  # ricasso width / base width (1.0 = no ricasso)
    sagitta_ratio: float        # curvature: max distance of centerline from chord / length (0.0 = straight)
    curve_bias: float           # curvature distribution: > 0 toward the tip, < 0 toward the base

    @property
    def shoulder_fraction(self) -> float:
        return 1.0 - self.point_length_ratio


@dataclass(frozen=True)
class GuardGeom:
    shape: str
    width: float                # span along X
    thickness: float            # extent along Y
    depth: float                # extent along Z
    end_scale: float            # tapered: end cross-section scale (1.0 otherwise)
    rise: float                 # recurved: how far the quillon tips rise toward the blade (0.0 otherwise)


@dataclass(frozen=True)
class GripGeom:
    length: float
    radius: float               # octagon circumradius at the ends, along X
    swell: float                # > 0 bulges mid-grip, < 0 waists it
    flatten: float              # Z radius / X radius (oval grips)
    segments: int


@dataclass(frozen=True)
class PommelGeom:
    shape: str
    radius: float
    height: float               # extent along Y (wheel: 2 * radius)
    thickness: float            # wheel only: extent along Z (0.0 otherwise)


@dataclass(frozen=True)
class BladeWeaponParams:
    blade: BladeGeom
    guard: GuardGeom
    grip: GripGeom
    pommel: PommelGeom

    @property
    def total_length(self) -> float:
        return self.pommel.height + self.grip.length + self.guard.thickness + self.blade.length

    def to_dict(self) -> dict:
        return {"blade": asdict(self.blade), "guard": asdict(self.guard), "grip": asdict(self.grip),
                "pommel": asdict(self.pommel)}


Range = tuple[float, float]


@dataclass(frozen=True)
class FamilyRules:
    """A family's plausibility envelope. Every range is inclusive."""
    asset_type: str
    hands: tuple[str, ...]                      # grips the family affords (lineage.grip_hands)
    blade: Mapping[str, Range]
    point_shapes: Mapping[str, Range]            # allowed point shapes -> point_length_ratio range
    cross_sections: tuple[str, ...]
    guard_shapes: tuple[str, ...]
    pommel_shapes: tuple[str, ...]
    guard: Mapping[str, Range]
    grip: Mapping[str, Range]
    grip_segments: tuple[int, int]
    pommel: Mapping[str, Range]
    ratios: Mapping[str, Range]                  # derived proportions, see proportions()
    curved: bool = False
    ricasso: bool = False
    total_length: Range = field(default=(0.0, 10.0))


def proportions(p: BladeWeaponParams) -> dict[str, float]:
    b, g, h, m = p.blade, p.guard, p.grip, p.pommel
    return {
        "blade_width_to_length": b.base_width / b.length,
        "blade_thickness_to_width": b.thickness / b.base_width,
        "guard_width_to_blade_width": g.width / b.base_width,
        "guard_depth_to_blade_thickness": g.depth / b.thickness,
        "grip_diameter_to_guard_depth": 2.0 * h.radius / g.depth,
        "pommel_radius_to_grip_radius": m.radius / h.radius,
        "grip_to_blade_length": h.length / b.length,
    }


def _in(name: str, value, rng, where: str) -> None:
    lo, hi = rng
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise GenerationError(f"{where}: {name} = {value!r} outside plausible range [{lo}, {hi}]")


def validate(p: BladeWeaponParams, rules: FamilyRules) -> None:
    """Raise GenerationError if any value or proportion is implausible for this family."""
    where = rules.asset_type
    b, g, h, m = p.blade, p.guard, p.grip, p.pommel
    for name, rng in rules.blade.items():
        _in(f"blade.{name}", getattr(b, name), rng, where)
    if b.point_shape not in rules.point_shapes:
        raise GenerationError(f"{where}: point shape {b.point_shape!r} not in {sorted(rules.point_shapes)}")
    _in("blade.point_length_ratio", b.point_length_ratio, rules.point_shapes[b.point_shape], where)
    if b.cross_section not in rules.cross_sections:
        raise GenerationError(f"{where}: cross section {b.cross_section!r} not in {list(rules.cross_sections)}")
    if b.cross_section == "diamond" and b.flat_fraction != 0.0:
        raise GenerationError(f"{where}: a diamond section has no flats (flat_fraction must be 0.0)")
    if b.point_shape != "leaf" and b.leaf_bulge != 0.0:
        raise GenerationError(f"{where}: leaf_bulge applies to leaf points only")
    if not rules.curved and (b.sagitta_ratio, b.curve_bias) != (0.0, 0.0):
        raise GenerationError(f"{where}: straight family with curvature parameters")
    if not rules.ricasso and (b.ricasso_length, b.ricasso_width_ratio) != (0.0, 1.0):
        raise GenerationError(f"{where}: family has no ricasso")
    if b.ricasso_length + b.point_length_ratio * b.length >= 0.8 * b.length:
        raise GenerationError(f"{where}: ricasso and point leave too little blade body")
    if g.shape not in rules.guard_shapes:
        raise GenerationError(f"{where}: guard shape {g.shape!r} not in {list(rules.guard_shapes)}")
    for name, rng in rules.guard.items():
        _in(f"guard.{name}", getattr(g, name), rng, where)
    if g.shape != "tapered" and g.end_scale != 1.0:
        raise GenerationError(f"{where}: end_scale applies to tapered guards only")
    if g.shape != "recurved" and g.rise != 0.0:
        raise GenerationError(f"{where}: rise applies to recurved guards only")
    if g.shape == "recurved" and not 0.0 < g.rise <= 0.35 * g.width * 0.5:
        raise GenerationError(f"{where}: recurved quillons rise {g.rise!r} m, too far for the guard span")
    for name, rng in rules.grip.items():
        _in(f"grip.{name}", getattr(h, name), rng, where)
    if any(x not in HANDS for x in rules.hands) or grip_hands(h.length) not in rules.hands:
        raise GenerationError(f"{where}: a {h.length!r} m grip is {grip_hands(h.length)}-handed; "
                              f"this family is {' or '.join(rules.hands)}")
    lo, hi = rules.grip_segments
    if type(h.segments) is not int or not lo <= h.segments <= hi:
        raise GenerationError(f"{where}: grip segments {h.segments!r} outside [{lo}, {hi}]")
    if m.shape not in rules.pommel_shapes:
        raise GenerationError(f"{where}: pommel shape {m.shape!r} not in {list(rules.pommel_shapes)}")
    for name, rng in rules.pommel.items():
        _in(f"pommel.{name}", getattr(m, name), rng, where)
    if (m.shape == "wheel") != (m.thickness > 0.0):
        raise GenerationError(f"{where}: only wheel pommels have a thickness")
    if m.shape == "wheel" and m.height != 2.0 * m.radius:
        raise GenerationError(f"{where}: a wheel pommel's height is its diameter")
    for name, rng in rules.ratios.items():
        _in(name, proportions(p)[name], rng, where)
    _in("total_length", p.total_length, rules.total_length, where)
    # the blade must sit inside the guard's footprint, the grip inside the guard's depth
    if b.base_width * 0.5 >= g.width * 0.5 or b.thickness * 0.5 >= g.depth * 0.5:
        raise GenerationError(f"{where}: the blade base is wider or thicker than the guard")
    if h.radius * max(1.0, h.flatten) >= g.depth * 0.5 and g.shape != "disc":
        raise GenerationError(f"{where}: the grip is thicker than the guard it meets")


# ------------------------------------------------------------------ the asset

@dataclass(frozen=True)
class BladeAsset:
    """Immutable result of a blade-family generator. Same shape of interface the generic code reads."""
    asset_type: str
    generator: str
    generator_version: int
    seed: int
    params: BladeWeaponParams
    components: tuple[Mesh, ...]             # blade, guard, grip, pommel
    landmarks: tuple[tuple[str, tuple], ...]  # (name, point or direction), sorted by name; canonical frame

    def __post_init__(self) -> None:
        if tuple(m.name for m in self.components) != COMPONENT_ORDER:
            raise GenerationError(f"blade-family components must be {COMPONENT_ORDER}")
        names = [k for k, _ in self.landmarks]
        if names != sorted(set(names)):
            raise GenerationError("landmarks must be unique and sorted by name")

    @property
    def component_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.components)

    def component(self, name: str) -> Mesh:
        for m in self.components:
            if m.name == name:
                return m
        raise KeyError(f"no component {name!r}; components are {COMPONENT_ORDER}")

    def landmark(self, name: str) -> tuple:
        for key, value in self.landmarks:
            if key == name:
                return value
        raise KeyError(f"no landmark {name!r}")

    @property
    def vertex_count(self) -> int:
        total = 0
        for m in self.components:
            total += m.vertex_count
        return total

    @property
    def triangle_count(self) -> int:
        total = 0
        for m in self.components:
            total += m.triangle_count
        return total

    def bounds(self) -> tuple[Vec3, Vec3]:
        mins, maxs = zip(*(m.bounds() for m in self.components))
        return ((min(p[0] for p in mins), min(p[1] for p in mins), min(p[2] for p in mins)),
                (max(p[0] for p in maxs), max(p[1] for p in maxs), max(p[2] for p in maxs)))

    def to_dict(self) -> dict:
        lo, hi = self.bounds()
        return {
            "asset_type": self.asset_type,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "units": "meters",
            "params": self.params.to_dict(),
            "derived": {"total_length": self.params.total_length},
            "landmarks": {k: list(v) for k, v in self.landmarks},
            "mesh": {
                "components": [{"name": m.name, "vertices": m.vertex_count, "triangles": m.triangle_count}
                               for m in self.components],
                "vertices": self.vertex_count,
                "triangles": self.triangle_count,
                "bounds_min": list(lo),
                "bounds_max": list(hi),
            },
        }


COMPONENT_ORDER = ("blade", "guard", "grip", "pommel")
