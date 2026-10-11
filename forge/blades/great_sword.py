"""Great sword generator, version 1 (forge.great_sword v1): a two-handed blade with a ricasso.

FROZEN CONTRACT once released: same seed -> identical parameters and geometry. Changes need a
new version.

Streams (draw orders in forge/blades/draws.py, plus the ricasso stream below):
  forge.great_sword.blade    draw_blade
  forge.great_sword.ricasso  length, width_ratio
  forge.great_sword.guard    draw_guard
  forge.great_sword.grip     draw_grip
  forge.great_sword.pommel   draw_pommel
The ricasso is the narrower, unsharpened base section that a gripping hand may hold. It has its
own stream, so tuning it can never shift the blade's other draws.
"""

from __future__ import annotations

from types import MappingProxyType

from forge.blades.build import build_asset
from forge.blades.draws import draw_blade, draw_grip, draw_guard, draw_pommel
from forge.blades.model import BladeGeom, BladeWeaponParams, FamilyRules
from forge.prng import derive_stream

ASSET_TYPE = "great_sword"
GENERATOR_ID = "forge.great_sword"
GENERATOR_VERSION = 1
STREAM_LABELS = MappingProxyType({c: f"forge.great_sword.{c}" for c in ("blade", "ricasso", "guard", "grip", "pommel")})

POINTS = MappingProxyType({"spear": (0.05, 0.10), "acute": (0.08, 0.14), "ogive": (0.05, 0.10)})
RULES = FamilyRules(
    asset_type=ASSET_TYPE, hands=("two",),
    blade=MappingProxyType({"length": (1.00, 1.45), "base_width": (0.048, 0.068), "thickness": (0.0057, 0.0116),
                            "taper": (0.20, 0.50), "distal_taper": (0.35, 0.65), "ricasso_length": (0.10, 0.22),
                            "ricasso_width_ratio": (0.55, 0.80)}),
    point_shapes=POINTS, cross_sections=("diamond", "hex"),
    guard_shapes=("bar", "tapered", "recurved"), pommel_shapes=("wheel", "orb", "faceted"),
    guard=MappingProxyType({"width": (0.21, 0.48), "thickness": (0.014, 0.026), "depth": (0.034, 0.046)}),
    grip=MappingProxyType({"length": (0.30, 0.46), "radius": (0.012, 0.016), "swell": (-0.08, 0.06),
                           "flatten": (0.80, 0.95)}),
    grip_segments=(4, 8),
    pommel=MappingProxyType({"radius": (0.0216, 0.0448), "height": (0.032, 0.090)}),
    ratios=MappingProxyType({"blade_width_to_length": (0.033, 0.068), "blade_thickness_to_width": (0.12, 0.17),
                             "guard_width_to_blade_width": (4.4, 7.0), "guard_depth_to_blade_thickness": (2.9, 8.1),
                             "grip_diameter_to_guard_depth": (0.5, 0.95), "pommel_radius_to_grip_radius": (1.8, 2.8),
                             "grip_to_blade_length": (0.20, 0.46)}),
    ricasso=True,
    total_length=(1.33, 2.10),
)


def draw_params(seed: int) -> BladeWeaponParams:
    blade = draw_blade(derive_stream(seed, STREAM_LABELS["blade"]), length=(1.00, 1.45), base_width=(0.048, 0.068),
                       thickness_ratio=(0.12, 0.17), taper=(0.20, 0.50), distal_taper=(0.35, 0.65),
                       sections=("diamond", "hex"), flat_fraction=(0.35, 0.60), points=POINTS)
    r = derive_stream(seed, STREAM_LABELS["ricasso"])
    ricasso_length = r.uniform(0.10, 0.22)
    ricasso_width = r.uniform(0.55, 0.80)
    blade = BladeGeom(**blade, ricasso_length=min(ricasso_length, 0.16 * blade["length"]),
                      ricasso_width_ratio=ricasso_width, sagitta_ratio=0.0, curve_bias=0.0)
    guard = draw_guard(derive_stream(seed, STREAM_LABELS["guard"]), base_width=blade.base_width,
                       shapes=("bar", "tapered", "recurved"), width_ratio=(4.4, 7.0), disc_ratio=(1.5, 2.0),
                       thickness=(0.014, 0.026), depth=(0.034, 0.046))
    grip = draw_grip(derive_stream(seed, STREAM_LABELS["grip"]), length=(0.30, 0.46), radius=(0.012, 0.016),
                     swell=(-0.08, 0.06), flatten=(0.80, 0.95), segments=(4, 8))
    pommel = draw_pommel(derive_stream(seed, STREAM_LABELS["pommel"]), grip_radius=grip.radius,
                         shapes=("wheel", "orb", "faceted"), radius_ratio=(1.8, 2.8), height=(0.032, 0.060),
                         cap_height=(0.014, 0.020), wheel_thickness=(0.018, 0.030))
    return BladeWeaponParams(blade=blade, guard=guard, grip=grip, pommel=pommel)


def generate(seed: int):
    """forge.great_sword v1. `seed` must already be validated."""
    return build_asset(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION,
                       seed=seed, params=draw_params(seed), rules=RULES)
