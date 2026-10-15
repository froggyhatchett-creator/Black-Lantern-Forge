"""Developer-profile adult anatomy geometry (male genitals).

Built only when the character DNA declares an adult (age >= 18), genital
anatomy is enabled, and the export profile is ``developer``.  The mesh is a
separate part flagged ``dev_only`` and skinned to its own bone chain
(genital_root -> penis_01..03, scrotum -> testicle_l/r) so secondary physics
can drive it.  Breasts and nipples live in the body field instead (see
anatomy.py); public exports rebuild the body with nipple detail removed.

Female external genital geometry is NOT implemented in this prototype.
"""

from __future__ import annotations

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.params import GenitalParams
from forge_character_forge.parts import Part, segment_weights
from forge_character_forge.sdf import Ellipsoid, Field, RoundCone


def genital_field(skel, gp: GenitalParams) -> Field:
    u = skel.marks["height"] / 1.75
    F = Field()
    r = 0.0148 * u * gp.penis_girth
    pts = [skel["genital_root"] + np.array([0, 0.004 * u, -0.012 * u]), skel["penis_01"], skel["penis_02"],
           skel["penis_03"], skel.marks["penis_tip"]]
    radii = [r * 1.05, r, r * 0.97, r * 0.95, r * 0.9]
    names = ["genital_root", "penis_01", "penis_02", "penis_03"]
    for i in range(4):
        F.add(RoundCone(names[i], 0.006 * u, a=tuple(pts[i]), b=tuple(pts[i + 1]), ra=radii[i], rb=radii[i + 1],
                        tag="shaft"))
    d = pts[4] - pts[3]
    d /= np.linalg.norm(d)
    g = gp.glans_size
    F.add(Ellipsoid("penis_03", 0.003 * u, center=tuple(pts[4] - d * 0.012 * u * g),
                    radii=(r * 1.06 * g, r * 1.06 * g, r * 1.06 * g), tag="glans"))
    sc = skel["scrotum"]
    s = gp.scrotum_size
    F.add(Ellipsoid("scrotum", 0.012 * u, center=tuple(sc + np.array([0, -0.012 * u, 0.0])),
                    radii=(0.030 * u * s, 0.03 * u * s, 0.026 * u * s), tag="scrotum"))
    for lab in ("l", "r"):
        F.add(Ellipsoid(f"testicle_{lab}", 0.01 * u, center=tuple(skel[f"testicle_{lab}"]),
                        radii=(0.017 * u * gp.testicle_size, 0.022 * u * gp.testicle_size, 0.017 * u * gp.testicle_size),
                        tag="testicle"))
    return F


def build_genitals(skel, gp: GenitalParams, skin_rgb: np.ndarray, body_field) -> Part:
    u = skel.marks["height"] / 1.75
    F = genital_field(skel, gp)
    root = skel["genital_root"]
    lo = np.min([p.bounds()[0] for p in F.prims], axis=0) - 0.01
    hi = np.max([p.bounds()[1] for p in F.prims], axis=0) + 0.01
    v, t = mesher.mesh_box(F.evaluate, lo, hi, 0.0016 * u)
    v, t, _ = mesher.repair(v, t)
    v = mesher.relax(v, t, F, iterations=2, strength=0.5)
    # drop the part buried inside the torso (keeps the visible attachment, removes hidden faces)
    inside = body_field.evaluate(v) < -0.006 * u
    keep = ~inside[t].all(1)
    t = t[keep]
    used = np.unique(t)
    remap = -np.ones(len(v), np.int64)
    remap[used] = np.arange(len(used))
    v, t = v[used], remap[t]
    names = skel.names
    chain = [(names.index("genital_root"), root + np.array([0, 0.004 * u, -0.012 * u]), skel["penis_01"]),
             (names.index("penis_01"), skel["penis_01"], skel["penis_02"]),
             (names.index("penis_02"), skel["penis_02"], skel["penis_03"]),
             (names.index("penis_03"), skel["penis_03"], skel.marks["penis_tip"]),
             (names.index("scrotum"), skel["scrotum"], skel["scrotum"] + np.array([0, -0.02 * u, 0])),
             (names.index("testicle_l"), skel["testicle_l"], skel["testicle_l"] + np.array([0, -0.005 * u, 0])),
             (names.index("testicle_r"), skel["testicle_r"], skel["testicle_r"] + np.array([0, -0.005 * u, 0]))]
    J, W = segment_weights(v, chain, sharp=0.006 * u)
    col = np.tile(skin_rgb * np.array([0.86, 0.72, 0.70]), (len(v), 1))
    return Part("dev_genitals", v, t, "skin", J, W, colors=col, dev_only=True,
                extras={"dev_only": True, "anatomy": "male_genitals", "adult_only": True})
