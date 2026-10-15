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
        # physically plausible vertical jump: countermovement, ~1.7 g push-off, ballistic flight, landing
        g = 9.81
        v0 = math.sqrt(2 * g * 0.25 * u)            # 0.25 m apex
        t_push, t_off = 0.40, 0.53
        t_land = t_off + 2 * v0 / g
        t_end = t_land + 0.55
        T = int(round(t_end * FPS)) + 1
        t = np.arange(T) / FPS
        fine = np.linspace(0, t_end, T * 20)

        def vel(x):
            if x < t_push:  # smooth dip down and back to rest velocity
                return -0.9 * math.sin(math.pi * x / t_push)
            if x < t_off:
                s_ = (x - t_push) / (t_off - t_push)
                return v0 * (3 * s_ * s_ - 2 * s_ ** 3)
            if x < t_land:
                return v0 - g * (x - t_off)
            s_ = min((x - t_land) / 0.25, 1.0)
            return -v0 * (1 - (3 * s_ * s_ - 2 * s_ ** 3)) if x < t_land + 0.25 else \
                0.6 * math.sin(math.pi * min((x - t_land - 0.25) / 0.30, 1.0))
        v = np.array([vel(x) for x in fine])
        y = np.concatenate([[0.0], np.cumsum((v[1:] + v[:-1]) * 0.5 * np.diff(fine))])
        y -= np.linspace(0, y[-1], len(y))          # close the loop exactly at rest height
        y = np.interp(t, fine, y)
        crouch = np.clip(-y / (0.20 * u), 0, 1.2)
        air = np.clip(y / (0.25 * u), 0, 1)
        rot = {"thigh_l": np.array([_q(-55 * c, 0, 0) for c in crouch]),
               "thigh_r": np.array([_q(-55 * c, 0, 0) for c in crouch]),
               "calf_l": np.array([_q(95 * c, 0, 0) for c in crouch]),
               "calf_r": np.array([_q(95 * c, 0, 0) for c in crouch]),
               "foot_l": np.array([_q(-40 * c + 25 * a, 0, 0) for c, a in zip(crouch, air)]),
               "foot_r": np.array([_q(-40 * c + 25 * a, 0, 0) for c, a in zip(crouch, air)]),
               "spine_01": np.array([_q(25 * c, 0, 0) for c in crouch]),
               "upperarm_l": np.array([_q(40 * c - 80 * a, 0, -30) for c, a in zip(crouch, air)]),
               "upperarm_r": np.array([_q(40 * c - 80 * a, 0, 30) for c, a in zip(crouch, air)])}
        root = np.stack([np.zeros(T), y + 0.0 * crouch, 0.06 * u * np.clip(crouch, 0, 1)], 1)
        return Clip("jump", t, rot, root, loop=False)
    if name == "run":
        T = 20                                   # 0.67 s stride -> 3 steps per second
        t = np.arange(T) / FPS
        ph = 2 * np.pi * np.arange(T) / T
        sw = np.sin(ph)
        knee = lambda p: 25 + 85 * max(0.0, math.sin(p + 1.6)) ** 1.5
        rot = {"thigh_l": np.array([_q(-45 * s - 10, 0, 0) for s in sw]),
               "thigh_r": np.array([_q(45 * s - 10, 0, 0) for s in sw]),
               "calf_l": np.array([_q(knee(p), 0, 0) for p in ph]),
               "calf_r": np.array([_q(knee(p + math.pi), 0, 0) for p in ph]),
               "foot_l": np.array([_q(-15 * math.sin(p - 0.5), 0, 0) for p in ph]),
               "foot_r": np.array([_q(15 * math.sin(p - 0.5), 0, 0) for p in ph]),
               "upperarm_l": np.array([_q(38 * s, 0, -55) for s in sw]),
               "upperarm_r": np.array([_q(-38 * s, 0, 55) for s in sw]),
               "lowerarm_l": np.array([_q(-80, 0, 0) for _ in sw]), "lowerarm_r": np.array([_q(-80, 0, 0) for _ in sw]),
               "spine_01": np.array([_q(10, 0, 0) for _ in sw]),
               "pelvis": np.array([_q(0, 8 * s, 0) for s in sw]),
               "spine_02": np.array([_q(4, -12 * s, 0) for s in sw])}
        root = np.stack([np.zeros(T), (0.045 * np.abs(np.cos(ph)) - 0.03) * u, np.zeros(T)], 1)
        return Clip("run", t, rot, root)
    if name == "turn":
        T = 72                                   # two smooth 180-degree turns with small steps
        t = np.arange(T) / FPS
        s = np.arange(T) / T
        def ease(x):
            x = np.clip(x, 0, 1)
            return x * x * (3 - 2 * x)
        yaw = 180 * ease((s - 0.05) / 0.25) + 180 * ease((s - 0.55) / 0.25)
        step = np.sin(np.clip((s - 0.05) / 0.25, 0, 1) * 2 * np.pi) + np.sin(np.clip((s - 0.55) / 0.25, 0, 1) * 2 * np.pi)
        rot = {"root": np.array([_q(0, y, 0) for y in yaw]),
               "thigh_l": np.array([_q(-20 * max(st, 0), 0, 0) for st in step]),
               "calf_l": np.array([_q(35 * max(st, 0), 0, 0) for st in step]),
               "thigh_r": np.array([_q(20 * min(st, 0), 0, 0) for st in step]),
               "calf_r": np.array([_q(-35 * min(st, 0), 0, 0) for st in step]),
               "upperarm_l": np.array([_q(0, 0, -38) for _ in s]), "upperarm_r": np.array([_q(0, 0, 38) for _ in s]),
               "spine_02": np.array([_q(0, -10 * (np.gradient(yaw)[i] / 15.0), 0) for i in range(T)]),
               "head": np.array([_q(0, -14 * (np.gradient(yaw)[i] / 15.0), 0) for i in range(T)])}
        root = np.zeros((T, 3))
        return Clip("turn", t, rot, root)
    if name == "sudden_stop":
        T = 75                                   # jog forward 1.4 m, decelerate in ~0.13 s (~1.7 g), settle
        t = np.arange(T) / FPS
        v_run, t_stop = 2.2 * u, 0.75
        v = np.where(t < t_stop, v_run * np.clip(t / 0.25, 0, 1), np.maximum(0.0, v_run - (t - t_stop) * 17.0))
        z = np.concatenate([[0.0], np.cumsum((v[1:] + v[:-1]) * 0.5 / FPS)])
        moving = np.clip(v / v_run, 0, 1)
        ph = 2 * np.pi * t / 0.6
        brake = np.exp(-((t - t_stop - 0.12) / 0.12) ** 2)
        rot = {"thigh_l": np.array([_q(-35 * m * math.sin(p) - 12 * b, 0, 0) for m, p, b in zip(moving, ph, brake)]),
               "thigh_r": np.array([_q(35 * m * math.sin(p) + 18 * b, 0, 0) for m, p, b in zip(moving, ph, brake)]),
               "calf_l": np.array([_q(20 + 55 * m * max(0, math.sin(p + 1.6)) + 25 * b, 0, 0) for m, p, b in zip(moving, ph, brake)]),
               "calf_r": np.array([_q(20 + 55 * m * max(0, math.sin(p + 1.6 + math.pi)) + 10 * b, 0, 0) for m, p, b in zip(moving, ph, brake)]),
               "upperarm_l": np.array([_q(30 * m * math.sin(p) - 25 * b, 0, -50) for m, p, b in zip(moving, ph, brake)]),
               "upperarm_r": np.array([_q(-30 * m * math.sin(p) - 25 * b, 0, 50) for m, p, b in zip(moving, ph, brake)]),
               "lowerarm_l": np.array([_q(-60 * m - 10, 0, 0) for m in moving]), "lowerarm_r": np.array([_q(-60 * m - 10, 0, 0) for m in moving]),
               "spine_01": np.array([_q(8 * m - 14 * b, 0, 0) for m, b in zip(moving, brake)])}
        root = np.stack([np.zeros(T), (0.03 * moving * np.abs(np.cos(ph)) - 0.02 * moving - 0.05 * brake) * u, z], 1)
        return Clip("sudden_stop", t, rot, root, loop=False)
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


CLIPS = ("idle", "walk", "run", "jump", "turn", "sudden_stop", "wave")


def pose_at(c: Clip, frame: int) -> dict:
    return {j: q[frame] for j, q in c.rotations.items()}
