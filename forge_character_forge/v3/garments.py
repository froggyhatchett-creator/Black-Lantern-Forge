"""v3-fitted basic garments: offset shells of the v3 body, skinned with the body's weights.

These exist so public v3 characters stay clothed. They are fitted to v3 only; v2 garments are not used or claimed on
v3. Shells follow every control through the body's deltas at their source vertices (normal changes under a morph are
not re-applied, so the offset is exact at the neutral and approximate elsewhere).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from forge_character_forge.v3 import model, rig

GARMENTS = {"basic_top": 0.006, "basic_shorts": 0.008}  # name: offset from the skin (m); shorts sit over the top
COLORS = {"basic_top": (0.30, 0.34, 0.42), "basic_shorts": (0.16, 0.17, 0.2)}
COVERS = {"pelvis": ["basic_shorts"], "chest": ["basic_top"]}
COVERAGE_DEFAULTS = {"pelvis": "basic_shorts", "chest": "basic_top"}


def _vertex_normals(v, tris):
    fn = np.cross(v[tris[:, 1]] - v[tris[:, 0]], v[tris[:, 2]] - v[tris[:, 0]])
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)


def _clip(tris, fields):
    """Clip triangles (over base vertex ids) to where every field >= 0. Output vertices are sparse linear combinations
    of base vertices ({id: weight}), so every control delta, normal and skin weight interpolates exactly."""
    polys = [[{int(i): 1.0} for i in t] for t in tris]
    for f in fields:
        val = lambda c: sum(w * f[i] for i, w in c.items())  # noqa: E731
        out = []
        for poly in polys:
            res = []
            for k in range(len(poly)):
                a, b = poly[k], poly[(k + 1) % len(poly)]
                fa, fb = val(a), val(b)
                if fa >= 0:
                    res.append(a)
                if (fa >= 0) != (fb >= 0):
                    t = fa / (fa - fb)
                    c = {}
                    for i, w in a.items():
                        c[i] = c.get(i, 0) + w * (1 - t)
                    for i, w in b.items():
                        c[i] = c.get(i, 0) + w * t
                    res.append(c)
            if len(res) >= 3:
                out.append(res)
        polys = out
    verts, index, faces = [], {}, []
    for poly in polys:
        ids = []
        for c in poly:
            key = tuple(sorted((i, round(w, 6)) for i, w in c.items() if w > 1e-9))
            if key not in index:
                index[key] = len(verts)
                verts.append(key)
            ids.append(index[key])
        faces += [(ids[0], ids[k], ids[k + 1]) for k in range(1, len(ids) - 1)]
    faces = [f for f in faces if len(set(f)) == 3]
    width = max(len(k) for k in verts)
    comb_i = np.zeros((len(verts), width), np.int64)
    comb_w = np.zeros((len(verts), width))
    for r, key in enumerate(verts):
        for c, (i, w) in enumerate(key):
            comb_i[r, c], comb_w[r, c] = i, w
    comb_w /= comb_w.sum(1, keepdims=True)
    return comb_i, comb_w, np.array(faces, np.int64)


@lru_cache(maxsize=None)
def shells():
    """name -> (combination ids (V,k), combination weights (V,k), triangles, offset per vertex (V,3)).

    Each garment is the body surface clipped by planes through the rig's joints (hems are straight cuts, not the
    mesh's edge pattern), offset along the body normal. Top: hips to the neck base with short sleeves; shorts: above
    the hips to mid-thigh; the two overlap at the hips, so no skin shows between them.
    """
    v = model.neutral()
    src_all, _, tris_split, _ = model.body_surface()
    tris = src_all[tris_split]  # body triangles over base vertex ids, outward
    nrm = _vertex_normals(v, tris)
    J = {n: rig.joint_rest(v)[k] for k, n in enumerate(rig.NAMES)}
    joints, _, _ = rig.skin(len(v))
    arm_ids = [k for k, n in enumerate(rig.NAMES) if n.split("_")[0] in ("upperarm", "lowerarm", "hand", "thumb", "index", "middle", "ring", "pinky")]
    arm = np.isin(joints[:, 0], arm_ids)
    y = v[:, 1]
    hip, neck, knee = J["thigh_l"][1], J["neck_01"][1], J["calf_l"][1]
    sleeve = np.ones(len(v))  # >= 0 keeps: torso everywhere, upper arm up to 35% of the way to the elbow
    for s in "lr":
        a, b = J[f"upperarm_{s}"], J[f"lowerarm_{s}"]
        t = ((v - a) @ (b - a)) / np.dot(b - a, b - a)
        side = arm & (v[:, 0] * (1 if s == "l" else -1) > 0)
        sleeve[side] = 0.35 - t[side]
    regions = {
        "basic_top": (~arm[tris].all(1) | (sleeve[tris] > -0.3).all(1), [y - (hip + 0.06), (neck - 0.015) - y, sleeve]),
        "basic_shorts": (~arm[tris].any(1), [y - (knee + 0.5 * (hip - knee)), (hip + 0.11) - y]),
    }
    out = {}
    for name, (cand, fields) in regions.items():
        ci, cw, faces = _clip(tris[cand], fields)
        n = (nrm[ci] * cw[:, :, None]).sum(1)
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        out[name] = (ci, cw, faces, n * GARMENTS[name])
    return out
