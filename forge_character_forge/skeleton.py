"""Humanoid skeleton: hierarchy, rest pose (A-pose) and the landmark frames anatomy is built on.

Conventions (glTF native): meters, right-handed, +Y up, character faces +Z,
character's left side is +X.  Every joint's rest orientation is identity, so a
joint's local rest transform is a pure translation from its parent.  Poses are
local rotations about parent-frame axes.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from forge_character_forge.params import BodyParams, FaceParams, GenitalParams

ARM_ABDUCTION_DEG = 48.0   # A-pose: arm angle from vertical
LEG_ABDUCTION_DEG = 4.0
FINGERS = ("thumb", "index", "middle", "ring", "pinky")
# phalanx lengths as fractions of hand length (thumb includes the metacarpal)
PHALANX = {"thumb": (0.20, 0.17, 0.14), "index": (0.24, 0.135, 0.10), "middle": (0.265, 0.155, 0.11),
           "ring": (0.245, 0.145, 0.105), "pinky": (0.185, 0.105, 0.095)}
FINGER_RADIUS = {"thumb": 0.052, "index": 0.047, "middle": 0.049, "ring": 0.045, "pinky": 0.039}
# knuckle offset across the palm width (fraction of hand width, + is thumb side) and spread angle (deg)
KNUCKLE = {"index": (0.37, 0.0, 6.0), "middle": (0.12, 0.02, 1.5), "ring": (-0.13, 0.0, -3.0),
           "pinky": (-0.36, -0.06, -8.5)}

DEV_BONES = ("genital_root", "penis_01", "penis_02", "penis_03", "scrotum", "testicle_l", "testicle_r")
CLOTH_BONES = tuple(f"cloth_{s}_0{i}" for s in ("front", "back") for i in (1, 2, 3))
PHYSICS_BONES = ("breast_l", "breast_r") + DEV_BONES[1:] + CLOTH_BONES

# Mapping onto common retargeting vocabularies (informational metadata in the GLB)
HUMANOID_MAP = {
    "pelvis": "Hips", "spine_01": "Spine", "spine_02": "Chest", "spine_03": "UpperChest", "neck_01": "Neck",
    "head": "Head", "jaw": "Jaw", "eye_l": "LeftEye", "eye_r": "RightEye",
    "clavicle_l": "LeftShoulder", "upperarm_l": "LeftUpperArm", "lowerarm_l": "LeftLowerArm", "hand_l": "LeftHand",
    "clavicle_r": "RightShoulder", "upperarm_r": "RightUpperArm", "lowerarm_r": "RightLowerArm", "hand_r": "RightHand",
    "thigh_l": "LeftUpperLeg", "calf_l": "LeftLowerLeg", "foot_l": "LeftFoot", "ball_l": "LeftToes",
    "thigh_r": "RightUpperLeg", "calf_r": "RightLowerLeg", "foot_r": "RightFoot", "ball_r": "RightToes",
}


@dataclass
class Skeleton:
    names: list
    parents: list          # parent index or -1
    rest: np.ndarray       # (J, 3) world rest positions
    marks: dict            # named landmark points / frames for anatomy

    def index(self, name: str) -> int:
        return self.names.index(name)

    def __getitem__(self, name: str) -> np.ndarray:
        return self.rest[self.names.index(name)]

    def local_offsets(self) -> np.ndarray:
        out = self.rest.copy()
        for j, p in enumerate(self.parents):
            if p >= 0:
                out[j] = self.rest[j] - self.rest[p]
        return out

    def children(self, name: str) -> list[str]:
        j = self.index(name)
        return [self.names[i] for i, p in enumerate(self.parents) if p == j]

    def subset(self, keep: list[str]) -> "Skeleton":
        """Drop joints (and their subtrees must not be needed). Parents are remapped."""
        idx = [self.index(n) for n in keep]
        remap = {old: new for new, old in enumerate(idx)}
        parents = []
        for old in idx:
            p = self.parents[old]
            if p >= 0 and p not in remap:
                raise ValueError(f"cannot drop parent of {self.names[old]}")
            parents.append(remap[p] if p >= 0 else -1)
        return Skeleton([self.names[i] for i in idx], parents, self.rest[idx].copy(), self.marks)


def hand_frame(side: float) -> dict:
    """Unit axes of the hand in A-pose. a: toward fingertips; w: across palm (thumb side, +Z);
    n: palm normal (pointing toward the body/down)."""
    t = math.radians(ARM_ABDUCTION_DEG)
    a = np.array([side * math.sin(t), -math.cos(t), 0.0])
    n = np.array([-side * math.cos(t), -math.sin(t), 0.0])
    w = np.array([0.0, 0.0, 1.0])
    return {"a": a, "n": n, "w": w}


def _rotate_toward(v: np.ndarray, toward: np.ndarray, deg: float) -> np.ndarray:
    r = math.radians(deg)
    out = v * math.cos(r) + toward * math.sin(r)
    return out / np.linalg.norm(out)


def build_skeleton(body: BodyParams, face: FaceParams | None = None, genital: GenitalParams | None = None) -> Skeleton:
    b = body
    fp = face or FaceParams()
    gp = genital or GenitalParams()
    leg = 0.47 * b.leg_length
    torso = 0.31 * b.torso_length
    neck = 0.045 * b.neck_length
    head = 0.13 * b.head_size
    foot_h = 0.045
    total = foot_h + leg + torso + neck + head
    s = b.height_m / total
    fem = b.femininity

    y_ankle = foot_h * s
    y_hip = (foot_h + leg) * s
    y_knee = y_ankle + 0.51 * leg * s
    y_neck_base = y_hip + torso * s
    y_chin = y_neck_base + neck * s
    head_h = head * s
    y_crown = y_chin + head_h
    t_len = torso * s

    hip_x = (0.051 + 0.006 * fem) * b.hip_width * b.height_m
    names, parents, pos = [], [], []

    def add(name, parent, p):
        names.append(name)
        parents.append(names.index(parent) if parent else -1)
        pos.append(np.asarray(p, dtype=float))

    add("root", None, (0, 0, 0))
    add("pelvis", "root", (0, y_hip + 0.065 * t_len, 0.0))
    add("spine_01", "pelvis", (0, y_hip + 0.21 * t_len, -0.004 * s))
    add("spine_02", "spine_01", (0, y_hip + 0.43 * t_len, -0.01 * s))
    add("spine_03", "spine_02", (0, y_hip + 0.65 * t_len, -0.012 * s))
    add("neck_01", "spine_03", (0, y_neck_base, -0.016 * s))
    add("head", "neck_01", (0, y_chin + 0.2 * head_h, -0.012 * s))
    add("jaw", "head", (0, y_chin + 0.3 * head_h, -0.012 * s + 0.078 * head_h))  # head-relative: scales with the head
    head_z = -0.012 * s
    eye_y = y_chin + 0.483 * head_h * fp.face_length
    eye_x = 0.137 * head_h * fp.eye_spacing * fp.face_width
    add("eye_l", "head", (eye_x, eye_y, head_z + 0.283 * head_h))
    add("eye_r", "head", (-eye_x, eye_y, head_z + 0.283 * head_h))

    sh_y = y_hip + 0.955 * t_len
    sh_x = (0.098 - 0.007 * fem) * b.shoulder_width * b.height_m
    upper = 0.186 * s * b.arm_length
    fore = 0.150 * s * b.arm_length
    hand_len = 0.108 * s * b.hand_size
    hand_w = 0.050 * s * b.hand_size
    t = math.radians(ARM_ABDUCTION_DEG)
    for label, side in (("l", 1.0), ("r", -1.0)):
        d = np.array([side * math.sin(t), -math.cos(t), 0.0])
        cl = np.array([side * 0.016 * s, sh_y + 0.012 * s, 0.012 * s])
        sh = np.array([side * sh_x, sh_y, -0.006 * s])
        el = sh + d * upper + np.array([0, 0, -0.008 * s])
        wr = el + d * fore + np.array([0, 0, 0.012 * s])
        add(f"clavicle_{label}", "spine_03", cl)
        add(f"upperarm_{label}", f"clavicle_{label}", sh)
        add(f"lowerarm_{label}", f"upperarm_{label}", el)
        add(f"hand_{label}", f"lowerarm_{label}", wr)
        hf = hand_frame(side)
        a, n, w = hf["a"], hf["n"], hf["w"]
        palm = 0.46 * hand_len
        for finger in FINGERS:
            lengths = [f * hand_len for f in PHALANX[finger]]
            if finger == "thumb":
                p0 = wr + a * 0.10 * hand_len + w * 0.30 * hand_w + n * 0.12 * hand_w
                direction = a * 0.80 + w * 0.48 + n * 0.38
                direction /= np.linalg.norm(direction)
                curl_axis = n
            else:
                off, proximal, spread = KNUCKLE[finger]
                p0 = wr + a * (palm + proximal * hand_len) + w * off * hand_w
                direction = _rotate_toward(a, w if spread >= 0 else -w, abs(spread))
                curl_axis = n
            p = p0
            add(f"{finger}_01_{label}", f"hand_{label}", p)
            for k in range(2):
                direction = _rotate_toward(direction, curl_axis, 9.0 + 4.0 * k)
                p = p + direction * lengths[k]
                add(f"{finger}_0{k + 2}_{label}", f"{finger}_0{k + 1}_{label}", p)

        la = math.radians(LEG_ABDUCTION_DEG)
        hip = np.array([side * hip_x, y_hip, 0.004 * s])
        knee = np.array([side * (hip_x + (y_hip - y_knee) * math.tan(la)) * 0.97, y_knee, 0.012 * s])
        ankle = np.array([side * (hip_x + (y_hip - y_ankle) * math.tan(la)), y_ankle, -0.012 * s])
        foot_len = 0.152 * s * b.foot_size
        ball = ankle + np.array([side * 0.006 * s, -0.75 * y_ankle, 0.58 * foot_len])
        add(f"thigh_{label}", "pelvis", hip)
        add(f"calf_{label}", f"thigh_{label}", knee)
        add(f"foot_{label}", f"calf_{label}", ankle)
        add(f"ball_{label}", f"foot_{label}", ball)

    # breasts: attachment on the chest wall; tip direction is forward/down
    bs = b.breast_size
    for label, side in (("l", 1.0), ("r", -1.0)):
        bx = side * (0.054 + 0.004 * bs) * b.breast_spacing * b.chest_width * b.height_m / 1.75 * 1.0
        by = y_hip + (0.70 - 0.02 * b.breast_sag * bs) * t_len * b.breast_height
        add(f"breast_{label}", "spine_03", (bx, by, 0.055 * s * b.chest_depth))

    # garment secondary-motion chains (loincloth flaps, skirt panels, robe hems)
    u0 = b.height_m / 1.75
    for label, z0, zs in (("front", 0.118, 1.0), ("back", -0.135, -1.0)):
        zz = z0 * u0 * (0.9 + 0.25 * b.body_fat)
        add(f"cloth_{label}_01", "pelvis", (0.0, y_hip + 0.035 * u0, zz))
        add(f"cloth_{label}_02", f"cloth_{label}_01", (0.0, y_hip - 0.085 * u0, zz + zs * 0.012 * u0))
        add(f"cloth_{label}_03", f"cloth_{label}_02", (0.0, y_hip - 0.20 * u0, zz + zs * 0.018 * u0))

    # developer anatomy chain (only exported in the developer profile). Flaccid rest pose hangs
    # down/forward from the pubis; lengths follow the genital parameters.
    u = b.height_m / 1.75
    gy = y_hip - 0.004 * u
    gz = (0.083 + 0.02 * b.body_fat) * u * b.hip_width ** 0.3
    L = 0.085 * u * gp.penis_length
    curve = gp.penis_curve
    d1 = np.array([0.0, -0.55 + 0.45 * curve, 0.83])
    d1 /= np.linalg.norm(d1)
    d2 = np.array([0.0, -0.93 + 0.6 * curve, 0.36 + 0.2 * curve])
    d2 /= np.linalg.norm(d2)
    root = np.array([0.0, gy, gz])
    p1 = root + np.array([0.0, -0.006 * u, 0.004 * u])
    p2 = p1 + d1 * L * 0.32
    p3 = p2 + d2 * L * 0.45
    add("genital_root", "pelvis", root)
    sc = root + np.array([0.0, -0.03 * u, -0.012 * u])
    add("scrotum", "genital_root", sc)
    ts = gp.testicle_size
    add("testicle_l", "scrotum", sc + np.array([0.016 * u * ts, -(0.022 + 0.008 * gp.testicle_asymmetry) * u, 0.004 * u]))
    add("testicle_r", "scrotum", sc + np.array([-0.016 * u * ts, -0.022 * u, 0.006 * u]))
    add("penis_01", "genital_root", p1)
    add("penis_02", "penis_01", p2)
    add("penis_03", "penis_02", p3)

    marks = {
        "scale": s, "height": b.height_m, "y_hip": y_hip, "y_knee": y_knee, "y_ankle": y_ankle,
        "y_neck_base": y_neck_base, "y_chin": y_chin, "y_crown": y_crown, "head_h": head_h,
        "torso_len": t_len, "penis_tip": p3 + d2 * L * 0.23, "head_z": head_z, "eye_r": 0.052 * head_h * fp.eye_size, "hand_len": hand_len, "hand_w": hand_w, "upper_arm": upper, "fore_arm": fore,
    }
    return Skeleton(names, parents, np.array(pos), marks)


def world_to_parent_chain(skel: Skeleton, name: str) -> list[str]:
    chain = []
    j = skel.index(name)
    while j >= 0:
        chain.append(skel.names[j])
        j = skel.parents[j]
    return chain
