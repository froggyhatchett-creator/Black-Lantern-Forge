"""War hammer generator, version 1 (forge.war_hammer v1): a one-handed or hand-and-a-half war hammer.

FROZEN CONTRACT once released: for a given seed this module must keep producing identical
parameters and geometry. A changed draw, bound, constant or vertex order needs a new version.

Components, in order: haft, grip, head, face, rear, butt_cap.
  head      the socket block around the haft's top end, with a collar ring under it
  face      the hammer face: a neck from the socket's front wall flaring into a square,
            octagonal or round face. The face's center vertex is the strike point.
  rear      one of:
              pick    tapering, curving downward
              spike   straight
              poll    a short, narrow blunt block
            Its far end is the secondary strike point.
  butt_cap  a metal cap over the haft's end
This is a hand weapon. Polearm-class hammers (a lucerne hammer) are not made here.

Streams (one per component; every value drawn unconditionally, in this order):
  forge.war_hammer.haft      draw_haft
  forge.war_hammer.grip      draw_grip
  forge.war_hammer.head      eye_height, wall_front, wall_back, wall_side, collar_height, collar_thickness
  forge.war_hammer.face      shape, size, neck_length, neck_ratio, length
  forge.war_hammer.rear      style, length_t, base_t, turn_t
  forge.war_hammer.butt_cap  draw_butt_cap
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType

from forge.errors import GenerationError
from forge.hafted.haft import (
    bore_volume,
    build_butt_cap,
    build_grip,
    build_haft,
    draw_butt_cap,
    draw_grip,
    draw_haft,
    layout,
    top_radii,
)
from forge.hafted.model import ButtCapGeom, GripGeom, HaftedAsset, HaftGeom, Joint, check, check_ranges, require
from forge.hafted.shapes import BACK, FORWARD, bent_sweep, chamfered_rect, eye_block, merge, ring, x_sweep
from forge.prng import derive_stream
from forge.primitives import unit_circle

ASSET_TYPE = "war_hammer"
GENERATOR_ID = "forge.war_hammer"
GENERATOR_VERSION = 1
COMPONENTS = ("haft", "grip", "head", "face", "rear", "butt_cap")
HEAD_PARTS = ("head", "face", "rear")
STREAM_LABELS = MappingProxyType({c: f"forge.war_hammer.{c}" for c in COMPONENTS})
EYE_CHAMFER = 0.24
COLLAR_OVERLAP = 0.003
PICK_SEGMENTS = 5
FACE_PROFILES = MappingProxyType({"square": chamfered_rect(0.12, 0.12), "octagonal": unit_circle(8),
                                  "round": unit_circle(16)})


@dataclass(frozen=True)
class RearStyle:
    length: tuple[float, float]       # beyond the socket's back wall (m)
    base: tuple[float, float]         # base height (m)
    turn: tuple[float, float]         # total downward turn, as a Cayley parameter


REAR_STYLES = MappingProxyType({
    "pick": RearStyle(length=(0.065, 0.120), base=(0.020, 0.030), turn=(0.10, 0.22)),
    "spike": RearStyle(length=(0.040, 0.070), base=(0.018, 0.026), turn=(0.0, 0.0)),
    "poll": RearStyle(length=(0.018, 0.032), base=(0.016, 0.022), turn=(0.0, 0.0)),
})


@dataclass(frozen=True)
class HammerHeadGeom:
    eye_height: float
    wall_front: float
    wall_back: float
    wall_side: float
    collar_height: float
    collar_thickness: float


@dataclass(frozen=True)
class HammerFaceGeom:
    shape: str               # square | octagonal | round
    size: float              # face width or diameter (m)
    neck_length: float       # from the socket's front wall to the flare (m)
    neck_ratio: float        # neck height / face size
    length: float            # face block length (m)


@dataclass(frozen=True)
class HammerRearGeom:
    style: str               # pick | spike | poll
    length: float            # (m)
    base: float              # base height (m)
    turn: float              # total downward turn (Cayley parameter); 0.0 for spike and poll


@dataclass(frozen=True)
class HammerParams:
    haft: HaftGeom
    grip: GripGeom
    head: HammerHeadGeom
    face: HammerFaceGeom
    rear: HammerRearGeom
    butt_cap: ButtCapGeom

    def to_dict(self) -> dict:
        return asdict(self)


RULES = MappingProxyType({
    "haft": MappingProxyType({"length": (0.445, 0.72), "radius": (0.0115, 0.0150), "flatten": (0.80, 0.95),
                              "taper": (0.0, 0.10), "knob": (0.0, 0.0), "butt_margin": (0.010, 0.025),
                              "protrusion": (0.001, 0.004)}),
    "grip": MappingProxyType({"length": (0.10, 0.19), "wrap": (0.0015, 0.0028)}),
    "head": MappingProxyType({"eye_height": (0.042, 0.060), "wall_front": (0.003, 0.006), "wall_back": (0.003, 0.006),
                              "wall_side": (0.004, 0.006), "collar_height": (0.010, 0.022),
                              "collar_thickness": (0.0012, 0.0025)}),
    "face": MappingProxyType({"size": (0.024, 0.040), "neck_length": (0.006, 0.018), "neck_ratio": (0.55, 0.80),
                              "length": (0.014, 0.026)}),
    "butt_cap": MappingProxyType({"radius": (0.014, 0.025), "height": (0.014, 0.024)}),
    "butt_cap_ratio": (1.25, 1.65),
    "face_to_neck": (1.2, 2.2),            # face size / neck height
    "face_to_eye": (0.35, 1.0),            # face size / socket height
    "rear_to_face_reach": (0.15, 3.8),     # rear reach / face reach, both from the haft axis
    "head_length": (0.06, 0.25),           # face to rear tip (m)
    "clearance": (0.06, 1.0),
    "overall": (0.45, 0.95),
    "head_mass": (0.20, 1.20),
    "lever_max": (0.0, 0.70),
})


@dataclass(frozen=True)
class _Layout:
    y_bottom: float
    y_top: float
    grip_lo: float
    grip_hi: float
    eye_bot: float
    eye_top: float
    head_y: float
    x_front: float
    x_back: float
    eye_half_thickness: float
    face_x: float


def _layout(p: HammerParams) -> _Layout:
    h, g, e, f = p.haft, p.grip, p.head, p.face
    y_bottom, y_top, grip_lo, grip_hi = layout(h, g)
    rt, rzt = top_radii(h)
    eye_top = y_top - h.protrusion
    eye_bot = eye_top - e.eye_height
    x_front = rt + e.wall_front
    return _Layout(y_bottom, y_top, grip_lo, grip_hi, eye_bot, eye_top, (eye_bot + eye_top) * 0.5, x_front,
                   0.0 - (rt + e.wall_back), rzt + e.wall_side, x_front + f.neck_length + f.length)


def _neck_thickness(L: _Layout) -> float:
    """The neck and the pick base follow the socket's cheeks: 75% of its usable half-thickness."""
    return 0.75 * L.eye_half_thickness * (1.0 - EYE_CHAMFER)


def validate(p: HammerParams) -> None:
    w, R = ASSET_TYPE, RULES
    h, g, e, f, rr, c = p.haft, p.grip, p.head, p.face, p.rear, p.butt_cap
    check_ranges(w, h, R["haft"], "haft")
    check_ranges(w, g, R["grip"], "grip")
    check_ranges(w, e, R["head"], "head")
    check_ranges(w, f, R["face"], "face")
    check_ranges(w, c, R["butt_cap"], "butt_cap")
    check(w, "butt_cap.radius_to_haft", c.radius / h.radius, R["butt_cap_ratio"])
    if f.shape not in FACE_PROFILES:
        raise GenerationError(f"{w}: face shape {f.shape!r} not in {sorted(FACE_PROFILES)}")
    if rr.style not in REAR_STYLES:
        raise GenerationError(f"{w}: rear style {rr.style!r} not in {sorted(REAR_STYLES)}")
    s = REAR_STYLES[rr.style]
    check(w, "rear.length", rr.length, s.length)
    check(w, "rear.base", rr.base, s.base)
    check(w, "rear.turn", rr.turn, s.turn)
    require(w, e.collar_thickness < 0.9 * e.wall_side, "the collar would stand proud of the socket")
    L = _layout(p)
    neck_h = f.neck_ratio * f.size
    check(w, "face.size_to_neck", f.size / neck_h, R["face_to_neck"])
    check(w, "face.size_to_socket", f.size / e.eye_height, R["face_to_eye"])
    require(w, neck_h * 0.5 <= 0.42 * e.eye_height, "the face's neck is taller than the socket that holds it")
    require(w, rr.base * 0.5 <= 0.42 * e.eye_height, "the rear's base is taller than the socket that holds it")
    rear_reach = (0.0 - L.x_back) + rr.length
    check(w, "rear.reach_to_face_reach", rear_reach / L.face_x, R["rear_to_face_reach"])
    check(w, "head.length", L.face_x + rear_reach, R["head_length"])
    check(w, "clearance", L.eye_bot - e.collar_height - L.grip_hi, R["clearance"])


def validate_assembly(asset: HaftedAsset) -> None:
    w = ASSET_TYPE
    check(w, "overall_length", asset.overall_length, RULES["overall"])
    mass = asset.head_mass_kg
    check(w, "head_mass_kg", mass, RULES["head_mass"])
    check(w, "head_leverage", mass * asset.landmark("head_center")[1], RULES["lever_max"])


def build(*, asset_type: str, generator_id: str, generator_version: int, seed: int,
          params: HammerParams) -> HaftedAsset:
    validate(params)
    h, g, e, f, rr = params.haft, params.grip, params.head, params.face, params.rear
    L = _layout(params)
    rt, rzt = top_radii(h)
    head = merge("head", [
        eye_block("head", L.x_back, L.x_front, L.eye_bot, L.eye_top, L.eye_half_thickness, EYE_CHAMFER),
        ring("head", L.eye_bot - e.collar_height, L.eye_bot + COLLAR_OVERLAP, rt + e.collar_thickness,
             rzt + e.collar_thickness),
    ])
    nh, nt = f.neck_ratio * f.size * 0.5, _neck_thickness(L)
    fh = f.size * 0.5
    x0 = L.x_front - 0.003
    neck_end = L.x_front + f.neck_length
    face, strike_i = x_sweep("face", FACE_PROFILES[f.shape], [
        (x0, nh, nt), (L.x_front + 0.5 * f.neck_length, nh, nt), (neck_end, nh, nt),
        (neck_end + 0.3 * f.length, fh, fh), (L.face_x - 0.1 * f.length, fh, fh), (L.face_x, fh * 0.92, fh * 0.92),
    ], L.head_y, FORWARD)

    base_h, base_t = rr.base * 0.5, _neck_thickness(L)
    start_x = L.x_back + 0.003
    if rr.style == "poll":
        end_x = L.x_back - rr.length
        rear, second_i = x_sweep("rear", chamfered_rect(0.15, 0.15), [
            (start_x, base_h, base_t), (L.x_back - 0.5 * rr.length, base_h, base_t),
            (end_x + 0.0015, base_h * 1.05, base_t * 1.05), (end_x, base_h * 0.95, base_t * 0.95),
        ], L.head_y, BACK)
    else:
        n = PICK_SEGMENTS
        sizes = [(base_h * (1.0 - 0.72 * k / n), base_t * (1.0 - 0.6 * k / n)) for k in range(n + 1)]
        rear, second_i, _ = bent_sweep("rear", unit_circle(4), (start_x, L.head_y), BACK,
                                       (rr.length + 0.003) * 0.88, n, rr.turn / n, sizes, (rr.length + 0.003) * 0.12)

    haft = build_haft(h, g, L.eye_bot, L.eye_top, (L.eye_bot - 0.5 * e.collar_height,))
    grip = build_grip(h, g)
    cap = build_butt_cap(h, g, params.butt_cap)
    margin = 0.1 * e.eye_height
    joints = (
        Joint("haft", "head", "the haft passes through the socket", y_lo=L.eye_bot + margin, y_hi=L.eye_top - margin),
        Joint("haft", "head", "the collar rings the haft", y_lo=L.eye_bot - 0.8 * e.collar_height,
              y_hi=L.eye_bot - 0.2 * e.collar_height),
        Joint("face", "head", "the face's neck is seated in the socket's front wall", x_hi=L.x_front - 0.0005),
        Joint("rear", "head", "the rear's base is seated in the socket's back wall", x_lo=L.x_back + 0.0005),
        Joint("haft", "grip", "the wrap encloses the haft", y_lo=L.grip_lo + 0.1 * g.length,
              y_hi=L.grip_hi - 0.1 * g.length),
        Joint("haft", "butt_cap", "the haft's end sits in the butt cap", y_hi=L.y_bottom + 1e-9),
    )
    landmarks = {
        "eye_bottom": (0.0, L.eye_bot, 0.0),
        "eye_top": (0.0, L.eye_top, 0.0),
        "grip_bottom_center": (0.0, L.grip_lo, 0.0),
        "grip_center": (0.0, 0.0, 0.0),
        "grip_top_center": (0.0, L.grip_hi, 0.0),
        "head_center": (0.0, L.head_y, 0.0),
        "secondary_strike_point": rear.positions[second_i],
        "strike_point": face.positions[strike_i],
        "tip": (0.0, L.y_top, 0.0),
    }
    asset = HaftedAsset(asset_type=asset_type, generator=generator_id, generator_version=generator_version, seed=seed,
                        params=params, components=(haft, grip, head, face, rear, cap),
                        landmarks=tuple(sorted(landmarks.items())), joints=joints, head_components=HEAD_PARTS,
                        head_bore_volume=bore_volume(rt, rzt, e.eye_height + e.collar_height))
    if asset.landmark("tip") not in haft.positions:
        raise GenerationError("the haft's top center is not a haft vertex")
    validate_assembly(asset)
    return asset


# ------------------------------------------------------------------ draws

def _lerp(rng, t: float) -> float:
    return rng[0] + (rng[1] - rng[0]) * t


def draw_params(seed: int) -> HammerParams:
    h = draw_haft(derive_stream(seed, STREAM_LABELS["haft"]), length=(0.445, 0.72), radius=(0.0115, 0.0150),
                  flatten=(0.80, 0.95), taper=(0.0, 0.10), knob=(0.0, 0.0), butt_margin=(0.010, 0.025),
                  protrusion=(0.001, 0.004))
    g = draw_grip(derive_stream(seed, STREAM_LABELS["grip"]), length=(0.10, 0.19), wrap=(0.0015, 0.0028))
    r = derive_stream(seed, STREAM_LABELS["head"])
    head = HammerHeadGeom(eye_height=r.uniform(0.042, 0.060), wall_front=r.uniform(0.003, 0.006),
                          wall_back=r.uniform(0.003, 0.006), wall_side=r.uniform(0.004, 0.006),
                          collar_height=r.uniform(0.010, 0.022), collar_thickness=r.uniform(0.0012, 0.0025))
    r = derive_stream(seed, STREAM_LABELS["face"])
    face = HammerFaceGeom(shape=r.choice(tuple(FACE_PROFILES)), size=r.uniform(0.024, 0.040),
                          neck_length=r.uniform(0.006, 0.018), neck_ratio=r.uniform(0.55, 0.80),
                          length=r.uniform(0.014, 0.026))
    r = derive_stream(seed, STREAM_LABELS["rear"])
    style = r.choice(tuple(REAR_STYLES))
    length_t, base_t, turn_t = r.next_float(), r.next_float(), r.next_float()
    s = REAR_STYLES[style]
    rear = HammerRearGeom(style=style, length=_lerp(s.length, length_t), base=_lerp(s.base, base_t),
                          turn=_lerp(s.turn, turn_t))
    cap = draw_butt_cap(derive_stream(seed, STREAM_LABELS["butt_cap"]), haft_radius=h.radius,
                        shapes=("knob", "disc", "cone"), radius_ratio=(1.25, 1.65), height=(0.014, 0.024))
    return HammerParams(haft=h, grip=g, head=head, face=face, rear=rear, butt_cap=cap)


def generate(seed: int):
    """forge.war_hammer v1. `seed` must already be validated."""
    return build(asset_type=ASSET_TYPE, generator_id=GENERATOR_ID, generator_version=GENERATOR_VERSION, seed=seed,
                 params=draw_params(seed))
