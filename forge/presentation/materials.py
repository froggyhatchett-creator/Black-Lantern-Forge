"""Simple deterministic materials with procedural surface patterns.

material_version 1
------------------
One material per component. Each is a preset from a small palette plus small
seeded variation, plus a procedural pattern:

  base_color  linear-ish RGB in [0, 1]
  metallic    0.0 (dielectric) or 1.0 (metal)
  roughness   [0.05, 1.0]
  pattern     brushed (blade), patina (guard, pommel), wrap (grip)

Randomness: every draw comes from a PCG32 stream labelled
"forge.presentation.material.v1.<component>". These labels never collide with
the geometry streams ("forge.sword.<component>"), and the generator never sees
them, so presentation randomness cannot shift geometry randomness. Materials
depend on the seed only, not on generated geometry.

Draw order per stream (part of the v1 contract):
  blade   preset, tint, roughness_jitter, pattern.seed, pattern.strength
  guard   preset, tint, roughness_jitter, pattern.seed, pattern.strength
  grip    preset, tint, roughness_jitter, pattern.seed, pattern.bands,
          pattern.contrast, pattern.twist
  pommel  match_guard (3 in 4), preset (always drawn), tint, roughness_jitter,
          pattern.seed, pattern.strength
          If match_guard, the guard's preset is used instead of the drawn one.

  base_color = preset_color * (1 + tint), tint in [-0.06, 0.06]
  roughness  = preset_roughness + roughness_jitter, jitter in [-0.05, 0.05]

The pattern formulas in this module are also part of material_version 1.
They use integer hashing plus + - * / and floor only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import ClassVar, Union

from forge.errors import PresentationError
from forge.prng import MASK32, derive_stream
from forge.versioning import require_version

SUPPORTED_MATERIAL_VERSIONS = (1,)
MATERIAL_STREAM_PREFIX = "forge.presentation.material.v1."

_METAL = (
    ("brass", (0.86, 0.69, 0.38), 1.0, 0.32),
    ("bronze", (0.74, 0.50, 0.28), 1.0, 0.38),
    ("steel", (0.70, 0.72, 0.75), 1.0, 0.28),
    ("blackened_steel", (0.20, 0.20, 0.22), 1.0, 0.50),
)
PALETTES_V1 = {
    "blade": (
        ("bright_steel", (0.78, 0.80, 0.83), 1.0, 0.22),
        ("blued_steel", (0.42, 0.49, 0.60), 1.0, 0.30),
        ("dark_iron", (0.40, 0.40, 0.42), 1.0, 0.42),
        ("bronze", (0.80, 0.57, 0.34), 1.0, 0.30),
    ),
    "guard": _METAL,
    "grip": (
        ("brown_leather", (0.32, 0.19, 0.11), 0.0, 0.72),
        ("black_leather", (0.09, 0.08, 0.08), 0.0, 0.62),
        ("oxblood_leather", (0.36, 0.09, 0.08), 0.0, 0.66),
        ("cord_wrap", (0.56, 0.47, 0.34), 0.0, 0.88),
    ),
    "pommel": _METAL,
}
TINT_RANGE = (-0.06, 0.06)
ROUGHNESS_JITTER = (-0.05, 0.05)
ROUGHNESS_BOUNDS = (0.05, 1.0)
BRUSHED_STRENGTH = (0.04, 0.10)
PATINA_STRENGTH = (0.10, 0.25)
WRAP_BANDS = (7, 14)
WRAP_CONTRAST = (0.25, 0.50)


# ------------------------------------------------------------------ noise

def _fmix32(h: int) -> int:
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & MASK32
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & MASK32
    h ^= h >> 16
    return h


def _lattice(ix: int, iy: int, seed: int) -> float:
    return _fmix32(((ix * 0x8DA6B343) ^ (iy * 0xD8163841) ^ seed) & MASK32) / 4294967296.0


def value_noise(x: float, y: float, seed: int) -> float:
    """Smooth 2D value noise in [0, 1). Integer lattice hash + smoothstep bilinear blend."""
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    sx = fx * fx * (3.0 - 2.0 * fx)
    sy = fy * fy * (3.0 - 2.0 * fy)
    a = _lattice(ix, iy, seed)
    b = _lattice(ix + 1, iy, seed)
    c = _lattice(ix, iy + 1, seed)
    d = _lattice(ix + 1, iy + 1, seed)
    top = a + (b - a) * sx
    bottom = c + (d - c) * sx
    return top + (bottom - top) * sy


# ------------------------------------------------------------------ patterns

@dataclass(frozen=True)
class BrushedPattern:
    """Fine lengthwise streaks: color *= 1 + strength * (2n - 1), n = noise(16u, 2v)."""
    seed: int
    strength: float
    kind: ClassVar[str] = "brushed"

    def factor(self, u: float, v: float) -> float:
        return 1.0 + self.strength * (2.0 * value_noise(u * 16.0, v * 2.0, self.seed) - 1.0)

    def to_dict(self) -> dict:
        return {"type": self.kind, "seed": self.seed, "strength": self.strength}


@dataclass(frozen=True)
class PatinaPattern:
    """Blotchy darkening: color *= 1 - strength * (2 noise(5u,5v) + noise(11u,11v)) / 3."""
    seed: int
    strength: float
    kind: ClassVar[str] = "patina"

    def factor(self, u: float, v: float) -> float:
        n = (2.0 * value_noise(u * 5.0, v * 5.0, self.seed)
             + value_noise(u * 11.0, v * 11.0, self.seed ^ 0x9E3779B9)) / 3.0
        return 1.0 - self.strength * n

    def to_dict(self) -> dict:
        return {"type": self.kind, "seed": self.seed, "strength": self.strength}


@dataclass(frozen=True)
class WrapPattern:
    """Grip wrap bands: t = bands*v + twist*u; f = frac(t);
    color *= (1 - contrast + contrast * 4f(1-f)) * (1 + 0.06 (2 noise(8u, 2 bands v) - 1)).
    twist is 0 (rings) or 1 (one-band spiral per turn; seamless because u wraps at 1)."""
    seed: int
    bands: int
    contrast: float
    twist: int
    kind: ClassVar[str] = "wrap"

    def factor(self, u: float, v: float) -> float:
        t = v * self.bands + u * self.twist
        f = t - math.floor(t)
        ridge = 4.0 * f * (1.0 - f)
        grain = 1.0 + 0.06 * (2.0 * value_noise(u * 8.0, v * (2.0 * self.bands), self.seed) - 1.0)
        return ((1.0 - self.contrast) + self.contrast * ridge) * grain

    def to_dict(self) -> dict:
        return {"type": self.kind, "seed": self.seed, "bands": self.bands,
                "contrast": self.contrast, "twist": self.twist}


Pattern = Union[BrushedPattern, PatinaPattern, WrapPattern]


@dataclass(frozen=True)
class Material:
    component: str
    preset: str
    base_color: tuple[float, float, float]
    metallic: float
    roughness: float
    pattern: Pattern

    def sample(self, u: float, v: float) -> tuple[float, float, float]:
        """Patterned base color at (u, v), clamped to [0, 1]."""
        k = self.pattern.factor(u, v)
        r, g, b = self.base_color
        return (min(1.0, max(0.0, r * k)), min(1.0, max(0.0, g * k)), min(1.0, max(0.0, b * k)))

    def to_dict(self) -> dict:
        return {
            "component": self.component,
            "preset": self.preset,
            "base_color": list(self.base_color),
            "metallic": self.metallic,
            "roughness": self.roughness,
            "pattern": self.pattern.to_dict(),
        }


# ------------------------------------------------------------------ selection

def _base(rng, palette):
    name, color, metallic, roughness = rng.choice(palette)
    return name, color, metallic, roughness


def _finish(component, preset, rng):
    name, color, metallic, roughness = preset
    tint = rng.uniform(*TINT_RANGE)
    jitter = rng.uniform(*ROUGHNESS_JITTER)
    k = 1.0 + tint
    return name, (color[0] * k, color[1] * k, color[2] * k), metallic, roughness + jitter


def select_materials_v1(seed: int) -> dict[str, Material]:
    out: dict[str, Material] = {}

    r = derive_stream(seed, MATERIAL_STREAM_PREFIX + "blade")
    name, color, metal, rough = _finish("blade", _base(r, PALETTES_V1["blade"]), r)
    out["blade"] = Material("blade", name, color, metal, rough,
                            BrushedPattern(seed=r.next_u32(), strength=r.uniform(*BRUSHED_STRENGTH)))

    r = derive_stream(seed, MATERIAL_STREAM_PREFIX + "guard")
    guard_preset = _base(r, PALETTES_V1["guard"])
    name, color, metal, rough = _finish("guard", guard_preset, r)
    out["guard"] = Material("guard", name, color, metal, rough,
                            PatinaPattern(seed=r.next_u32(), strength=r.uniform(*PATINA_STRENGTH)))

    r = derive_stream(seed, MATERIAL_STREAM_PREFIX + "grip")
    name, color, metal, rough = _finish("grip", _base(r, PALETTES_V1["grip"]), r)
    lo, hi = WRAP_BANDS
    out["grip"] = Material("grip", name, color, metal, rough, WrapPattern(
        seed=r.next_u32(), bands=lo + r.next_bounded(hi - lo + 1),
        contrast=r.uniform(*WRAP_CONTRAST), twist=r.next_bounded(2)))

    r = derive_stream(seed, MATERIAL_STREAM_PREFIX + "pommel")
    match_guard = r.next_bounded(4) != 0
    drawn = _base(r, PALETTES_V1["pommel"])
    name, color, metal, rough = _finish("pommel", guard_preset if match_guard else drawn, r)
    out["pommel"] = Material("pommel", name, color, metal, rough,
                             PatinaPattern(seed=r.next_u32(), strength=r.uniform(*PATINA_STRENGTH)))

    for m in out.values():
        validate_material(m)
    return out


def validate_material(m: Material) -> None:
    where = f"material {m.component!r}"
    if len(m.base_color) != 3 or not all(type(c) is float and 0.0 <= c <= 1.0 for c in m.base_color):
        raise PresentationError(f"{where}: base_color {m.base_color!r} outside [0, 1]")
    if type(m.metallic) is not float or m.metallic not in (0.0, 1.0):
        raise PresentationError(f"{where}: metallic {m.metallic!r} must be 0.0 or 1.0")
    lo, hi = ROUGHNESS_BOUNDS
    if type(m.roughness) is not float or not lo <= m.roughness <= hi:
        raise PresentationError(f"{where}: roughness {m.roughness!r} outside [{lo}, {hi}]")


def select_materials(seed: int, material_version: int) -> dict[str, Material]:
    require_version("material_version", material_version, SUPPORTED_MATERIAL_VERSIONS)
    return select_materials_v1(seed)
