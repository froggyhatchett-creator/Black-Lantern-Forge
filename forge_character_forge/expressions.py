"""Facial expression morph targets (real per-vertex displacements on the body mesh).

Each target is a displacement field defined in head coordinates and evaluated on
the character's actual vertices, so it scales with every face shape.  Jaw
opening is a bone (``jaw``), not a morph; the template's mouth is a real
opening, so rotating the jaw parts the lips.
"""

from __future__ import annotations

import math

import numpy as np

from forge_character_forge.anatomy import head_frame

EXPRESSIONS = ("blink_l", "blink_r", "smile", "mouth_close", "brow_raise", "frown", "pucker")


def _gauss(q, c, sigma):
    return np.exp(-np.sum((q - c) ** 2, axis=1) / (2 * sigma * sigma))


def expression_morphs(verts: np.ndarray, skel, face, region: np.ndarray) -> dict[str, np.ndarray]:
    O, h = head_frame(skel)
    k = h / 0.23
    head = region == 1
    q = (verts - O) / k
    out = {}
    re = skel.marks["eye_r"]
    for lab, side in (("l", 1.0), ("r", -1.0)):
        E = skel[f"eye_{lab}"]
        rel = verts - E
        dist = np.linalg.norm(rel, axis=1)
        upper = head & (rel[:, 1] > -0.0015 * k) & (rel[:, 2] > 0.0) & (dist < 0.03 * k) & (np.abs(rel[:, 0]) < 0.022 * k)
        w = np.clip(1.0 - (dist - re * 1.05) / (0.016 * k), 0, 1) * upper
        w *= np.clip(1.0 - np.abs(rel[:, 0]) / (0.022 * k), 0, 1) ** 0.5
        ang = -0.62 * w  # rotate down about the eye's lateral axis
        y, z = rel[:, 1], rel[:, 2]
        ny = y * np.cos(ang) - z * np.sin(ang)
        nz = y * np.sin(ang) + z * np.cos(ang)
        new = np.stack([rel[:, 0], ny, nz], 1)
        rr = np.linalg.norm(new, axis=1)
        new *= np.maximum(rr, re * 1.10)[:, None] / np.maximum(rr, 1e-12)[:, None]
        lower = head & (rel[:, 1] < -0.0015 * k) & (rel[:, 2] > 0.0) & (dist < 0.026 * k) & (np.abs(rel[:, 0]) < 0.02 * k)
        wl = np.clip(1.0 - (dist - re * 1.05) / (0.012 * k), 0, 1) * lower
        d = np.where(upper[:, None], new - rel, 0.0)
        d[:, 1] += wl * 0.0025 * k
        out[f"blink_{lab}"] = d
    mw = face.mouth_width
    smile = np.zeros_like(verts)
    for side in (1.0, -1.0):
        g = _gauss(q, np.array([side * 0.025 * mw, 0.047, 0.086]), 0.011) * head
        smile += g[:, None] * np.array([side * 0.0035, 0.0045, -0.0025]) * k
        gc = _gauss(q, np.array([side * 0.036, 0.07, 0.072]), 0.016) * head
        smile += gc[:, None] * np.array([side * 0.0008, 0.0025, 0.0015]) * k
    out["smile"] = smile
    near_mouth = head & (np.abs(q[:, 0]) < 0.03 * mw) & (q[:, 2] > 0.06)
    gap = 0.0468 - q[:, 1]
    wclose = np.exp(-(gap / 0.0065) ** 2) * near_mouth * np.clip(1 - np.abs(q[:, 0]) / (0.028 * mw), 0, 1) ** 0.5
    mc = np.zeros_like(verts)
    mc[:, 1] = gap * wclose * 0.9 * k
    out["mouth_close"] = mc
    br = np.zeros_like(verts)
    for side in (1.0, -1.0):
        g = _gauss(q, np.array([side * 0.03, 0.14, 0.085]), 0.022) * head
        br[:, 1] += g * 0.0045 * k
    out["brow_raise"] = br
    fr = np.zeros_like(verts)
    for side in (1.0, -1.0):
        g = _gauss(q, np.array([side * 0.014, 0.128, 0.09]), 0.011) * head
        fr += g[:, None] * np.array([-side * 0.0018, -0.0028, 0.0006]) * k
    out["frown"] = fr
    pk = np.zeros_like(verts)
    gm = _gauss(q, np.array([0.0, 0.047, 0.095]), 0.014) * head
    pk[:, 0] = -q[:, 0] * gm * 0.35 * k
    pk[:, 2] = gm * 0.004 * k
    out["pucker"] = pk
    return out
