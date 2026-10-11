"""Two-hand axe generator, version 1 (forge.two_hand_axe v1): a long-hafted, two-handed axe.

FROZEN CONTRACT once released: for a given seed this module must keep producing identical
parameters and geometry. A changed draw, bound, constant or vertex order needs a new version.

The head is drawn on its own ranges, not scaled from the haft. A longer haft never makes a
bigger head, and the rules cap the head's length relative to the haft.

Head styles (broad shapes, not named historical presets):
  broad      a wide, thin, flaring bit on a narrow neck
  bearded    a long beard under a taller neck
  crescent   a deep, strongly curved edge with horn and beard
Polls: flat, or a short rear spike.

The grip zone at the origin is the lower (rear) hand. The upper hand's zone sits below the
head, recorded as landmarks, with a minimum spacing between the two.

Streams (one per component; draw orders in forge/hafted/haft.py and axe.py):
  forge.two_hand_axe.haft   draw_haft
  forge.two_hand_axe.grip   draw_grip, then upper_grip, throat_gap
  forge.two_hand_axe.head   draw_head  (style, eye, walls, poll, collar)
  forge.two_hand_axe.bit    draw_bit
"""

from __future__ import annotations

from types import MappingProxyType

from forge.hafted.axe import AxeParams, AxeRules, AxeStyle, build, draw_bit, draw_head
from forge.hafted.haft import draw_grip, draw_haft
from forge.prng import derive_stream

ASSET_TYPE = "two_hand_axe"
GENERATOR_ID = "forge.two_hand_axe"
GENERATOR_VERSION = 1
STREAM_LABELS = MappingProxyType({c: f"forge.two_hand_axe.{c}" for c in ("haft", "grip", "head", "bit")})

STYLES = MappingProxyType({
    "broad": AxeStyle(eye_height=(0.056, 0.072), neck_ratio=(0.40, 0.52), horn=(0.026, 0.046),
                      beard=(0.055, 0.085), projection=(0.150, 0.200), bulge_ratio=(0.08, 0.16),
                      poll_length=(0.008, 0.016), poll_reach=(0.030, 0.050), poll_size=(0.018, 0.026)),
    "bearded": AxeStyle(eye_height=(0.056, 0.072), neck_ratio=(0.52, 0.68), horn=(0.008, 0.020),
                        beard=(0.060, 0.090), projection=(0.140, 0.185), bulge_ratio=(0.05, 0.12),
                        poll_length=(0.008, 0.016), poll_reach=(0.030, 0.050), poll_size=(0.018, 0.026)),
    "crescent": AxeStyle(eye_height=(0.055, 0.070), neck_ratio=(0.40, 0.52), horn=(0.045, 0.068),
                         beard=(0.050, 0.075), projection=(0.145, 0.195), bulge_ratio=(0.13, 0.22),
                         poll_length=(0.008, 0.016), poll_reach=(0.030, 0.050), poll_size=(0.018, 0.026)),
})

RULES = AxeRules(
    asset_type=ASSET_TYPE, hands=("two",), styles=STYLES, polls=("flat", "spike"),
    haft=MappingProxyType({"length": (0.86, 1.42), "radius": (0.0135, 0.0165), "flatten": (0.70, 0.82),
                           "taper": (0.0, 0.08), "knob": (0.08, 0.22), "butt_margin": (0.030, 0.070),
                           "protrusion": (0.001, 0.005)}),
    grip=MappingProxyType({"length": (0.14, 0.22), "wrap": (0.0018, 0.0030)}),
    head=MappingProxyType({"wall_front": (0.003, 0.006), "wall_side": (0.004, 0.006),
                           "collar_height": (0.0, 0.018), "collar_thickness": (0.0, 0.0025)}),
    bit=MappingProxyType({"thickness_ratio": (0.24, 0.42), "bevel_x": (0.70, 0.85), "bevel_z": (0.15, 0.28)}),
    edge_height=(0.095, 0.240),
    head_length=(0.15, 0.30),
    head_to_haft=(0.10, 0.32),
    projection_to_thickness=(2.6, 9.5),
    clearance=0.10,
    overall=(0.85, 1.60),
    head_mass=(0.40, 2.00),
    mass_per_haft_area=(300.0, 3400.0),
    lever_max=2.5,
    upper_grip=(0.14, 0.22),
    throat_gap=(0.04, 0.10),
    hand_spacing=0.12,
)


def _poll_for(style: str, drawn: str) -> str:
    return drawn


def draw_params(seed: int) -> AxeParams:
    h = draw_haft(derive_stream(seed, STREAM_LABELS["haft"]), length=(0.86, 1.42), radius=(0.0135, 0.0165),
                  flatten=(0.70, 0.82), taper=(0.0, 0.08), knob=(0.08, 0.22), butt_margin=(0.030, 0.070),
                  protrusion=(0.001, 0.005))
    r = derive_stream(seed, STREAM_LABELS["grip"])
    g = draw_grip(r, length=(0.14, 0.22), wrap=(0.0018, 0.0030))
    upper = r.uniform(0.14, 0.22)
    gap = r.uniform(0.04, 0.10)
    head = draw_head(derive_stream(seed, STREAM_LABELS["head"]), RULES, wall_front=(0.003, 0.006),
                     wall_side=(0.004, 0.006), collar_height=(0.010, 0.018), collar_thickness=(0.0012, 0.0025),
                     poll_for=_poll_for)
    bit = draw_bit(derive_stream(seed, STREAM_LABELS["bit"]), RULES, head, thickness_ratio=(0.24, 0.42),
                   bevel_x=(0.70, 0.85), bevel_z=(0.15, 0.28))
    return AxeParams(haft=h, grip=g, head=head, bit=bit, upper_grip=upper, throat_gap=gap)


def generate(seed: int):
    """forge.two_hand_axe v1. `seed` must already be validated."""
    return build(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION, seed=seed,
                 params=draw_params(seed), rules=RULES)
