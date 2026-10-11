"""Parameter model, plausibility checks and the immutable asset type for the hafted families (Step 5B).

Every family shares a haft and a grip wrap (HaftGeom, GripGeom). Each family adds its own head
geometry. Validation runs twice, and either pass fails closed with GenerationError:
  * on the parameters, before any geometry is built: ranges and proportions
  * on the built assembly: overall length, head mass from the head's actual volume, the head's
    leverage about the grip for one-handed weapons, and how far the parts reach
Nothing is clamped or repaired.

HaftedAsset exposes the interface the generic code already reads:
  * asset_type, generator, generator_version, seed
  * components, component_names, to_dict()
It adds:
  * params
  * landmarks: named points that sockets and tests use
  * joints: where one part is seated inside another. The tests check them geometrically.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from forge.errors import GenerationError
from forge.mesh import Mesh, Vec3

STEEL_DENSITY_KG_M3 = 7850.0          # head mass is estimated from mesh volume at this density
HANDS = ("one", "hand_and_half", "two")
Range = tuple[float, float]


def check(where: str, name: str, value, rng: Range) -> None:
    lo, hi = rng
    if type(value) not in (int, float) or not math.isfinite(value) or not lo <= value <= hi:
        raise GenerationError(f"{where}: {name} = {value!r} outside plausible range [{lo}, {hi}]")


def check_ranges(where: str, obj, ranges: Mapping[str, Range], prefix: str) -> None:
    for name, rng in ranges.items():
        check(where, f"{prefix}.{name}", getattr(obj, name), rng)


def require(where: str, condition: bool, message: str) -> None:
    if not condition:
        raise GenerationError(f"{where}: {message}")


# ------------------------------------------------------------------ shared parameter blocks

@dataclass(frozen=True)
class HaftGeom:
    length: float          # butt end to top end (m)
    radius: float          # half-width along X over the grip (m); the haft is oval
    flatten: float         # half-depth along Z / half-width along X
    taper: float           # the haft is (1 + taper) times wider where it enters the head
    knob: float            # flare at the butt (axes); 0.0 when a butt cap covers the end
    butt_margin: float     # haft below the grip zone (m)
    protrusion: float      # haft end standing proud of the head top (m); negative = buried in the head


@dataclass(frozen=True)
class GripGeom:
    length: float          # grip zone, centered on the origin (m)
    wrap: float            # wrap thickness over the haft (m)


@dataclass(frozen=True)
class ButtCapGeom:
    shape: str             # knob | disc | cone
    radius: float          # (m)
    height: float          # (m)


@dataclass(frozen=True)
class Joint:
    """`inner` is seated in `outer`: every inner vertex inside the selection box lies inside the outer
    part's closed shell. None leaves a bound open. r_max bounds the distance from the Y axis."""
    inner: str
    outer: str
    meaning: str
    y_lo: float | None = None
    y_hi: float | None = None
    x_lo: float | None = None
    x_hi: float | None = None
    r_max: float | None = None

    def selects(self, p: Vec3) -> bool:
        x, y, z = p
        return ((self.y_lo is None or y >= self.y_lo) and (self.y_hi is None or y <= self.y_hi)
                and (self.x_lo is None or x >= self.x_lo) and (self.x_hi is None or x <= self.x_hi)
                and (self.r_max is None or x * x + z * z <= self.r_max * self.r_max))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class HaftedAsset:
    """Immutable result of a hafted-family generator."""
    asset_type: str
    generator: str
    generator_version: int
    seed: int
    params: Any                                  # the family's parameter dataclass (has to_dict())
    components: tuple[Mesh, ...]
    landmarks: tuple[tuple[str, tuple], ...]     # (name, point), sorted by name
    joints: tuple[Joint, ...]
    head_components: tuple[str, ...]             # the parts whose volume makes up the head mass
    head_bore_volume: float                      # volume of haft passing through those parts (m^3)

    def __post_init__(self) -> None:
        names = [m.name for m in self.components]
        if len(set(names)) != len(names):
            raise GenerationError(f"{self.asset_type}: component names must be unique")
        keys = [k for k, _ in self.landmarks]
        if keys != sorted(set(keys)):
            raise GenerationError(f"{self.asset_type}: landmarks must be unique and sorted by name")
        for j in self.joints:
            if j.inner not in names or j.outer not in names:
                raise GenerationError(f"{self.asset_type}: joint {j.inner}->{j.outer} names a missing component")
        if not set(self.head_components) <= set(names):
            raise GenerationError(f"{self.asset_type}: head components {self.head_components} not all present")

    @property
    def component_names(self) -> tuple[str, ...]:
        return tuple(m.name for m in self.components)

    def component(self, name: str) -> Mesh:
        for m in self.components:
            if m.name == name:
                return m
        raise KeyError(f"no component {name!r}; components are {self.component_names}")

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

    @property
    def overall_length(self) -> float:
        lo, hi = self.bounds()
        return hi[1] - lo[1]

    @property
    def head_mass_kg(self) -> float:
        """Steel-equivalent mass of the head: the closed-shell volume of the head parts, less the haft
        that passes through them (the eye is solid in the mesh), at steel density. It is an
        estimate: overlapping shells inside one part count twice."""
        volume = 0.0 - self.head_bore_volume
        for name in self.head_components:
            volume += self.component(name).signed_volume()
        return volume * STEEL_DENSITY_KG_M3

    def to_dict(self) -> dict:
        lo, hi = self.bounds()
        return {
            "asset_type": self.asset_type,
            "generator": self.generator,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "units": "meters",
            "params": self.params.to_dict(),
            "derived": {"overall_length": self.overall_length, "head_mass_kg": self.head_mass_kg,
                        "width": hi[0] - lo[0], "depth": hi[2] - lo[2]},
            "landmarks": {k: list(v) for k, v in self.landmarks},
            "joints": [j.to_dict() for j in self.joints],
            "mesh": {
                "components": [{"name": m.name, "vertices": m.vertex_count, "triangles": m.triangle_count}
                               for m in self.components],
                "vertices": self.vertex_count,
                "triangles": self.triangle_count,
                "bounds_min": list(lo),
                "bounds_max": list(hi),
            },
        }


def params_dict(obj) -> dict:
    return asdict(obj)


def hands_for(grip_length: float, nominal: tuple[str, ...]) -> str:
    """The grip a weapon affords. Families with one nominal grip return it. The war hammer reads
    its grip zone: 0.15 m or more is hand-and-a-half."""
    if len(nominal) == 1:
        return nominal[0]
    return "hand_and_half" if grip_length >= 0.15 else "one"
