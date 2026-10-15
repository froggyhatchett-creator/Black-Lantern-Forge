"""Anatomical body field: the smooth CSG of primitives that defines the skin surface.

All body dimensions are meters for a 1.75 m reference adult, scaled by
``u = height / 1.75``; the head is meters for a 0.23 m reference head height,
scaled by ``k = head_h / 0.23``.  Reference values follow common adult
anthropometric averages (shoulder/hip breadths, head length and breadth,
interpupillary distance, nose and mouth widths).  Every primitive is tagged with
the bone that owns it so skin weights can be derived from the same field.
"""

from __future__ import annotations

import math

import numpy as np

from forge_character_forge.params import BodyParams, FaceParams
from forge_character_forge.sdf import Ellipsoid, Field, RoundBox, RoundCone, rot_xyz
from forge_character_forge.skeleton import FINGERS, FINGER_RADIUS, Skeleton, hand_frame


def _v(*a):
    return np.array(a, dtype=float)


def _asym(face: FaceParams, side: float, k: float) -> float:
    """Deterministic left/right variation: left gets +k*asymmetry, right -k*asymmetry."""
    return 1.0 + side * k * face.asymmetry


def _lerp(a, b, t):
    return a + (b - a) * t


def build_field(body: BodyParams, face: FaceParams, skel: Skeleton, *, nipples: bool = True) -> Field:
    F = Field()
    m = skel.marks
    u = m["height"] / 1.75
    yh = m["y_hip"]
    fem = body.femininity
    fat = body.body_fat
    mus = body.muscle
    gf = 0.88 + 0.34 * fat           # fat girth factor
    gm = 0.90 + 0.25 * mus           # muscle girth factor
    J = skel.__getitem__
    hipw, waist, cw, cd = body.hip_width, body.waist_width, body.chest_width, body.chest_depth
    ty = m["torso_len"] / (0.31 * 1.75 * u)  # torso length multiplier for vertical placements

    # ------------------------------------------------------------------ pelvis
    F.add(Ellipsoid("pelvis", 0.05 * u, center=(0, yh + 0.045 * u, -0.01 * u),
                    radii=(_lerp(0.132, 0.146, fem) * u * hipw * gf ** 0.5, 0.10 * u, 0.098 * u * gf ** 0.6)))
    F.add(Ellipsoid("pelvis", 0.04 * u, center=(0, yh + 0.04 * u, 0.035 * u),
                    radii=(0.10 * u * hipw, 0.075 * u, 0.065 * u * gf)))
    for side in (1.0, -1.0):
        g = body.glute_size * _lerp(0.95, 1.12, fem) * gf ** 0.6
        F.add(Ellipsoid("pelvis", 0.04 * u, center=(side * 0.056 * u * hipw, yh - 0.018 * u, -0.058 * u),
                        radii=(0.074 * u * g ** 0.8, 0.088 * u * g ** 0.5, 0.064 * u * g)))
        F.add(Ellipsoid("pelvis", 0.06 * u, center=(side * _lerp(0.094, 0.100, fem) * u * hipw, yh - 0.03 * u, -0.008 * u),
                        radii=(_lerp(0.046, 0.058, fem) * u * gf ** 0.7, 0.095 * u, 0.072 * u * gf ** 0.5)))

    # ------------------------------------------------------------------ abdomen / waist
    F.add(Ellipsoid("spine_01", 0.06 * u, center=(0, yh + 0.19 * u * ty, 0.002 * u),
                    radii=(_lerp(0.135, 0.118, fem) * u * waist * gf ** 1.2, 0.13 * u * ty, 0.096 * u * gf ** 1.2)))
    belly = body.belly
    F.add(Ellipsoid("spine_01", 0.06 * u, center=(0, yh + 0.13 * u * ty, (0.035 + 0.035 * belly) * u),
                    radii=(0.105 * u * waist * gf, (0.10 + 0.03 * belly) * u * ty, (0.06 + 0.06 * belly + 0.025 * fat) * u)))
    for side in (1.0, -1.0):
        F.add(Ellipsoid("spine_01", 0.05 * u, center=(side * 0.10 * u * waist, yh + 0.12 * u * ty, -0.005 * u),
                        radii=((0.035 + 0.035 * fat) * u, 0.075 * u * ty, 0.07 * u * gf)))

    # ------------------------------------------------------------------ ribcage / chest / back
    F.add(Ellipsoid("spine_02", 0.06 * u, center=(0, yh + 0.36 * u * ty, -0.012 * u),
                    radii=(_lerp(0.145, 0.128, fem) * u * cw * gf ** 0.4, 0.175 * u * ty, 0.107 * u * cd * gf ** 0.4)))
    F.add(Ellipsoid("spine_03", 0.06 * u, center=(0, yh + 0.445 * u * ty, -0.02 * u),
                    radii=(_lerp(0.150, 0.130, fem) * u * cw, 0.095 * u * ty, 0.098 * u * cd)))
    F.add(Ellipsoid("spine_03", 0.05 * u, center=(0, m["y_neck_base"] - 0.045 * u, -0.055 * u),
                    radii=(0.085 * u * gm, 0.055 * u, 0.048 * u)))  # trapezius
    neck_r = _lerp(0.060, 0.050, fem) * u * body.neck_thickness * gm ** 0.5
    for side, lab in ((1.0, "l"), (-1.0, "r")):
        sh = J(f"upperarm_{lab}")
        F.add(RoundCone(f"clavicle_{lab}", 0.04 * u, a=(side * 0.03 * u, m["y_neck_base"] - 0.025 * u, -0.025 * u),
                        b=tuple(sh + _v(-side * 0.012 * u, 0.014 * u, -0.008 * u)),
                        ra=0.034 * u * gm, rb=0.032 * u * gm, squash=(1.0, 0.85)))
        pec = mus * (1.0 - 0.7 * fem)
        F.add(Ellipsoid("spine_03", 0.045 * u, center=(side * 0.066 * u * cw, yh + 0.445 * u * ty, 0.062 * u * cd),
                        radii=(0.082 * u * cw, (0.048 + 0.006 * pec) * u, (0.016 + 0.016 * pec) * u),
                        rot=rot_xyz(0.25, 0, -side * 0.18)))
        F.add(Ellipsoid("spine_02", 0.05 * u, center=(side * _lerp(0.112, 0.102, fem) * u * cw, yh + 0.37 * u * ty, -0.035 * u),
                        radii=((0.03 + 0.022 * mus) * u, 0.11 * u * ty, 0.055 * u)))  # latissimus
        bs = body.breast_size
        if bs > 0.02:
            bj = J(f"breast_{lab}")
            vol = bs ** (1.0 / 3.0)
            proj = body.breast_projection
            sag = body.breast_sag * min(bs, 2.0)
            r = _v(0.060 * vol, 0.056 * vol, 0.05 * vol * proj) * u
            brot = rot_xyz(0.3 * sag, side * 0.22, 0.0)
            c = bj + _v(side * 0.006 * u, -(0.008 + 0.02 * sag) * u * vol, r[2] * 0.15)
            F.add(Ellipsoid(f"breast_{lab}", 0.045 * u, center=tuple(c), radii=tuple(r), rot=brot, tag="breast"))
            F.add(Ellipsoid(f"breast_{lab}", 0.04 * u, center=tuple(c + _v(-side * 0.01 * u, -0.012 * u * vol, -0.01 * u)),
                            radii=tuple(r * _v(0.95, 0.8, 0.85)), rot=brot, tag="breast_lower"))
            tip = c + brot @ _v(0, 0, r[2] * 0.97) + _v(0, -0.004 * u * sag, 0)
        else:
            pecz = (0.06 * cd + 0.024 + 0.02 * mus * (1 - 0.7 * fem)) * u
            tip = _v(side * 0.072 * u * cw, yh + 0.425 * u * ty, pecz + 0.004 * u)
        m[f"nipple_{lab}"] = tip
        if nipples and body.nipple_size > 0.01:
            nr = 0.0045 * u * body.nipple_size
            F.add(Ellipsoid(f"breast_{lab}" if bs > 0.02 else "spine_03", 0.003 * u,
                            center=tuple(tip), radii=(nr, nr, nr * 0.9), tag="nipple"))

    # -------------------------------------------------------------------- neck
    F.add(RoundCone("neck_01", 0.03 * u, a=(0, m["y_neck_base"] - 0.03 * u, -0.02 * u),
                    b=(0, m["y_chin"] + 0.045 * u, -0.036 * u), ra=neck_r * 1.1, rb=neck_r,
                    squash=(1.0, 0.95)))

    # -------------------------------------------------------------------- arms
    at = body.arm_thickness
    for side, lab in ((1.0, "l"), (-1.0, "r")):
        sh, el, wr = J(f"upperarm_{lab}"), J(f"lowerarm_{lab}"), J(f"hand_{lab}")
        d_up = (el - sh) / np.linalg.norm(el - sh)
        arm_rot = rot_xyz(0, 0, side * math.radians(48))
        F.add(Ellipsoid(f"upperarm_{lab}", 0.035 * u,
                        center=tuple(sh + d_up * 0.035 * u + _v(side * 0.008 * u, 0.0, 0.0)),
                        radii=(0.046 * u * gm, 0.07 * u, 0.05 * u * gm), rot=arm_rot, tag="deltoid"))
        F.add(RoundCone(f"upperarm_{lab}", 0.03 * u, a=tuple(sh), b=tuple(el), ra=0.045 * u * at * gf ** 0.6,
                        rb=0.035 * u * at, hint=(0, 0, 1)))
        F.add(Ellipsoid(f"upperarm_{lab}", 0.03 * u, center=tuple(sh + (el - sh) * 0.55 + _v(0, 0, 0.014 * u)),
                        radii=((0.022 + 0.01 * mus) * u * at, 0.065 * u, (0.022 + 0.012 * mus) * u * at),
                        rot=arm_rot, tag="biceps"))
        F.add(Ellipsoid(f"upperarm_{lab}", 0.03 * u, center=tuple(sh + (el - sh) * 0.42 + _v(0, 0, -0.016 * u)),
                        radii=((0.024 + 0.008 * mus) * u * at, 0.075 * u, (0.022 + 0.008 * mus) * u * at),
                        rot=arm_rot, tag="triceps"))
        F.add(RoundCone(f"lowerarm_{lab}", 0.025 * u, a=tuple(el), b=tuple(wr), ra=0.037 * u * at * gm ** 0.5,
                        rb=0.026 * u * at, squash=(1.0, 0.72), hint=(0, 0, 1)))
        F.add(Ellipsoid(f"lowerarm_{lab}", 0.03 * u, center=tuple(el + (wr - el) * 0.27),
                        radii=((0.027 + 0.006 * mus) * u, 0.065 * u, (0.03 + 0.006 * mus) * u),
                        rot=arm_rot, tag="forearm"))
        _hand(F, skel, side, lab)

    # -------------------------------------------------------------------- legs
    th, ca = body.thigh_thickness, body.calf_thickness
    for side, lab in ((1.0, "l"), (-1.0, "r")):
        hp, kn, an = J(f"thigh_{lab}"), J(f"calf_{lab}"), J(f"foot_{lab}")
        F.add(RoundCone(f"thigh_{lab}", 0.05 * u, a=tuple(hp + _v(side * 0.008 * u, -0.02 * u, -0.006 * u)), b=tuple(kn),
                        ra=_lerp(0.088, 0.092, fem) * u * th * gf ** 0.7, rb=0.046 * u * th))
        F.add(Ellipsoid(f"thigh_{lab}", 0.04 * u, center=tuple(hp + (kn - hp) * 0.5 + _v(0, 0, 0.03 * u)),
                        radii=((0.045 + 0.01 * mus) * u * th, 0.14 * u, (0.036 + 0.012 * mus) * u * th),
                        tag="quadriceps"))
        F.add(Ellipsoid(f"thigh_{lab}", 0.04 * u, center=tuple(hp + (kn - hp) * 0.3 + _v(-side * 0.035 * u, 0, 0.0)),
                        radii=((0.035 + 0.02 * fat * fem + 0.01 * fat) * u * th, 0.11 * u, 0.05 * u * th),
                        tag="inner_thigh"))
        F.add(Ellipsoid(f"calf_{lab}", 0.02 * u, center=tuple(kn + _v(0, 0.005 * u, 0.036 * u)),
                        radii=(0.022 * u, 0.024 * u, 0.012 * u), tag="patella"))
        F.add(RoundCone(f"calf_{lab}", 0.04 * u, a=tuple(kn), b=tuple(an + _v(0, 0.01 * u, 0)), ra=0.043 * u * ca,
                        rb=0.03 * u * ca))
        F.add(Ellipsoid(f"calf_{lab}", 0.04 * u, center=tuple(kn + (an - kn) * 0.27 + _v(0, 0, -0.024 * u)),
                        radii=((0.042 + 0.006 * mus) * u * ca, 0.10 * u, (0.04 + 0.008 * mus) * u * ca),
                        tag="gastrocnemius"))
        _foot(F, skel, side, lab, body, u)

    _head(F, skel, face)
    F.clip_planes.append(((0.0, 0.0015 * u, 0.0), (0.0, 1.0, 0.0)))  # flat soles
    return F


def _foot(F, skel, side, lab, body, u):
    an, ball = skel[f"foot_{lab}"], skel[f"ball_{lab}"]
    fs = body.foot_size
    fwd = ball - an
    fwd[1] = 0.0
    yaw = math.atan2(fwd[0], fwd[2])
    Ry = rot_xyz(0, yaw, 0)

    def at(x, y, z):  # foot-local (x lateral toward the outside, y up, z forward) -> world, ground at y=0
        q = Ry @ _v(side * x * u, 0.0, z * u * fs)
        return an * _v(1, 0, 1) + q + _v(0, y * u, 0)

    heel = at(-0.002, 0.034, -0.046)
    F.add(Ellipsoid(f"foot_{lab}", 0.02 * u, center=tuple(heel), radii=(0.031 * u, 0.036 * u, 0.04 * u * fs)))
    F.add(Ellipsoid(f"foot_{lab}", 0.03 * u, center=tuple(at(0.004, 0.038, 0.04)), radii=(0.038 * u, 0.034 * u, 0.08 * u * fs),
                    rot=Ry @ rot_xyz(0.32, 0, 0), tag="instep"))
    F.add(Ellipsoid(f"foot_{lab}", 0.025 * u, center=tuple(at(0.010, 0.018, 0.085)), radii=(0.045 * u, 0.022 * u, 0.06 * u * fs),
                    rot=Ry, tag="sole"))
    F.add(Ellipsoid(f"ball_{lab}", 0.02 * u, center=tuple(at(0.006, 0.02, 0.145)), radii=(0.048 * u, 0.02 * u, 0.035 * u * fs),
                    rot=Ry, tag="ball"))
    F.add(RoundCone(f"ball_{lab}", 0.012 * u, a=tuple(at(-0.022, 0.017, 0.15)), b=tuple(at(-0.025, 0.014, 0.19)),
                    ra=0.015 * u, rb=0.0135 * u, squash=(1.0, 0.8), hint=(0, 1, 0), tag="big_toe"))
    F.add(Ellipsoid(f"ball_{lab}", 0.012 * u, center=tuple(at(0.017, 0.012, 0.172)), radii=(0.03 * u, 0.011 * u, 0.026 * u * fs),
                    rot=Ry @ rot_xyz(0, side * 0.35, 0), tag="small_toes"))
    F.add(Ellipsoid(f"foot_{lab}", 0.015 * u, center=tuple(an + _v(side * 0.02 * u, -0.004 * u, 0)),
                    radii=(0.011 * u, 0.014 * u, 0.014 * u), tag="malleolus"))
    skel.marks[f"toe_tip_{lab}"] = at(-0.025, 0.014, 0.204)
    skel.marks[f"heel_{lab}"] = heel


def _hand(F: Field, skel: Skeleton, side: float, lab: str) -> None:
    m = skel.marks
    L, W = m["hand_len"], m["hand_w"]
    hf = hand_frame(side)
    a, n, w = hf["a"], hf["n"], hf["w"]
    wr = skel[f"hand_{lab}"]
    q = L / 0.19
    rot = np.stack([a, w, n], axis=1)  # world-from-local columns: x=a (fingers), y=w (thumb side), z=n (palm)
    F.add(RoundBox(f"hand_{lab}", 0.012 * q, center=tuple(wr + a * 0.26 * L - n * 0.015 * W),
                   half=(0.24 * L, 0.46 * W, 0.16 * W), radius=0.155 * W, rot=rot, tag="palm"))
    F.add(Ellipsoid(f"hand_{lab}", 0.01 * q, center=tuple(wr + a * 0.30 * L + n * 0.03 * W),
                    radii=(0.20 * L, 0.42 * W, 0.12 * W), rot=rot, tag="palm_pad"))
    F.add(Ellipsoid(f"thumb_01_{lab}", 0.012 * q, center=tuple(wr + a * 0.17 * L + w * 0.30 * W + n * 0.10 * W),
                    radii=(0.16 * L, 0.24 * W, 0.19 * W), rot=rot, tag="thenar"))
    for finger in FINGERS:
        r0 = FINGER_RADIUS[finger] * L * (1.12 if finger == "thumb" else 1.0)
        pts = [skel[f"{finger}_0{k}_{lab}"] for k in (1, 2, 3)]
        d = pts[2] - pts[1]
        length_last = {"thumb": 0.13, "index": 0.10, "middle": 0.11, "ring": 0.105, "pinky": 0.095}[finger] * L
        tip = pts[2] + d / np.linalg.norm(d) * (length_last - r0 * 0.7)
        pts.append(tip)
        radii = (r0, r0 * 0.92, r0 * 0.85, r0 * 0.78)
        for k in range(3):
            F.add(RoundCone(f"{finger}_0{k + 1}_{lab}", 0.004 * q, a=tuple(pts[k]), b=tuple(pts[k + 1]),
                            ra=radii[k], rb=radii[k + 1], squash=(1.0, 0.85), hint=tuple(n)))
        skel.marks[f"tip_{finger}_{lab}"] = tip


def head_frame(skel: Skeleton) -> tuple[np.ndarray, float]:
    m = skel.marks
    return _v(0.0, m["y_chin"], m["head_z"]), m["head_h"]


def _head(F: Field, skel: Skeleton, fp: FaceParams) -> None:
    """Head in meters for a 0.23 m reference head (chin at y=0, tragion near z=0, face toward +z)."""
    O, h = head_frame(skel)
    k = h / 0.23
    fw, fl = fp.face_width, fp.face_length

    def P(x, y, z, face=True):
        return tuple(O + (_v(x * fw, y * fl, z) if face else _v(x, y, z)) * k)

    def R(x, y, z, face=True):
        return tuple((_v(x * fw, y * fl, z) if face else _v(x, y, z)) * k)

    def E(bone, blend, c, r, **kw):
        return F.add(Ellipsoid(bone, blend * k, center=c, radii=r, **kw))

    # cranium, occiput, face masses
    E("head", 0.02, P(0, 0.133, -0.01, False), R(0.079, 0.095, 0.103, False))
    E("head", 0.02, P(0, 0.08, -0.055, False), R(0.06, 0.05, 0.05, False))
    E("head", 0.02, P(0, 0.087, 0.032), R(0.064, 0.05, 0.062))
    E("head", 0.018, P(0, 0.128 * fp.brow_height, 0.082 + 0.003 * fp.brow_prominence),
      R(0.042, 0.0085, 0.008 + 0.004 * fp.brow_prominence), tag="brow")
    for side in (1.0, -1.0):
        a = _asym(fp, side, 0.05)
        E("head", 0.012, P(side * 0.047 * fp.cheekbone_width * a, 0.094 * fp.cheekbone_height, 0.055),
          R(0.024, 0.015, 0.024), tag="cheekbone")
        F.add(RoundCone("head", 0.018 * k, a=P(side * 0.05 * fp.cheekbone_width, 0.097, 0.045),
                        b=P(side * 0.066, 0.099, -0.002, False), ra=0.008 * k, rb=0.0065 * k, tag="zygomatic_arch"))
        E("jaw", 0.016, P(side * 0.04 * a, 0.068, 0.058), R(0.019 * fp.cheek_fullness, 0.021, 0.019 * fp.cheek_fullness),
          tag="cheek")
        jw = fp.jaw_width
        gon = P(side * 0.051 * jw * a, 0.032 + 0.006 * (1.0 - fp.jaw_angle), -0.008)
        F.add(RoundCone("jaw", 0.022 * k, a=gon, b=P(side * 0.055 * jw, 0.088, -0.006),
                        ra=0.0095 * k * fp.jaw_angle ** 0.5, rb=0.009 * k, tag="ramus"))
        F.add(RoundCone("jaw", 0.022 * k, a=gon, b=P(side * 0.017 * fp.chin_width, 0.01, 0.08 * fp.chin_projection),
                        ra=0.0095 * k * fp.jaw_angle ** 0.5, rb=0.0105 * k, tag="mandible"))
    E("jaw", 0.018, P(0, 0.045, 0.022), R(0.049 * fp.jaw_width, 0.042, 0.064), tag="lower_face")
    E("jaw", 0.012, P(0, 0.016 * (2.0 - fp.chin_length), 0.083 * fp.chin_projection),
      R(0.021 * fp.chin_width, 0.017 * fp.chin_length, 0.016), tag="chin")
    E("head", 0.016, P(0, 0.058, 0.073), R(0.031, 0.022, 0.027), tag="muzzle")
    # lips, slightly parted so the topology owns a real mouth opening
    mw = fp.mouth_width
    # upper lip: two lobes meeting at the philtrum (cupid's bow) instead of one sausage; corners taper
    for side in (1.0, -1.0):
        E("head", 0.0035, P(side * 0.0085 * mw, 0.0522, 0.0928), R(0.0135 * mw, 0.0052 * fp.lip_upper, 0.0068 * fp.lip_upper),
          rot=rot_xyz(0, 0, side * 0.10), tag="lip_upper")
    E("jaw", 0.0035, P(0, 0.0408, 0.0905), R(0.0195 * mw, 0.0064 * fp.lip_lower, 0.0076 * fp.lip_lower), tag="lip_lower")
    E("jaw", 0.002, P(0, 0.0468, 0.101), R(0.0205 * mw, 0.0021, 0.02), subtract=True, tag="mouth_slit")
    E("jaw", 0.004, P(0, 0.047, 0.062), R(0.0225, 0.013, 0.033), subtract=True, tag="oral_cavity")
    # nose
    nl, nw, nb, nt = fp.nose_length, fp.nose_width, fp.nose_bridge, fp.nose_tip
    tip_y = 0.119 - 0.044 * nl + 0.004 * fp.nose_upturn
    tip = P(0, tip_y, 0.1155 + 0.006 * (nl - 1.0))
    F.add(RoundCone("head", 0.008 * k, a=P(0, 0.117, 0.088 + 0.004 * nb), b=tip, ra=0.0065 * k * nb,
                    rb=0.0085 * k, squash=(1.1 * nw, 1.0), hint=(0, 0, 1), tag="nose_bridge"))
    E("head", 0.005, tip, R(0.0082 * nt * nw, 0.0078 * nt, 0.0080 * nt), tag="nose_tip")
    for side in (1.0, -1.0):
        E("head", 0.004, P(side * 0.0115 * nw, tip_y - 0.003, 0.102), R(0.0074 * nw, 0.0068, 0.0088), tag="ala")
        E("head", 0.002, P(side * 0.0066 * nw, tip_y - 0.0078, 0.109), R(0.0048 * nw, 0.0026, 0.0065),
          subtract=True, tag="nostril")
    # eyes: socket + almond aperture + lid rolls; the eyeball is a separate mesh in the socket
    re = skel.marks["eye_r"]
    for side, lab in ((1.0, "l"), (-1.0, "r")):
        Ep = skel[f"eye_{lab}"]
        es = fp.eye_size
        rot = rot_xyz(0, side * 0.08, side * 0.10 * fp.eye_tilt)
        F.add(Ellipsoid("head", 0.0015 * k, subtract=True, center=tuple(Ep + _v(-side * 0.0016 * k, 0, re * 0.95)),
                        radii=(0.0150 * k * es, 0.0074 * k * es, 0.011 * k), rot=rot, tag="eye_aperture"))
        F.add(Ellipsoid("head", 0.003 * k, subtract=True, center=tuple(Ep), radii=(re * 1.06,) * 3, tag="eye_socket"))
        F.add(Ellipsoid("head", 0.003 * k, center=tuple(Ep + _v(0, re * 0.72, re * 0.58)),
                        radii=(0.0155 * k * es, 0.0048 * k, 0.0075 * k), rot=rot, tag="lid_upper"))
        F.add(Ellipsoid("head", 0.003 * k, center=tuple(Ep + _v(0, -re * 0.74, re * 0.55)),
                        radii=(0.0145 * k * es, 0.004 * k, 0.0068 * k), rot=rot, tag="lid_lower"))
    # ears
    for side in (1.0, -1.0):
        es = fp.ear_size * _asym(fp, side, 0.05)
        c = _v(*P(side * 0.0745, 0.098, -0.014, False))
        rot = rot_xyz(0.0, -side * (0.30 + 0.25 * (fp.ear_protrusion - 1.0)), 0.0) @ rot_xyz(0.22, 0, 0)
        F.add(Ellipsoid("head", 0.006 * k, center=tuple(c), radii=(0.0048 * k, 0.031 * k * es, 0.019 * k * es),
                        rot=rot, tag="ear"))
        F.add(Ellipsoid("head", 0.002 * k, subtract=True,
                        center=tuple(c + rot @ _v(side * 0.0062 * k, -0.004 * k, 0.003 * k)),
                        radii=(0.0035 * k, 0.012 * k * es, 0.009 * k * es), rot=rot, tag="concha"))
