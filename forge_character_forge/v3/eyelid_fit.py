"""Eyelid fit (Phase 4A.1): shape changes keep the lid skin on the eyeball.

The problem (measured, see docs/CHARACTER_FORGE_V3_PHASE4A1.md): many shape terms move the lid skin toward or away
from the eyeball without moving the eyeball the same way. The worst is ``face.eye_size``: MakeHuman's CC0
``eyes/*-eye-scale-*`` targets move 386 of the 414 lid vertices and none of the 80 eye-helper vertices that place
the eyeball, so the slider resizes the opening around a fixed eyeball and pulls the lid skin up to 2.25 mm into it
(eye size 0.7-0.8: the eyeball shows through the lower lid of ID-A, the cornea through the closed upper lid of
Mercy-inspired) or lifts it 1-2 mm off it (1.25-1.4: a dark hollow at the outer corner). Body femininity, brow
ridge, cheekbone height, eye size and spacing do the same by smaller amounts, and they add up.

The correction (fit 2) is linear, so it fits the studio's morph basis: for every shape delta D (each control side and
each identity parameter) the skin near the eyeball loses the part of its motion that changes its distance from the
eyeball's surface, measured against the eyeball's own (affine) motion under D:

    dg_i = u_i . d_i - u_i . t - R u_i . A u_i          (first-order change of the skin-to-eyeball gap)
    K_i  = -f(g_i) dg_i u_i                              (u_i = direction from the eyeball centre)

f is 1 for skin within ``GAP_FULL`` of the eyeball sphere (the lids, which drape on it) and fades to 0 at
``GAP_NONE`` (crease, brow, cheek). The motion along the eyeball surface is untouched, so the opening's shape, size,
tilt and position still change exactly as before; only the depth is corrected. The neutral is unchanged (K(0) = 0).

Fit 1 is the geometry before this phase (no correction). Character DNA records the fit (``face_deformation``
group, see ``dna_fit``); DNA without it is fit 1, so every saved character reproduces exactly.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from forge_character_forge.v3 import mh, model

FIT = 2          # current eyelid fit; 1 = Phase 4A and earlier (no correction)
GAP_FULL = 0.003  # m: skin this close to the eyeball sphere is fully corrected (the lids proper)
GAP_NONE = 0.008  # m: ... and from here on not at all
SCHEMA = "forge.v3-face-deformation"
GROUP = "face_deformation"


def _smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


@lru_cache(maxsize=None)
def geometry():
    """Per side: (body vertex ids corrected, unit directions from the eyeball centre, weights f, centre, radius,
    eye proxy ids), all on the neutral."""
    v = model.neutral()
    body = model.body_vertex_ids()
    out = {}
    for s in "lr":
        ids = model.eye_parts()[f"eye_{s}"][0]
        c, R = model.sphere_fit(mh.fit_eyes(v)[ids])
        r = v[body] - c
        rho = np.linalg.norm(r, axis=1)
        g = rho - R
        sel = (g < GAP_NONE) & (r[:, 2] > -0.5 * rho)  # front of the eye; the far side of the socket is skull
        out[s] = (body[sel], r[sel] / rho[sel, None], 1 - _smooth(g[sel], GAP_FULL, GAP_NONE), c, R, ids)
    return out


def _eye_motion(d: np.ndarray, ids: np.ndarray, c: np.ndarray):
    """Least-squares affine motion of one eyeball under d: displacement = A (p - c) + t."""
    v = model.neutral()
    p0 = mh.fit_eyes(v)[ids]
    p1 = mh.fit_eyes(v + d)[ids]
    coef, *_ = np.linalg.lstsq(np.c_[p0 - c, np.ones(len(ids))], p1 - p0, rcond=None)
    return coef[:3].T, coef[3]


def correction(d: np.ndarray) -> np.ndarray:
    """K(d): the fit-2 correction of a shape delta d (V, 3) on the neutral. Zero where d does not change the gap."""
    K = np.zeros_like(d)
    for vid, u, f, c, R, ids in geometry().values():
        A, t = _eye_motion(d, ids, c)
        dg = (u * d[vid]).sum(1) - u @ t - R * np.einsum("ij,jk,ik->i", u, A, u)
        K[vid] -= (f * dg)[:, None] * u
    return K


def fitted(d: np.ndarray, fit: int = FIT) -> np.ndarray:
    return d + correction(d) if fit >= 2 else d


def dna_group(fit: int = FIT) -> dict:
    return {"schema": SCHEMA, "version": 1, "eyelid_fit": int(fit)}


def dna_fit(dna: dict) -> int:
    """The eyelid fit a Character DNA asks for: its ``face_deformation`` group, or 1 when absent (saved before
    Phase 4A.1, reproduced exactly). Unknown schema, version or fit is an error, never reinterpreted."""
    g = dna.get(GROUP)
    if g is None:
        return 1
    if not isinstance(g, dict) or g.get("schema") != SCHEMA or g.get("version") != 1:
        raise ValueError(f"{GROUP}: unsupported schema/version {g!r}")
    fit = g.get("eyelid_fit")
    if fit not in (1, 2):
        raise ValueError(f"{GROUP}.eyelid_fit = {fit!r} is not 1 or 2")
    return fit
