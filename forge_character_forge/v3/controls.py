"""The 53 Character Studio controls on the v3 (MakeHuman hm08) foundation.

Every control keeps its v2 name, default and studio range, so Character DNA stays comparable across generators.
Each one maps to MakeHuman CC0 targets on its high and low side (weights applied when the slider reaches that end)
or to an exact transform. Quality labels:

- ``direct``: the targets model what the control names.
- ``approximate``: the nearest available targets; the shape differs from the control's meaning (noted).
- ``derived``: no MakeHuman target exists; built from other targets (noted).

No control is dropped or silently substituted; tests check that all 53 are present and labelled.
"""

from __future__ import annotations

FEM = "macrodetails/caucasian-female-young.target"
MALE = "macrodetails/caucasian-male-young.target"
U = "macrodetails/universal-{}-young-{}.target"
CUP = "breast/female-young-averagemuscle-averageweight-{}cup-averagefirmness.target"
FIRM = "breast/female-young-averagemuscle-averageweight-averagecup-{}firmness.target"


def _lr(path: str, w: float = 1.0) -> list[tuple[str, float]]:
    """A target that exists per side (``{s}`` = l / r)."""
    return [(path.format(s=s), w) for s in ("l", "r")]


def _avg_sexes(kind: str) -> list[tuple[str, float]]:
    """Universal weight/muscle targets exist per sex; the neutral basis averages them."""
    return [(U.format("female", kind), 0.5), (U.format("male", kind), 0.5)]


def _pair(name: str, hi: str = "incr", lo: str = "decr", w: float = 1.0, lr: bool = False):
    group = name.split("/")[0]
    stem = name.split("/")[1]
    mk = (lambda suf: _lr(f"{group}/{{s}}-{stem}-{suf}.target", w)) if lr else (lambda suf: [(f"{group}/{stem}-{suf}.target", w)])
    return mk(hi), mk(lo)


def _merge(*pairs):
    hi, lo = [], []
    for h, l in pairs:
        hi += h
        lo += l
    return hi, lo


# key -> (quality, hi targets, lo targets, note); "scale" marks the exact uniform-scale control
CONTROLS: dict[str, tuple] = {}


def _c(key, quality, pair, note=""):
    CONTROLS[key] = (quality, pair[0], pair[1], note)


_c("body.height_m", "direct", ("scale", "scale"), "exact uniform scale about the floor; v3 neutral is scaled to the 1.75 m default")
_c("body.femininity", "direct", ([(FEM, 0.5), (MALE, -0.5)], [(MALE, 0.5), (FEM, -0.5)]),
   "neutral = base + 0.5 female + 0.5 male macro; ends are the pure macros")
_c("body.body_fat", "approximate", (_avg_sexes("averagemuscle-maxweight"), _avg_sexes("averagemuscle-minweight")),
   "MakeHuman weight = fat and mass together; female/male targets averaged")
_c("body.muscle", "direct", (_avg_sexes("maxmuscle-averageweight"), _avg_sexes("minmuscle-averageweight")),
   "female/male targets averaged")
_c("body.shoulder_width", "approximate", _pair("torso/torso-vshape"), "V-shape: shoulders and lats, not the shoulder joints")
_c("body.chest_width", "approximate", _pair("torso/torso-scale-horiz"), "scales the whole torso width")
_c("body.chest_depth", "approximate", _pair("torso/torso-scale-depth"), "scales the whole torso depth")
_c("body.waist_width", "approximate", _pair("torso/torso-scale-horiz", w=0.5), "no isolated waist target: half torso width")
_c("body.hip_width", "direct", _pair("hip/hip-scale-horiz"))
_c("body.glute_size", "direct", _pair("buttocks/buttocks-volume"))
_c("body.belly", "approximate", _pair("stomach/stomach-pregnant"), "pregnancy-shaped belly, not abdominal fat")
_c("body.torso_length", "direct", _pair("torso/torso-scale-vert"))
_c("body.neck_length", "direct", _pair("neck/neck-scale-vert"))
_c("body.neck_thickness", "direct", _merge(_pair("neck/neck-scale-horiz"), _pair("neck/neck-scale-depth")))
_c("body.arm_length", "direct", _merge(_pair("armslegs/upperarm-scale-vert", lr=True), _pair("armslegs/lowerarm-scale-vert", lr=True)))
_c("body.arm_thickness", "direct", _merge(*[_pair(f"armslegs/{p}-scale-{a}", lr=True) for p in ("upperarm", "lowerarm") for a in ("horiz", "depth")]))
_c("body.leg_length", "direct", _merge(_pair("armslegs/upperleg-scale-vert", lr=True), _pair("armslegs/lowerlegs-height", lr=False)),
   "upper legs per side; lower legs use the both-sides height target")
_c("body.thigh_thickness", "direct", _merge(*[_pair(f"armslegs/upperleg-scale-{a}", lr=True) for a in ("horiz", "depth")]))
_c("body.calf_thickness", "direct", _merge(*[_pair(f"armslegs/lowerleg-scale-{a}", lr=True) for a in ("horiz", "depth")]))
_c("body.hand_size", "direct", _pair("armslegs/hand-scale", lr=True))
_c("body.foot_size", "direct", _pair("armslegs/foot-scale", lr=True))
_c("body.head_size", "direct", _merge(*[_pair(f"head/head-scale-{a}") for a in ("horiz", "vert", "depth")]))
_c("body.breast_size", "direct", ([(CUP.format("max"), 1.0)], [(CUP.format("min"), 1.0)]),
   "cup targets of the average-weight young female set; the low side is unused (default = minimum)")
_c("body.breast_spacing", "direct", _pair("breast/breast-dist"))
_c("body.breast_height", "direct", _pair("breast/breast-trans", hi="up", lo="down"))
_c("body.breast_projection", "approximate", _pair("breast/breast-point"), "nipple-point projection, not volume")
_c("body.breast_sag", "direct", ([(FIRM.format("min"), 1.0)], [(FIRM.format("max"), 1.0)]), "inverse of MakeHuman firmness")
_c("face.face_width", "approximate", _pair("head/head-scale-horiz", w=0.6), "whole head width, not the face only")
_c("face.face_length", "approximate", _merge(_pair("chin/chin-height"), _pair("head/head-scale-vert", w=0.5)),
   "chin height plus half the head height (lengthens the cranium too)")
_c("face.jaw_width", "approximate", _pair("chin/chin-bones"), "jaw bones (mandible width)")
_c("face.jaw_angle", "approximate", ([("head/head-square.target", 1.0)], [("head/head-oval.target", 1.0)]),
   "whole-head square / oval shapes")
_c("face.chin_width", "direct", _pair("chin/chin-width"))
_c("face.chin_length", "direct", _pair("chin/chin-height"))
_c("face.chin_projection", "direct", _pair("chin/chin-prominent"))
_c("face.cheekbone_width", "direct", _pair("cheek/cheek-bones", lr=True))
_c("face.cheekbone_height", "direct", _pair("cheek/cheek-trans", hi="up", lo="down", lr=True))
_c("face.cheek_fullness", "direct", _pair("cheek/cheek-volume", lr=True))
_c("face.asymmetry", "derived", ([("cheek/l-cheek-bones-incr.target", 0.4), ("cheek/r-cheek-bones-decr.target", 0.4),
                                   ("eyes/l-eye-corner1-up.target", 0.3), ("ears/r-ear-scale-incr.target", 0.3)], []),
   "no MakeHuman asymmetry target: unequal left/right targets; one side only (default = minimum)")
_c("face.nose_length", "direct", _pair("nose/nose-scale-vert"))
_c("face.nose_width", "direct", _pair("nose/nose-scale-horiz"))
_c("face.nose_bridge", "approximate", _pair("nose/nose-greek"), "Greek (straight high) bridge")
_c("face.nose_tip", "approximate", _pair("nose/nose-point-width"), "tip width only")
_c("face.nose_upturn", "direct", _pair("nose/nose-point", hi="up", lo="down"))
_c("face.brow_height", "direct", _pair("eyebrows/eyebrows-trans", hi="up", lo="down"))
_c("face.brow_prominence", "approximate", _pair("eyebrows/eyebrows-trans", hi="forward", lo="backward"), "moves the brow forward, no ridge shape")
_c("face.eye_size", "direct", _pair("eyes/eye-scale", lr=True))
_c("face.eye_spacing", "direct", _pair("eyes/eye-trans", hi="out", lo="in", lr=True))
_c("face.eye_tilt", "approximate", _pair("eyes/eye-corner1", hi="up", lo="down", lr=True), "one eye corner raised or lowered")
_c("face.lip_upper", "direct", _pair("mouth/mouth-upperlip-volume"))
_c("face.lip_lower", "direct", _pair("mouth/mouth-lowerlip-volume"))
_c("face.mouth_width", "direct", _pair("mouth/mouth-scale-horiz"))
_c("face.ear_size", "direct", _pair("ears/ear-scale", lr=True))
_c("face.ear_protrusion", "approximate", _pair("ears/ear-wing", lr=True), "ear wing (cup) rather than rotation")

# the neutral v3 base: hm08 + half of each sex macro; scaled to this height
NEUTRAL = [(FEM, 0.5), (MALE, 0.5)]


def required_targets() -> list[str]:
    out = {r for r, _ in NEUTRAL}
    for _, hi, lo, _ in CONTROLS.values():
        for side in (hi, lo):
            if side != "scale":
                out.update(r for r, _ in side)
    return sorted(out)


def summary() -> dict:
    q: dict[str, int] = {}
    for quality, *_ in CONTROLS.values():
        q[quality] = q.get(quality, 0) + 1
    return {"controls": len(CONTROLS), "by_quality": q}
