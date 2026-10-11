"""Long sword generator, version 1 (forge.long_sword v1): a long blade on a hand-and-a-half grip.

FROZEN CONTRACT once released: same seed -> identical parameters and geometry. Changes need a
new version.

Streams (draw orders in forge/blades/draws.py):
  forge.long_sword.blade   draw_blade
  forge.long_sword.guard   draw_guard
  forge.long_sword.grip    draw_grip
  forge.long_sword.pommel  draw_pommel
"""

from __future__ import annotations

from types import MappingProxyType

from forge.blades.build import build_asset
from forge.blades.draws import draw_blade, draw_grip, draw_guard, draw_pommel
from forge.blades.model import BladeGeom, BladeWeaponParams, FamilyRules
from forge.prng import derive_stream

ASSET_TYPE = "long_sword"
GENERATOR_ID = "forge.long_sword"
GENERATOR_VERSION = 1
STREAM_LABELS = MappingProxyType({c: f"forge.long_sword.{c}" for c in ("blade", "guard", "grip", "pommel")})

POINTS = MappingProxyType({"spear": (0.06, 0.12), "acute": (0.10, 0.18), "ogive": (0.07, 0.13)})
RULES = FamilyRules(
    asset_type=ASSET_TYPE, hands=("hand_and_half",),
    blade=MappingProxyType({"length": (0.75, 1.10), "base_width": (0.040, 0.058), "thickness": (0.0048, 0.0105),
                            "taper": (0.20, 0.55), "distal_taper": (0.35, 0.65)}),
    point_shapes=POINTS, cross_sections=("diamond", "hex"),
    guard_shapes=("bar", "tapered", "recurved"), pommel_shapes=("wheel", "orb", "faceted"),
    guard=MappingProxyType({"width": (0.136, 0.325), "thickness": (0.010, 0.020), "depth": (0.030, 0.040)}),
    grip=MappingProxyType({"length": (0.19, 0.25), "radius": (0.011, 0.0145), "swell": (-0.04, 0.10),
                           "flatten": (0.78, 0.95)}),
    grip_segments=(3, 6),
    pommel=MappingProxyType({"radius": (0.0176, 0.0377), "height": (0.026, 0.076)}),
    ratios=MappingProxyType({"blade_width_to_length": (0.036, 0.078), "blade_thickness_to_width": (0.12, 0.18),
                             "guard_width_to_blade_width": (3.4, 5.6), "guard_depth_to_blade_thickness": (2.8, 8.4),
                             "grip_diameter_to_guard_depth": (0.5, 0.97), "pommel_radius_to_grip_radius": (1.6, 2.6),
                             "grip_to_blade_length": (0.17, 0.39)}),
    total_length=(0.95, 1.55),
)


def draw_params(seed: int) -> BladeWeaponParams:
    blade = draw_blade(derive_stream(seed, STREAM_LABELS["blade"]), length=(0.75, 1.10), base_width=(0.040, 0.058),
                       thickness_ratio=(0.12, 0.18), taper=(0.20, 0.55), distal_taper=(0.35, 0.65),
                       sections=("diamond", "hex"), flat_fraction=(0.35, 0.60), points=POINTS)
    blade = BladeGeom(**blade, ricasso_length=0.0, ricasso_width_ratio=1.0, sagitta_ratio=0.0, curve_bias=0.0)
    guard = draw_guard(derive_stream(seed, STREAM_LABELS["guard"]), base_width=blade.base_width,
                       shapes=("bar", "tapered", "recurved"), width_ratio=(3.4, 5.6), disc_ratio=(1.5, 2.0),
                       thickness=(0.010, 0.020), depth=(0.030, 0.040))
    grip = draw_grip(derive_stream(seed, STREAM_LABELS["grip"]), length=(0.19, 0.25), radius=(0.011, 0.0145),
                     swell=(-0.04, 0.10), flatten=(0.78, 0.95), segments=(3, 6))
    pommel = draw_pommel(derive_stream(seed, STREAM_LABELS["pommel"]), grip_radius=grip.radius,
                         shapes=("wheel", "orb", "faceted"), radius_ratio=(1.6, 2.6), height=(0.026, 0.045),
                         cap_height=(0.012, 0.018), wheel_thickness=(0.014, 0.024))
    return BladeWeaponParams(blade=blade, guard=guard, grip=grip, pommel=pommel)


def generate(seed: int):
    """forge.long_sword v1. `seed` must already be validated."""
    return build_asset(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION,
                       seed=seed, params=draw_params(seed), rules=RULES)
