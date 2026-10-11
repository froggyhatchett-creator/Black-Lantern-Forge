"""One-hand axe generator, version 1 (forge.one_hand_axe v1): a compact one-handed chopping axe.

FROZEN CONTRACT once released: for a given seed this module must keep producing identical
parameters and geometry. A changed draw, bound, constant or vertex order needs a new version.

Head styles (broad shapes, not named historical presets):
  compact_bearded  moderate beard, small horn
  crescent         tall edge; the bit sweeps both up (horn) and down (beard)
  broad_utility    tall neck, little beard, longer flat poll
  narrow_battle    narrow neck, small flare, long reach, thin
  hammer_poll      a squared hammer face behind the eye

Streams (one per component; draw orders in forge/hafted/haft.py and axe.py):
  forge.one_hand_axe.haft   draw_haft
  forge.one_hand_axe.grip   draw_grip
  forge.one_hand_axe.head   draw_head  (style, eye, walls, poll, collar)
  forge.one_hand_axe.bit    draw_bit
"""

from __future__ import annotations

from types import MappingProxyType

from forge.hafted.axe import AxeParams, AxeRules, AxeStyle, build, draw_bit, draw_head
from forge.hafted.haft import draw_grip, draw_haft
from forge.prng import derive_stream

ASSET_TYPE = "one_hand_axe"
GENERATOR_ID = "forge.one_hand_axe"
GENERATOR_VERSION = 1
STREAM_LABELS = MappingProxyType({c: f"forge.one_hand_axe.{c}" for c in ("haft", "grip", "head", "bit")})

_NONE = (0.0, 0.0)
STYLES = MappingProxyType({
    "compact_bearded": AxeStyle(eye_height=(0.050, 0.064), neck_ratio=(0.55, 0.72), horn=(0.002, 0.010),
                                beard=(0.030, 0.052), projection=(0.095, 0.128), bulge_ratio=(0.06, 0.14),
                                poll_length=(0.007, 0.014), poll_reach=_NONE, poll_size=_NONE),
    "crescent": AxeStyle(eye_height=(0.050, 0.064), neck_ratio=(0.45, 0.60), horn=(0.026, 0.042),
                         beard=(0.032, 0.050), projection=(0.105, 0.138), bulge_ratio=(0.10, 0.20),
                         poll_length=(0.006, 0.012), poll_reach=_NONE, poll_size=_NONE),
    "broad_utility": AxeStyle(eye_height=(0.055, 0.070), neck_ratio=(0.66, 0.78), horn=(0.006, 0.016),
                              beard=(0.010, 0.024), projection=(0.095, 0.122), bulge_ratio=(0.04, 0.10),
                              poll_length=(0.012, 0.022), poll_reach=_NONE, poll_size=_NONE),
    "narrow_battle": AxeStyle(eye_height=(0.045, 0.058), neck_ratio=(0.42, 0.55), horn=(0.010, 0.020),
                              beard=(0.012, 0.024), projection=(0.115, 0.148), bulge_ratio=(0.04, 0.10),
                              poll_length=(0.006, 0.010), poll_reach=_NONE, poll_size=_NONE),
    "hammer_poll": AxeStyle(eye_height=(0.050, 0.064), neck_ratio=(0.55, 0.70), horn=(0.004, 0.012),
                            beard=(0.018, 0.034), projection=(0.095, 0.124), bulge_ratio=(0.05, 0.12),
                            poll_length=(0.004, 0.008), poll_reach=(0.018, 0.030), poll_size=(0.020, 0.028)),
})

RULES = AxeRules(
    asset_type=ASSET_TYPE, hands=("one",), styles=STYLES, polls=("flat", "hammer"),
    haft=MappingProxyType({"length": (0.355, 0.70), "radius": (0.0115, 0.0150), "flatten": (0.72, 0.86),
                           "taper": (0.0, 0.12), "knob": (0.10, 0.28), "butt_margin": (0.014, 0.032),
                           "protrusion": (0.001, 0.005)}),
    grip=MappingProxyType({"length": (0.09, 0.13), "wrap": (0.0015, 0.0028)}),
    head=MappingProxyType({"wall_front": (0.003, 0.006), "wall_side": (0.004, 0.006),
                           "collar_height": (0.0, 0.016), "collar_thickness": (0.0, 0.0025)}),
    bit=MappingProxyType({"thickness_ratio": (0.35, 0.60), "bevel_x": (0.70, 0.85), "bevel_z": (0.15, 0.28)}),
    edge_height=(0.040, 0.150),
    head_length=(0.10, 0.18),
    head_to_haft=(0.15, 0.50),
    projection_to_thickness=(1.8, 6.5),
    clearance=0.05,
    overall=(0.35, 0.80),
    head_mass=(0.20, 1.40),
    mass_per_haft_area=(300.0, 3000.0),
    lever_max=0.70,
)


def _poll_for(style: str, drawn: str) -> str:
    return "hammer" if style == "hammer_poll" else "flat"


def draw_params(seed: int) -> AxeParams:
    h = draw_haft(derive_stream(seed, STREAM_LABELS["haft"]), length=(0.355, 0.70), radius=(0.0115, 0.0150),
                  flatten=(0.72, 0.86), taper=(0.0, 0.12), knob=(0.10, 0.28), butt_margin=(0.014, 0.032),
                  protrusion=(0.001, 0.005))
    g = draw_grip(derive_stream(seed, STREAM_LABELS["grip"]), length=(0.09, 0.13), wrap=(0.0015, 0.0028))
    head = draw_head(derive_stream(seed, STREAM_LABELS["head"]), RULES, wall_front=(0.003, 0.006),
                     wall_side=(0.004, 0.006), collar_height=(0.008, 0.016), collar_thickness=(0.0012, 0.0025),
                     poll_for=_poll_for)
    bit = draw_bit(derive_stream(seed, STREAM_LABELS["bit"]), RULES, head, thickness_ratio=(0.35, 0.60),
                   bevel_x=(0.70, 0.85), bevel_z=(0.15, 0.28))
    return AxeParams(haft=h, grip=g, head=head, bit=bit)


def generate(seed: int):
    """forge.one_hand_axe v1. `seed` must already be validated."""
    return build(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION, seed=seed,
                 params=draw_params(seed), rules=RULES)
