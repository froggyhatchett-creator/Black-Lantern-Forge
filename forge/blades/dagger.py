"""Dagger generator, version 1 (forge.dagger v1): a compact one-handed blade.

FROZEN CONTRACT once released: for a given seed this module must keep producing identical
parameters and geometry. A changed draw, bound, constant or vertex order needs a new version.

Streams (one per component; draw orders in forge/blades/draws.py):
  forge.dagger.blade   draw_blade
  forge.dagger.guard   draw_guard
  forge.dagger.grip    draw_grip
  forge.dagger.pommel  draw_pommel
"""

from __future__ import annotations

from types import MappingProxyType

from forge.blades.build import build_asset
from forge.blades.draws import draw_blade, draw_grip, draw_guard, draw_pommel
from forge.blades.model import BladeGeom, BladeWeaponParams, FamilyRules
from forge.prng import derive_stream

ASSET_TYPE = "dagger"
GENERATOR_ID = "forge.dagger"
GENERATOR_VERSION = 1
STREAM_LABELS = MappingProxyType({c: f"forge.dagger.{c}" for c in ("blade", "guard", "grip", "pommel")})

POINTS = MappingProxyType({"spear": (0.12, 0.22), "acute": (0.18, 0.32), "ogive": (0.12, 0.22),
                           "leaf": (0.45, 0.65)})
RULES = FamilyRules(
    asset_type=ASSET_TYPE, hands=("one",),
    blade=MappingProxyType({"length": (0.18, 0.40), "base_width": (0.022, 0.044), "thickness": (0.0030, 0.0115),
                            "taper": (0.10, 0.45), "distal_taper": (0.20, 0.55), "leaf_bulge": (0.0, 0.40)}),
    point_shapes=POINTS, cross_sections=("diamond", "hex"),
    guard_shapes=("bar", "tapered", "recurved", "disc"), pommel_shapes=("wheel", "orb", "faceted", "cap"),
    guard=MappingProxyType({"width": (0.033, 0.150), "thickness": (0.006, 0.012), "depth": (0.026, 0.090)}),
    grip=MappingProxyType({"length": (0.085, 0.115), "radius": (0.0095, 0.0125), "swell": (0.0, 0.14),
                           "flatten": (0.80, 1.0)}),
    grip_segments=(2, 5),
    pommel=MappingProxyType({"radius": (0.0123, 0.0238), "height": (0.008, 0.048)}),
    ratios=MappingProxyType({"blade_width_to_length": (0.05, 0.25), "blade_thickness_to_width": (0.14, 0.26),
                             "guard_width_to_blade_width": (1.5, 3.4), "guard_depth_to_blade_thickness": (2.2, 30.0),
                             "grip_diameter_to_guard_depth": (0.2, 0.97), "pommel_radius_to_grip_radius": (1.3, 1.9),
                             "grip_to_blade_length": (0.2, 0.65)}),
    total_length=(0.27, 0.62),
)


def draw_params(seed: int) -> BladeWeaponParams:
    blade = draw_blade(derive_stream(seed, STREAM_LABELS["blade"]), length=(0.18, 0.40), base_width=(0.022, 0.044),
                       thickness_ratio=(0.14, 0.26), taper=(0.10, 0.45), distal_taper=(0.20, 0.55),
                       sections=("diamond", "hex"), flat_fraction=(0.35, 0.65), points=POINTS)
    blade = BladeGeom(**blade, ricasso_length=0.0, ricasso_width_ratio=1.0, sagitta_ratio=0.0, curve_bias=0.0)
    guard = draw_guard(derive_stream(seed, STREAM_LABELS["guard"]), base_width=blade.base_width,
                       shapes=("bar", "tapered", "recurved", "disc"), width_ratio=(2.0, 3.4), disc_ratio=(1.5, 2.0),
                       thickness=(0.006, 0.012), depth=(0.027, 0.034))
    grip = draw_grip(derive_stream(seed, STREAM_LABELS["grip"]), length=(0.085, 0.115), radius=(0.0095, 0.0125),
                     swell=(0.0, 0.14), flatten=(0.80, 1.0), segments=(2, 5))
    pommel = draw_pommel(derive_stream(seed, STREAM_LABELS["pommel"]), grip_radius=grip.radius,
                         shapes=("wheel", "orb", "faceted", "cap"), radius_ratio=(1.3, 1.9), height=(0.014, 0.026),
                         cap_height=(0.008, 0.014), wheel_thickness=(0.010, 0.018))
    return BladeWeaponParams(blade=blade, guard=guard, grip=grip, pommel=pommel)


def generate(seed: int):
    """forge.dagger v1. `seed` must already be validated."""
    return build_asset(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION,
                       seed=seed, params=draw_params(seed), rules=RULES)
