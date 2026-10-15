"""Poses and procedural animation clips as joint-local rotations (quaternions x, y, z, w).

Rest pose is the A-pose with identity joint orientations, so every rotation
below is about the parent-frame axes: +X pitches a downward-pointing limb
backward, -X swings it forward; Z rolls the arms in the frontal plane.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from forge_character_forge.rig import quat_from_euler

FPS = 30


@dataclass
class Clip:
    name: str
    times: np.ndarray                 # (T,)
    rotations: dict                   # joint -> (T, 4)
    root_translation: np.ndarray      # (T, 3) offset added to the root joint
    loop: bool = True


def _q(rx=0.0, ry=0.0, rz=0.0):
    return quat_from_euler(math.radians(rx), math.radians(ry), math.radians(rz))


POSES = {
    "a_pose": {},
    "relaxed": {"upperarm_l": _q(0, 0, -38), "upperarm_r": _q(0, 0, 38), "lowerarm_l": _q(-12, 0, -4),
                "lowerarm_r": _q(-12, 0, 4)},
    "contrapposto": {"pelvis": _q(0, 6, 4), "spine_02": _q(0, -4, -3), "neck_01": _q(4, -6, 0),
                     "head": _q(-4, 8, 2), "thigh_l": _q(-6, 0, 2), "calf_l": _q(14, 0, 0), "foot_l": _q(-6, 0, 0),
                     "thigh_r": _q(2, 0, -3), "upperarm_l": _q(-10, 0, -40), "lowerarm_l": _q(-35, 0, 0),
                     "upperarm_r": _q(8, 0, 36), "lowerarm_r": _q(-15, 0, 0), "jaw": _q(6, 0, 0)},
    "lunge": {"pelvis": _q(0, 10, 0), "thigh_l": _q(-55, 0, 0), "calf_l": _q(60, 0, 0), "foot_l": _q(-8, 0, 0),
              "thigh_r": _q(25, 0, 0), "calf_r": _q(35, 0, 0), "spine_01": _q(8, 0, 0), "spine_02": _q(6, -8, 0),
              "upperarm_l": _q(30, 0, -30), "upperarm_r": _q(-50, 0, 30), "lowerarm_r": _q(-60, 0, 0),
              "lowerarm_l": _q(-20, 0, 0), "head": _q(-8, 10, 0)},
    "seated": {"thigh_l": _q(-88, 0, 3), "thigh_r": _q(-88, 0, -3), "calf_l": _q(88, 0, 0), "calf_r": _q(88, 0, 0),
               "upperarm_l": _q(-20, 0, -40), "upperarm_r": _q(-20, 0, 40), "lowerarm_l": _q(-50, 0, 0),
               "lowerarm_r": _q(-50, 0, 0)},
}


def _fist(amount: float) -> dict:
    out = {}
    for lab, s in (("l", 1.0), ("r", -1.0)):
        for f in ("index", "middle", "ring", "pinky"):
            for k in (1, 2, 3):
                # curl about the hand's width axis (world Z in the A-pose)
                out[f"{f}_0{k}_{lab}"] = _q(0, 0, -s * amount * (35 + 15 * k))
    return out


def clip(name: str, u: float = 1.0) -> Clip:
    if name == "walk":
        T = 32
        t = np.arange(T) / FPS
        ph = 2 * np.pi * np.arange(T) / T
        rot = {}
        sw = np.sin(ph)
        rot["thigh_l"] = np.array([_q(-28 * s, 0, 0) for s in sw])
        rot["thigh_r"] = np.array([_q(28 * s, 0, 0) for s in sw])
        knee = lambda p: 8 + 50 * max(0.0, math.sin(p + 1.9)) ** 2
        rot["calf_l"] = np.array([_q(knee(p), 0, 0) for p in ph])
        rot["calf_r"] = np.array([_q(knee(p + math.pi), 0, 0) for p in ph])
        rot["foot_l"] = np.array([_q(-10 * math.sin(p - 0.6), 0, 0) for p in ph])
        rot["foot_r"] = np.array([_q(10 * math.sin(p - 0.6), 0, 0) for p in ph])
        rot["upperarm_l"] = np.array([_q(22 * s, 0, -40) for s in sw])
        rot["upperarm_r"] = np.array([_q(-22 * s, 0, 40) for s in sw])
        rot["lowerarm_l"] = np.array([_q(-15 - 10 * max(0, -s), 0, 0) for s in sw])
        rot["lowerarm_r"] = np.array([_q(-15 - 10 * max(0, s), 0, 0) for s in sw])
        rot["pelvis"] = np.array([_q(0, 6 * s, 3 * math.cos(2 * p)) for s, p in zip(sw, ph)])
        rot["spine_02"] = np.array([_q(3, -8 * s, 0) for s in sw])
        rot["head"] = np.array([_q(0, 3 * s, 0) for s in sw])
        root = np.stack([np.zeros(T), 0.022 * u * np.cos(2 * ph) - 0.012 * u, np.zeros(T)], 1)
        return Clip("walk", t, rot, root)
    if name == "idle":
        T = 60
        t = np.arange(T) / FPS
        ph = 2 * np.pi * np.arange(T) / T
        rot = {"spine_02": np.array([_q(1.5 * math.sin(p), 0, 0) for p in ph]),
               "spine_03": np.array([_q(1.0 * math.sin(p), 0, 0) for p in ph]),
               "head": np.array([_q(-1.0 * math.sin(p), 2.0 * math.sin(p / 2), 0) for p in ph]),
               "upperarm_l": np.array([_q(0, 0, -38 + 1.5 * math.sin(p)) for p in ph]),
               "upperarm_r": np.array([_q(0, 0, 38 - 1.5 * math.sin(p)) for p in ph])}
        root = np.stack([np.zeros(T), 0.002 * u * np.sin(ph), np.zeros(T)], 1)
        return Clip("idle", t, rot, root)
    if name == "jump":
        T = 45
        t = np.arange(T) / FPS
        s = np.arange(T) / (T - 1)
        crouch = np.interp(s, [0, 0.2, 0.32, 0.38, 0.62, 0.72, 0.85, 1.0], [0, 1, 1, 0, 0, 0.9, 0.3, 0])
        air = np.interp(s, [0, 0.32, 0.38, 0.5, 0.62, 0.66, 1.0], [0, 0, 0.6, 1.0, 0.25, 0, 0])
        rot = {"thigh_l": np.array([_q(-55 * c, 0, 0) for c in crouch]),
               "thigh_r": np.array([_q(-55 * c, 0, 0) for c in crouch]),
               "calf_l": np.array([_q(95 * c, 0, 0) for c in crouch]),
               "calf_r": np.array([_q(95 * c, 0, 0) for c in crouch]),
               "foot_l": np.array([_q(-40 * c, 0, 0) for c in crouch]),
               "foot_r": np.array([_q(-40 * c, 0, 0) for c in crouch]),
               "spine_01": np.array([_q(25 * c, 0, 0) for c in crouch]),
               "upperarm_l": np.array([_q(40 * c - 80 * a, 0, -30) for c, a in zip(crouch, air)]),
               "upperarm_r": np.array([_q(40 * c - 80 * a, 0, 30) for c, a in zip(crouch, air)])}
        root = np.stack([np.zeros(T), (-0.20 * crouch + 0.32 * air) * u, 0.06 * u * crouch], 1)
        return Clip("jump", t, rot, root, loop=False)
    if name == "wave":
        T = 40
        t = np.arange(T) / FPS
        ph = 2 * np.pi * np.arange(T) / T * 2
        rot = {"upperarm_r": np.array([_q(-10, 0, -100) for _ in ph]),
               "lowerarm_r": np.array([_q(0, 0, -25 - 25 * math.sin(p)) for p in ph]),
               "upperarm_l": np.array([_q(0, 0, -38) for _ in ph]),
               "head": np.array([_q(-3, -10, 0) for _ in ph]),
               "jaw": np.array([_q(8 + 4 * math.sin(p), 0, 0) for p in ph])}
        root = np.zeros((T, 3))
        return Clip("wave", t, rot, root)
    raise ValueError(f"unknown clip {name!r}")


CLIPS = ("idle", "walk", "jump", "wave")


def pose_at(c: Clip, frame: int) -> dict:
    return {j: q[frame] for j, q in c.rotations.items()}
