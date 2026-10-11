"""Short-sword parameter model and its documented bounds.

All lengths are meters. Ratios are unitless. Bounds are inclusive.
These tables are the single source of truth for docs/SWORD_MODEL.md and the
bounds tests. Changing any value changes generated swords, so it requires a
new generator version.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, fields

from forge.errors import GenerationError

# ---------------------------------------------------------------- bounds (v1)

POINT_SHAPES = ("spear", "acute", "ogive")
GUARD_SHAPES = ("bar", "tapered", "oval")
POMMEL_SHAPES = ("disc", "orb", "faceted")

BLADE_BOUNDS = {
    "length": (0.42, 0.60),          # base of blade (top of guard) to tip, along +Y
    "base_width": (0.040, 0.058),    # edge-to-edge at the base, along X
    "thickness": (0.0050, 0.0085),   # spine thickness at the base, along Z
    "taper": (0.0, 0.35),            # fraction of base width lost by the point shoulder
    "distal_taper": (0.20, 0.60),    # fraction of base thickness lost by the point shoulder
}
# Point length as a fraction of blade length, per point shape.
POINT_LENGTH_RATIO = {
    "spear": (0.08, 0.14),
    "acute": (0.16, 0.26),
    "ogive": (0.10, 0.18),
}
GUARD_BOUNDS = {
    "width": (0.090, 0.150),         # span along X
    "thickness": (0.010, 0.020),     # extent along Y (sword axis)
    "depth": (0.024, 0.036),         # extent along Z
    "end_scale": (0.50, 0.80),       # 'tapered' only: end cross-section scale vs center
}
GRIP_BOUNDS = {
    "length": (0.085, 0.110),        # along Y; grip is centered on the origin
    "radius": (0.011, 0.015),        # octagonal cross-section circumradius at the ends
    "swell": (0.0, 0.12),            # extra radius fraction at mid-grip
}
GRIP_SEGMENTS = (2, 5)               # inclusive int range: lengthwise loft segments
POMMEL_BOUNDS = {
    "radius": (0.018, 0.028),        # max radius in XZ
    "height": (0.016, 0.030),        # extent along Y
}


# ---------------------------------------------------------------- data model

@dataclass(frozen=True)
class BladeParams:
    length: float
    base_width: float
    thickness: float
    taper: float
    distal_taper: float
    point_shape: str
    point_length_ratio: float

    @property
    def shoulder_width(self) -> float:
        return self.base_width * (1.0 - self.taper)

    @property
    def shoulder_thickness(self) -> float:
        return self.thickness * (1.0 - self.distal_taper)

    @property
    def point_length(self) -> float:
        return self.length * self.point_length_ratio


@dataclass(frozen=True)
class GuardParams:
    shape: str
    width: float
    thickness: float
    depth: float
    end_scale: float  # always drawn (keeps the random stream stable); used only by 'tapered'


@dataclass(frozen=True)
class GripParams:
    length: float
    radius: float
    swell: float
    segments: int


@dataclass(frozen=True)
class PommelParams:
    shape: str
    radius: float
    height: float


@dataclass(frozen=True)
class SwordParams:
    blade: BladeParams
    guard: GuardParams
    grip: GripParams
    pommel: PommelParams

    @property
    def total_length(self) -> float:
        return self.pommel.height + self.grip.length + self.guard.thickness + self.blade.length

    def to_dict(self) -> dict:
        return {
            "blade": asdict(self.blade),
            "guard": asdict(self.guard),
            "grip": asdict(self.grip),
            "pommel": asdict(self.pommel),
        }

    def validate(self) -> None:
        """Raise GenerationError if any parameter is out of its documented bounds."""
        _check_ranges("blade", self.blade, BLADE_BOUNDS)
        _check_choice("blade.point_shape", self.blade.point_shape, POINT_SHAPES)
        _check_float("blade.point_length_ratio", self.blade.point_length_ratio,
                     POINT_LENGTH_RATIO[self.blade.point_shape])
        _check_ranges("guard", self.guard, GUARD_BOUNDS)
        _check_choice("guard.shape", self.guard.shape, GUARD_SHAPES)
        _check_ranges("grip", self.grip, GRIP_BOUNDS)
        seg = self.grip.segments
        if type(seg) is not int or not GRIP_SEGMENTS[0] <= seg <= GRIP_SEGMENTS[1]:
            raise GenerationError(f"grip.segments={seg!r} outside int range {GRIP_SEGMENTS}")
        _check_ranges("pommel", self.pommel, POMMEL_BOUNDS)
        _check_choice("pommel.shape", self.pommel.shape, POMMEL_SHAPES)
        # Every dataclass field must be covered by a check above.
        for part, bounds, extra in (
            (self.blade, BLADE_BOUNDS, {"point_shape", "point_length_ratio"}),
            (self.guard, GUARD_BOUNDS, {"shape"}),
            (self.grip, GRIP_BOUNDS, {"segments"}),
            (self.pommel, POMMEL_BOUNDS, {"shape"}),
        ):
            names = {f.name for f in fields(part)}
            if names != set(bounds) | extra:
                raise GenerationError(f"{type(part).__name__} fields {sorted(names)} not fully covered by bounds")


def _check_float(name: str, value: object, bounds: tuple[float, float]) -> None:
    lo, hi = bounds
    if type(value) is not float or not math.isfinite(value):
        raise GenerationError(f"{name}={value!r} is not a finite float")
    if not lo <= value <= hi:
        raise GenerationError(f"{name}={value!r} outside documented bounds [{lo}, {hi}]")


def _check_ranges(prefix: str, part: object, table: dict[str, tuple[float, float]]) -> None:
    for key, bounds in table.items():
        _check_float(f"{prefix}.{key}", getattr(part, key), bounds)


def _check_choice(name: str, value: object, options: tuple[str, ...]) -> None:
    if value not in options:
        raise GenerationError(f"{name}={value!r} not one of {options}")
