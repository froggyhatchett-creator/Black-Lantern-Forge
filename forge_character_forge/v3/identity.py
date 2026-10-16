"""Generator v3 identity layer (Phase 3A): Forge-owned regional facial transforms on the hm08 topology.

Identity is separate from body proportions, expressions, materials, grooming, clothing and animation: it is a delta on
the neutral mesh (all vertices, including hidden ones: sockets, mouth interior, joint helpers), and everything else
is evaluated on top of it.

Each parameter s in [-1, 1] (0 = the v3 neutral) moves one complete anatomical region by a small affine map,

    delta(p) = s * w(p) * (A (p - pivot) + t)

where w is a smooth volumetric weight (a plateau ellipsoid with a wide smoothstep falloff, so regions transition
without seams or dents) and A, t are fixed per parameter (A is the generator of a scale, shear or rotation, in head
coordinates: x lateral, y up, z forward, origin between the eyeball centres). Every parameter is exactly linear in s,
so parameters compose by addition and fit the studio's linear morph basis; paired features (eyes, cheekbones, jaw
angles) are applied mirrored on both sides.

Regions are placed from data, not guessed landmarks: their centres and extents follow MakeHuman's CC0 detail-target
vertex sets (nose, lips, chin, cheeks, eyes, brows), measured once on the neutral (see ``REGIONS``).
These transforms are Forge's own; MakeHuman's morph library is not used for identity.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from forge_character_forge.v3 import mh, model, textures

IDENTITY_VERSION = 1

# head-frame regions: centre, radii (m), falloff (relative extra radius over which the weight drops to 0)
# measured from the CC0 target vertex sets on the v3 neutral (eye-scale, nose-scale, lip-volume, chin-*, cheek-*, brows)
REGIONS = {
    "cranium": ((0.0, 0.065, -0.07), (0.095, 0.085, 0.115), 0.6),
    "head": ((0.0, 0.0, -0.05), (0.1, 0.12, 0.13), 0.5),  # whole head above the neck (widths act on it as one piece)
    "forehead": ((0.0, 0.055, 0.012), (0.065, 0.04, 0.04), 1.0),
    "brow": ((0.0, 0.021, 0.022), (0.062, 0.012, 0.02), 0.8),
    "eye": ((0.031, 0.0, 0.004), (0.021, 0.0165, 0.024), 1.1),
    "nose": ((0.0, -0.031, 0.032), (0.027, 0.03, 0.022), 0.8),
    "bridge": ((0.0, -0.006, 0.031), (0.011, 0.016, 0.011), 0.7),
    "nose_tip": ((0.0, -0.036, 0.044), (0.013, 0.011, 0.01), 0.7),
    "alae": ((0.0, -0.044, 0.034), (0.025, 0.01, 0.013), 0.6),
    "cheekbone": ((0.056, -0.024, -0.004), (0.022, 0.018, 0.026), 0.7),
    "cheek": ((0.044, -0.052, 0.0), (0.026, 0.026, 0.026), 1.3),
    "mouth": ((0.0, -0.07, 0.012), (0.034, 0.02, 0.034), 0.5),
    "upper_lip": ((0.0, -0.064, 0.03), (0.023, 0.007, 0.012), 0.7),
    "lower_lip": ((0.0, -0.075, 0.027), (0.022, 0.007, 0.012), 0.7),
    "midface": ((0.0, -0.045, 0.02), (0.05, 0.03, 0.035), 0.9),
    "face": ((0.0, -0.045, 0.0), (0.078, 0.11, 0.065), 0.45),
    "lower_face": ((0.0, -0.105, -0.025), (0.08, 0.05, 0.085), 0.8),
    "gonion": ((0.062, -0.095, -0.062), (0.026, 0.026, 0.03), 1.3),
    "chin": ((0.0, -0.118, 0.008), (0.031, 0.026, 0.026), 0.6),
    # Phase 3D addition (a new key only; earlier regions and parameters are unchanged)
    "lips": ((0.0, -0.069, 0.027), (0.026, 0.014, 0.012), 0.9),
}
MIRRORED = {"eye", "cheekbone", "cheek", "gonion"}


@dataclass(frozen=True)
class Param:
    key: str
    region: str
    A: tuple = ((0, 0, 0), (0, 0, 0), (0, 0, 0))
    t: tuple = (0, 0, 0)
    pivot: tuple = (0, 0, 0)  # head frame; for mirrored regions the left-side pivot (x mirrored for the right)
    gate: str = ""            # optional extra weight restricting the region (see _gate)
    label: str = ""


def _d(x=0, y=0, z=0):
    return ((x, 0, 0), (0, y, 0), (0, 0, z))


def _rz(a):  # rotation generator about z (radians at s = 1)
    return ((0, -a, 0), (a, 0, 0), (0, 0, 0))


def _rx(a):
    return ((0, 0, 0), (0, 0, -a), (0, a, 0))


PARAMS = [
    # 1 skull and forehead
    Param("skull_length", "cranium", _d(z=0.10), pivot=(0, 0, -0.03), gate="back", label="Skull length (back of head)"),
    Param("skull_width", "head", _d(x=0.08), gate="above_jaw", label="Head width"),
    Param("forehead_height", "forehead", _d(y=0.16), pivot=(0, 0.02, 0), label="Forehead height"),
    Param("forehead_slope", "forehead", ((0, 0, 0), (0, 0, 0), (0, -0.35, 0)), pivot=(0, 0.025, 0), label="Forehead slope"),
    # 2 brow and sockets
    Param("brow_ridge", "brow", t=(0, 0.0005, 0.0045), label="Brow ridge projection"),
    Param("eye_depth", "eye", t=(0, 0, -0.0028), label="Deep-set eyes"),
    # 3 eyes (socket, lids and eyeball move together)
    Param("eye_spacing", "eye", t=(0.0045, 0, 0), label="Eye spacing"),
    Param("eye_size", "eye", _d(0.13, 0.13, 0.13), pivot=(0.030, 0, 0), label="Eye size"),
    Param("eye_tilt", "eye", _rz(0.16), pivot=(0.030, 0, 0), label="Eye tilt (outer corner up)"),
    Param("eye_height", "eye", t=(0, 0.004, 0), label="Eye height"),
    # 4 nose
    Param("nose_length", "nose", _d(y=0.12), pivot=(0, -0.002, 0.03), label="Nose length"),
    Param("nose_width", "alae", _d(x=0.24), label="Nose width (alae)"),
    Param("nose_projection", "nose", _d(z=0.14), pivot=(0, 0, 0.016), label="Nose projection"),
    Param("nose_bridge", "bridge", t=(0, 0, 0.003), label="Nose bridge height"),
    Param("nose_tip_size", "nose_tip", _d(0.28, 0.28, 0.22), pivot=(0, -0.036, 0.04), label="Nose tip size"),
    Param("nose_tip_angle", "nose_tip", _rx(-0.28), pivot=(0, -0.03, 0.03), label="Nose tip upturn"),
    # 5 cheeks
    Param("cheekbone_width", "cheekbone", t=(0.0045, 0, 0.001), label="Cheekbone width"),
    Param("cheekbone_height", "cheekbone", t=(0, 0.0045, 0), label="Cheekbone height"),
    Param("cheek_fullness", "cheek", t=(0.0035, 0, 0.003), label="Cheek fullness"),
    Param("midface_projection", "midface", t=(0, 0, 0.004), label="Midface projection"),
    # 6 mouth
    Param("mouth_width", "mouth", _d(x=0.15), label="Mouth width"),
    Param("mouth_height", "mouth", t=(0, 0.0035, 0), label="Mouth position (up)"),
    Param("upper_lip", "upper_lip", _d(y=0.3, z=0.25), pivot=(0, -0.069, 0.024), label="Upper lip fullness"),
    Param("lower_lip", "lower_lip", _d(y=0.3, z=0.25), pivot=(0, -0.069, 0.022), label="Lower lip fullness"),
    # 7 jaw
    Param("jaw_width", "lower_face", _d(x=0.12), gate="below_mouth", label="Jaw width"),
    Param("jaw_angle", "gonion", t=(0.0045, -0.0035, -0.002), label="Jaw angle prominence"),
    Param("jaw_taper", "lower_face", _d(x=-0.16), gate="front_low", label="Jaw taper (V-shape)"),
    # 8 chin
    Param("chin_width", "chin", _d(x=0.22), label="Chin width"),
    Param("chin_height", "chin", _d(y=0.2), pivot=(0, -0.085, 0), label="Chin height"),
    Param("chin_projection", "chin", t=(0, 0, 0.0065), label="Chin projection"),
    # 9 overall
    Param("face_length", "face", _d(y=0.085), pivot=(0, 0.02, 0), gate="below_brow", label="Face length"),
    Param("face_width", "face", _d(x=0.07), label="Face width"),
    # 10 eye aperture (Phase 3C): lid-only operators; the eyeball does not move (see _lid_op)
    Param("eye_aperture", "lids", label="Eye opening: almond (+) / round (-)"),
    Param("eye_outer_corner", "lids", label="Outer eye corner lift"),
    Param("eye_length", "lids", label="Eye opening length"),
    # 11 Phase 3D: lip projection (fixes the Phase 3C pout without changing parameters 1-35)
    Param("lip_projection", "lips", t=(0, 0, 0.004), label="Lip projection (both lips as a unit)"),
]
LID_OPS = {  # key: (upper-lid rotation about x, lower-lid rotation about x, outer-corner rotation about z, x stretch)
    "eye_aperture": (0.11, -0.07, 0.0, 0.0),   # rad at s = 1: upper lid down, lower lid up (narrower, almond)
    "eye_outer_corner": (0.0, 0.0, 0.12, 0.0),  # outer half of both lids turns up about the eye centre
    "eye_length": (0.0, 0.0, 0.0, 0.10),        # opening 10 % longer, mostly toward the outer corner
}
KEYS = [p.key for p in PARAMS]


def _smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def region_weight(rel: np.ndarray, name: str, side: float = 1.0) -> np.ndarray:
    c, r, f = REGIONS[name]
    c = np.array(c) * np.array([side, 1, 1])
    q = np.linalg.norm((rel - c) / np.array(r), axis=1)
    return 1 - _smooth(q, 1.0, 1.0 + f)


def _gate(rel, gate):
    y, z = rel[:, 1], rel[:, 2]
    if gate == "back":
        return _smooth(-z, 0.0, 0.05)
    if gate == "below_mouth":
        return _smooth(-y, 0.06, 0.1)
    if gate == "front_low":
        return _smooth(-y, 0.07, 0.11) * _smooth(z, -0.07, -0.01)
    if gate == "above_jaw":  # full above the mouth, fading over the jaw (the face's own width params take over)
        return 1 - _smooth(-y, 0.06, 0.15)
    if gate == "below_brow":
        return _smooth(-y, -0.01, 0.03)
    return 1.0


@lru_cache(maxsize=None)
def frame():
    v = model.neutral()
    E, _ = textures.head_frame_v3(v)
    return E


SMOOTH_ITERS = 12


@lru_cache(maxsize=None)
def _adjacency():
    """Padded neighbour table over body vertices (skin surface) for displacement smoothing."""
    nb = model._neighbours()
    V = len(model.neutral())
    deg = max(len(x) for x in nb.values())
    N = np.tile(np.arange(V)[:, None], (1, deg))
    M = np.zeros((V, deg), bool)
    for i, js in nb.items():
        js = list(js)
        N[i, :len(js)] = js
        M[i, :len(js)] = True
    return N, M, M.any(1)


def smooth_field(d: np.ndarray) -> np.ndarray:
    """Laplacian smoothing of a displacement field over the skin surface (linear, so parameters still add).
    Removes crease-scale discontinuities where neighbouring regions move differently; region-scale shape remains.
    Vertices off the skin (helpers) keep their own displacement."""
    N, M, on = _adjacency()
    cnt = M.sum(1, keepdims=True).clip(1)
    for _ in range(SMOOTH_ITERS):
        avg = (d[N] * M[:, :, None]).sum(1) / cnt
        d = np.where(on[:, None], d + 0.5 * (avg - d), d)
    return d


@lru_cache(maxsize=None)
def _eye_helpers():
    """Per side: (lid skin vertex ids, hidden eye-helper and eye-joint vertex ids that place the eyeball and joint)."""
    _, _, _, _, groups = mh.base_obj()
    out = {}
    for s, side in (("l", 1.0), ("r", -1.0)):
        ids = set()
        for g in (f"helper-{s}-eye", f"joint-{s}-eye"):
            for f in groups.get(g, []):
                ids.update(c[0] for c in f)
        out[side] = (model.lid_region(s, 1), np.array(sorted(ids)))
    return out


def _eyes_follow_lids(delta, rel):
    """The eyeball (placed by hidden helper vertices) takes the least-squares affine motion of its own lids, so lids
    and eyeball move as one unit (smoothing acts on the skin only). Linear in the displacement. (A similarity-only
    fit keeps the eyeball rounder but lets the lids cut into it on deep-set eyes; checked visually.)"""
    for side, (lid, hid) in _eye_helpers().items():
        X = np.c_[rel[lid], np.ones(len(lid))]
        coef, *_ = np.linalg.lstsq(X, delta[lid], rcond=None)
        delta[hid] = np.c_[rel[hid], np.ones(len(hid))] @ coef
    return delta


@lru_cache(maxsize=None)
def ear_mask():
    """Soft ear mask per vertex and per side (+x / -x): ears move rigidly with the side of the head."""
    out = {}
    for side, rel in ((1.0, "ears/l-ear-scale-incr.target"), (-1.0, "ears/r-ear-scale-incr.target")):
        i, d = mh.target(rel)
        m = np.zeros(len(model.neutral()))
        mag = np.linalg.norm(d, axis=1)
        m[i] = _smooth(mag / mag.max(), 0.02, 0.25)
        out[side] = m
    return out


def _rigid_ears(delta, rel):
    """Replace each ear's deformation by the displacement at the ear's centre (no shear: ears keep their shape)."""
    for side, m in ear_mask().items():
        core = m > 0.9
        if not core.any():
            continue
        c = rel[core].mean(0)
        k = np.argmin(np.linalg.norm(rel - c, axis=1) + 1e3 * (m > 0.05))  # nearest non-ear vertex to the ear centre
        delta[:] = delta * (1 - m[:, None]) + delta[k] * m[:, None]
    return delta


@lru_cache(maxsize=None)
def basis(key: str) -> np.ndarray:
    """Delta of one identity parameter at s = 1 over all base vertices (V,3)."""
    p = next(q for q in PARAMS if q.key == key)
    if p.region == "lids":
        return _lid_op(key)
    v = model.neutral()
    rel = v - frame()
    out = np.zeros_like(v)
    sides = (1.0, -1.0) if p.region in MIRRORED else (1.0,)
    for side in sides:
        w = region_weight(rel, p.region, side) * (_gate(rel, p.gate) if p.gate else 1.0)
        A = np.array(p.A, float)
        t = np.array(p.t, float)
        piv = np.array(p.pivot, float)
        if side < 0:  # mirror: x -> -x
            M = np.diag([-1.0, 1, 1])
            A, t, piv = M @ A @ M, M @ t, M @ piv
        out += w[:, None] * ((rel - piv) @ A.T + t)
    return _eyes_follow_lids(_rigid_ears(smooth_field(out), rel), rel)


@lru_cache(maxsize=None)
def _lid_weights():
    """Per side: eyeball centre (sphere fit), upper-lid and lower-lid skin weights (MakeHuman's lid-bone weights)."""
    W = mh.skin_weights()
    v = model.neutral()
    out = {}
    for s, S, side in (("l", "L", 1.0), ("r", "R", -1.0)):
        c, _ = model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])
        wu, wl = np.zeros(len(v)), np.zeros(len(v))
        for b, w in ((f"orbicularis03.{S}", wu), (f"orbicularis04.{S}", wl)):
            q = np.asarray(W[b], float)
            w[q[:, 0].astype(np.int64)] = q[:, 1]
        out[side] = (c, wu, wl)
    return out


def _lid_op(key: str) -> np.ndarray:
    """Eye-opening shape (lids only). Lid vertices turn about the eyeball centre (linearised small rotations), so lid
    skin stays at its distance from the eyeball: the opening changes shape while the eyeball and socket stay put."""
    au, al, az, sx = LID_OPS[key]
    v = model.neutral()
    out = np.zeros_like(v)
    _, hid_all = zip(*_eye_helpers().values())
    for side, (c, wu, wl) in _lid_weights().items():
        r = v - c
        near = 1 - _smooth(np.linalg.norm(r, axis=1), 0.018, 0.03)  # the eyelids proper, not the brow
        wu, wl = wu * near, wl * near
        ex = np.array([1.0, 0, 0])
        if au or al:  # rotation about x: d = theta * (x_axis cross r)
            out += (wu * au)[:, None] * np.cross(ex, r) + (wl * al)[:, None] * np.cross(ex, r)
        lateral = _smooth(r[:, 0] * side, -0.004, 0.012)  # outer half of the opening
        if az:  # outer corner up: rotation about z (mirrored on the right)
            out += ((wu + wl) * lateral * az * side)[:, None] * np.cross(np.array([0, 0, 1.0]), r)
        if sx:
            out[:, 0] += (wu + wl) * (0.4 + 0.6 * lateral) * sx * r[:, 0]
    out = smooth_field(out)
    for hid in hid_all:  # the eyeball and eye joint never move with the lids
        out[hid] = 0
    return out


def identity_delta(values: dict) -> np.ndarray:
    """Sum of parameter deltas (linear, composable). Unknown keys are an error (no silent reinterpretation)."""
    unknown = set(values) - set(KEYS)
    if unknown:
        raise KeyError(f"unknown identity parameters: {sorted(unknown)}")
    v = model.neutral()
    d = np.zeros_like(v)
    for k, s in values.items():
        if s:
            d += float(s) * basis(k)
    return d


def identity_mesh(values: dict) -> np.ndarray:
    """Neutral v3 vertices with an identity applied; soles stay on the floor (the head never reaches it)."""
    return model.neutral() + identity_delta(values)


# Phase 3C: a stylised adult inspired by REF-001 (geometry only; not a likeness). The character also sets the existing
# body control femininity = 1 (separate from identity; see STYLIZED_CONTROLS).
STYLIZED = {
    "MERCY-INSPIRED": {
        "eye_aperture": 0.6, "eye_outer_corner": 1.0, "eye_length": 0.7, "eye_size": 0.8, "eye_tilt": 0.35,
        "eye_spacing": 0.1, "eye_depth": -0.2, "eye_height": 0.15, "brow_ridge": -0.9, "forehead_slope": -0.3,
        "forehead_height": 0.15, "nose_length": -0.6, "nose_width": -0.7, "nose_projection": -0.35, "nose_bridge": -0.3,
        "nose_tip_size": -0.6, "nose_tip_angle": 0.45, "mouth_width": -0.3, "mouth_height": 0.35, "upper_lip": -0.25,
        "lower_lip": -0.1, "lip_projection": -0.8, "cheekbone_width": 0.45, "cheekbone_height": 0.6, "cheek_fullness": -0.35,
        "midface_projection": 0.15, "jaw_width": -0.7, "jaw_angle": 0.0, "jaw_taper": 0.8, "chin_width": -0.7,
        "chin_projection": 0.15, "chin_height": -0.6, "face_width": -0.25, "skull_width": -0.1, "face_length": -0.3,
    },
}

STYLIZED_CONTROLS = {"MERCY-INSPIRED": {"body.femininity": 1.0}}

# Two deliberately different original adults (Phase 3B), and nothing else: identity values only.
IDENTITIES = {
    "ID-A": {  # long, narrow, angular: high forehead, deep-set close eyes, long high-bridged nose, thin lips, V jaw
        "skull_length": 0.8, "skull_width": -0.6, "forehead_height": 0.8, "forehead_slope": 0.4, "brow_ridge": 0.9,
        "eye_depth": 0.7, "eye_spacing": -0.6, "eye_size": -0.3, "eye_tilt": -0.4, "eye_height": 0.2,
        "nose_length": 0.7, "nose_width": -0.5, "nose_projection": 0.6, "nose_bridge": 0.9, "nose_tip_size": -0.4,
        "nose_tip_angle": -0.3, "cheekbone_width": 0.6, "cheekbone_height": 0.8, "cheek_fullness": -0.8,
        "midface_projection": 0.3, "mouth_width": -0.15, "mouth_height": 0.0, "upper_lip": -0.45, "lower_lip": -0.25,
        "jaw_width": -0.6, "jaw_angle": -0.4, "jaw_taper": 0.7, "chin_width": -0.5, "chin_height": 0.8,
        "chin_projection": 0.8, "face_length": 0.9, "face_width": -0.6,
    },
    "ID-B": {  # short, broad, soft: round skull, low forehead, wide-set large prominent eyes, short broad upturned nose,
        # full low cheeks, wide full mouth, wide square jaw, short broad receding chin
        "skull_length": -0.7, "skull_width": 0.8, "forehead_height": -0.7, "forehead_slope": -0.5, "brow_ridge": -0.6,
        "eye_depth": -0.4, "eye_spacing": 0.7, "eye_size": 0.4, "eye_tilt": 0.5, "eye_height": -0.3,
        "nose_length": -0.8, "nose_width": 0.8, "nose_projection": -0.5, "nose_bridge": -0.8, "nose_tip_size": 0.7,
        "nose_tip_angle": 0.7, "cheekbone_width": -0.3, "cheekbone_height": -0.6, "cheek_fullness": 0.6,
        "midface_projection": -0.5, "mouth_width": 0.6, "mouth_height": 0.2, "upper_lip": 0.6, "lower_lip": 0.7,
        "jaw_width": 0.9, "jaw_angle": 0.9, "jaw_taper": -0.6, "chin_width": 0.8, "chin_height": -0.7,
        "chin_projection": -0.5, "face_length": -0.8, "face_width": 0.8,
    },
}
