"""Curved sword generator, version 1 (forge.curved_sword v1): a single-edged, progressively curved blade.

The blade really curves. Its centerline turns a little between each of 24 equal arc-length segments
(rational Cayley rotations, no trigonometry; see forge/blades/shapes.py). The body follows that
curve; it isn't a straight blade rotated, nor one with only the tip bent. The edge is on the convex
(+X) side. The point is clipped toward the spine, so the terminal point sits on the spine line,
neither on the centerline nor necessarily at the highest y.

FROZEN CONTRACT once released: same seed -> identical parameters and geometry. Changes need a
new version.

Streams (draw orders in forge/blades/draws.py, plus the curvature stream below):
  forge.curved_sword.blade      draw_blade
  forge.curved_sword.curvature  sagitta_ratio, curve_bias
  forge.curved_sword.guard      draw_guard
  forge.curved_sword.grip       draw_grip
  forge.curved_sword.pommel     draw_pommel
"""

from __future__ import annotations

from types import MappingProxyType

from forge.blades.build import build_asset
from forge.blades.draws import draw_blade, draw_grip, draw_guard, draw_pommel
from forge.blades.model import BladeGeom, BladeWeaponParams, FamilyRules
from forge.prng import derive_stream

ASSET_TYPE = "curved_sword"
GENERATOR_ID = "forge.curved_sword"
GENERATOR_VERSION = 1
STREAM_LABELS = MappingProxyType({c: f"forge.curved_sword.{c}"
                                  for c in ("blade", "curvature", "guard", "grip", "pommel")})

POINTS = MappingProxyType({"clipped": (0.08, 0.16)})
SAGITTA_RATIO = (0.015, 0.060)
CURVE_BIAS = (-0.5, 0.9)
RULES = FamilyRules(
    asset_type=ASSET_TYPE, hands=("one", "hand_and_half"),
    blade=MappingProxyType({"length": (0.60, 0.90), "base_width": (0.028, 0.040), "thickness": (0.0050, 0.0120),
                            "taper": (0.10, 0.35), "distal_taper": (0.20, 0.50), "flat_fraction": (0.35, 0.60),
                            "sagitta_ratio": SAGITTA_RATIO, "curve_bias": CURVE_BIAS}),
    point_shapes=POINTS, cross_sections=("single_edge",),
    guard_shapes=("bar", "tapered", "disc"), pommel_shapes=("cap", "orb"),
    guard=MappingProxyType({"width": (0.053, 0.144), "thickness": (0.006, 0.014), "depth": (0.028, 0.100)}),
    grip=MappingProxyType({"length": (0.11, 0.25), "radius": (0.0105, 0.0135), "swell": (0.0, 0.08),
                           "flatten": (0.75, 0.90)}),
    grip_segments=(3, 6),
    pommel=MappingProxyType({"radius": (0.0110, 0.0230), "height": (0.010, 0.024)}),
    ratios=MappingProxyType({"blade_width_to_length": (0.031, 0.067), "blade_thickness_to_width": (0.18, 0.30),
                             "guard_width_to_blade_width": (1.9, 3.6), "guard_depth_to_blade_thickness": (2.0, 16.0),
                             "grip_diameter_to_guard_depth": (0.20, 0.98), "pommel_radius_to_grip_radius": (1.05, 1.7),
                             "grip_to_blade_length": (0.12, 0.42)}),
    curved=True,
    total_length=(0.72, 1.20),
)


def draw_params(seed: int) -> BladeWeaponParams:
    blade = draw_blade(derive_stream(seed, STREAM_LABELS["blade"]), length=(0.60, 0.90), base_width=(0.028, 0.040),
                       thickness_ratio=(0.18, 0.30), taper=(0.10, 0.35), distal_taper=(0.20, 0.50),
                       sections=("single_edge",), flat_fraction=(0.35, 0.60), points=POINTS)
    r = derive_stream(seed, STREAM_LABELS["curvature"])
    sagitta = r.uniform(*SAGITTA_RATIO)
    bias = r.uniform(*CURVE_BIAS)
    blade = BladeGeom(**blade, ricasso_length=0.0, ricasso_width_ratio=1.0, sagitta_ratio=sagitta, curve_bias=bias)
    guard = draw_guard(derive_stream(seed, STREAM_LABELS["guard"]), base_width=blade.base_width,
                       shapes=("bar", "tapered", "disc"), width_ratio=(2.4, 3.6), disc_ratio=(1.9, 2.6),
                       thickness=(0.006, 0.014), depth=(0.028, 0.034))
    grip = draw_grip(derive_stream(seed, STREAM_LABELS["grip"]), length=(0.11, 0.25), radius=(0.0105, 0.0135),
                     swell=(0.0, 0.08), flatten=(0.75, 0.90), segments=(3, 6))
    pommel = draw_pommel(derive_stream(seed, STREAM_LABELS["pommel"]), grip_radius=grip.radius,
                         shapes=("cap", "orb"), radius_ratio=(1.05, 1.7), height=(0.016, 0.024),
                         cap_height=(0.010, 0.016), wheel_thickness=(0.010, 0.016))
    return BladeWeaponParams(blade=blade, guard=guard, grip=grip, pommel=pommel)


def generate(seed: int):
    """forge.curved_sword v1. `seed` must already be validated."""
    return build_asset(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION,
                       seed=seed, params=draw_params(seed), rules=RULES)
