"""Garments: body-conforming shells, a parametric skirt/robe and a loincloth with physics flaps.

Shell garments are cut from the fixed template topology (so their topology is
fixed too), offset outward and relaxed with an inflate/push-out loop: concave
regions (cleavage, gluteal cleft) are bridged instead of followed, and nothing
ends up inside the body.  Shell vertices inherit (smoothed) skin weights from
the body vertices they came from, so they deform with the rig and with the
breast physics bones.  Skirts are skinned across both thighs plus the cloth
bones; that is the cheap runtime strategy, not a cloth simulation.
"""

from __future__ import annotations

import math

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.parts import Part, segment_weights

GARMENTS = ("briefs", "bra", "tshirt", "shorts", "pants", "skirt", "robe", "loincloth")
DEFAULT_PUBLIC_OUTFIT = ("tshirt", "shorts")
COLORS = {"briefs": (0.12, 0.12, 0.14), "bra": (0.12, 0.12, 0.14), "tshirt": (0.30, 0.34, 0.40),
          "shorts": (0.10, 0.12, 0.18), "pants": (0.10, 0.11, 0.16), "skirt": (0.35, 0.10, 0.12),
          "robe": (0.22, 0.17, 0.12), "loincloth": (0.30, 0.22, 0.13)}
# which garments count as covering each modesty region (used by the public export gate)
COVERS = {"pelvis": {"briefs", "shorts", "pants", "skirt", "robe", "loincloth"},
          "chest": {"bra", "tshirt", "robe"}}


def _dominant(tpl, skel_names):
    return np.array(skel_names)[tpl.joints[:, 0]]


def region_mask(kind: str, tpl, skel_t) -> np.ndarray:
    """Vertex mask on the template (rest pose)."""
    v = tpl.verts
    m = skel_t.marks
    u = m["height"] / 1.75
    yh = m["y_hip"]
    names = list(skel_t.names)
    dom = _dominant(tpl, names)
    x, y, z = v[:, 0], v[:, 1], v[:, 2]
    torso = np.isin(dom, ["pelvis", "spine_01", "spine_02", "spine_03", "breast_l", "breast_r", "clavicle_l", "clavicle_r"])
    thigh = np.isin(dom, ["thigh_l", "thigh_r"])
    calf = np.isin(dom, ["calf_l", "calf_r"])
    upper = np.isin(dom, ["upperarm_l", "upperarm_r"])
    knee_y = skel_t["calf_l"][1]
    hip_x = abs(skel_t["thigh_l"][0])
    outer = np.clip((np.abs(x) - hip_x * 0.8) / (0.07 * u), 0, 1)
    if kind == "briefs":
        low = yh - 0.075 * u + 0.055 * u * outer
        return (torso | thigh) & (y > low) & (y < yh + 0.065 * u)
    if kind in ("shorts", "pants"):
        stop = knee_y + 0.40 * (yh - knee_y) if kind == "shorts" else skel_t["foot_l"][1] + 0.035 * u
        legs = thigh | (calf if kind == "pants" else np.zeros_like(thigh))
        return ((torso & (y < yh + 0.085 * u)) | legs) & (y > stop)
    nip = m.get("nipple_l", skel_t["breast_l"])[1]
    neck_axis = np.array([0.0, 0.0, -0.02 * u])
    r_neck = np.linalg.norm((v - neck_axis)[:, [0, 2]], axis=1)
    if kind == "bra":
        return torso & (y > nip - 0.07 * u) & (y < nip + 0.055 * u) & ~(np.isin(dom, ["clavicle_l", "clavicle_r"]))
    if kind in ("tshirt", "robe"):
        neckline = ~((y > m["y_neck_base"] - 0.06 * u) & (r_neck < 0.085 * u) & (z > -0.02 * u)) & \
            ~((y > m["y_neck_base"] - 0.02 * u) & (r_neck < 0.075 * u))
        sleeve = np.zeros_like(upper)
        for lab in ("l", "r"):
            sh = skel_t[f"upperarm_{lab}"]
            el = skel_t[f"lowerarm_{lab}"]
            d = (el - sh) / np.linalg.norm(el - sh)
            along = (v - sh) @ d
            frac = 0.45 if kind == "tshirt" else 0.95
            sleeve |= (along < frac * np.linalg.norm(el - sh)) & (np.sign(x) == (1 if lab == "l" else -1))
        bottom = yh + 0.05 * u if kind == "tshirt" else yh - 0.02 * u
        return ((torso & (y > bottom)) | (upper & sleeve)) & neckline & (dom != "neck_01")
    raise ValueError(kind)


def _submesh(mask, tris):
    tin = mask[tris].all(1)
    t = tris[tin]
    used = np.unique(t)
    remap = -np.ones(len(mask), np.int64)
    remap[used] = np.arange(len(used))
    return used, remap[t]


def shell_garment(kind: str, body_verts, body_normals, tpl, skel_t, skel, field, thickness: float,
                  body_morphs: dict | None = None) -> Part:
    mask = region_mask(kind, tpl, skel_t)
    used, t = _submesh(mask, tpl.tris)
    t = mesher.remove_dangling(t)
    used2 = np.unique(t)
    remap = -np.ones(len(used), np.int64)
    remap[used2] = np.arange(len(used2))
    t = remap[t]
    used = used[used2]
    v = body_verts[used] + body_normals[used] * thickness
    adj = mesher.neighbors(len(v), t)
    try:
        boundary = np.zeros(len(v), bool)
        for lp in mesher.boundary_loops(t):
            boundary[lp] = True
    except RuntimeError:
        boundary = np.zeros(len(v), bool)
    for _ in range(10):
        lap = mesher.laplacian(v, adj) - v
        lap[boundary] *= 0.2
        v = v + 0.6 * lap
        d = field.evaluate(v)
        g = field.gradient(v)
        g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
        v = v + g * np.clip(thickness - d, 0, None)[:, None]
    # smooth the cut edges (hems, necklines) along their loops so they are not saw-toothed
    try:
        for lp in mesher.boundary_loops(t):
            lp = np.array(lp)
            for _ in range(12):
                v[lp] = 0.5 * v[lp] + 0.25 * (np.roll(v[lp], 1, 0) + np.roll(v[lp], -1, 0))
    except RuntimeError:
        pass
    J = tpl.joints[used].copy()
    W = tpl.weights[used].copy()
    # smooth weights over the garment so cloth does not crease sharply at joints
    dense = np.zeros((len(v), len(skel.names)))
    for k in range(4):
        np.add.at(dense, (np.arange(len(v)), J[:, k]), W[:, k])
    for _ in range(6):
        dense = 0.5 * dense + 0.5 * mesher.laplacian(dense, adj)
    order = np.argsort(-dense, axis=1)[:, :4]
    ww = np.take_along_axis(dense, order, 1)
    ww /= ww.sum(1, keepdims=True)
    uv = np.stack([np.arctan2(v[:, 0], v[:, 2]) * 0.3 / math.pi * 6, v[:, 1] * 6], 1)
    morphs = {name: d[used] for name, d in (body_morphs or {}).items()}
    return Part(kind, v, t, f"cloth_{kind}", order, ww, uvs=uv, morphs=morphs, double_sided=True,
                extras={"garment": kind, "covers": [r for r, s in COVERS.items() if kind in s]})


def skirt_garment(kind: str, skel, field, length: str = "knee") -> Part:
    m = skel.marks
    u = m["height"] / 1.75
    yh = m["y_hip"]
    top_y = yh + 0.07 * u
    hem_y = skel["calf_l"][1] - 0.02 * u if length == "knee" else skel["foot_l"][1] + 0.03 * u
    segs, rows = 64, 18
    center = np.array([0.0, 0.0, -0.01 * u])
    ss = np.repeat(np.arange(rows + 1) / rows, segs)
    ang = np.tile(2 * math.pi * np.arange(segs) / segs, rows + 1)
    ys = top_y + (hem_y - top_y) * ss
    dirs = np.stack([np.sin(ang), np.zeros_like(ang), np.cos(ang)], 1)
    lo, hi = np.zeros(len(ss)), np.full(len(ss), 0.5)
    for _ in range(28):  # vectorized bisection for the body surface along every ray at once
        mid = (lo + hi) / 2
        p = center + dirs * mid[:, None]
        p[:, 1] = ys
        inside = field.evaluate(p) < 0
        lo = np.where(inside, mid, lo)
        hi = np.where(inside, hi, mid)
    radius = hi + 0.006 * u + (0.10 * u if kind == "skirt" else 0.07 * u) * ss ** 1.3
    v = center + dirs * radius[:, None]
    v[:, 1] = ys
    uvs = list(zip(np.tile(np.arange(segs) / segs * 8.0, rows + 1), ss * 6.0))
    # widen rows monotonically so lower rows never cut inside upper ones (keeps the silhouette conical)
    ring = v.reshape(rows + 1, segs, 3)
    rad = np.linalg.norm((ring - center)[..., [0, 2]], axis=2)
    rad = np.maximum.accumulate(rad, axis=0)
    dirs = (ring - center)[..., [0, 2]] / np.maximum(np.linalg.norm((ring - center)[..., [0, 2]], axis=2, keepdims=True), 1e-9)
    ring[..., 0] = center[0] + dirs[..., 0] * rad
    ring[..., 2] = center[2] + dirs[..., 1] * rad
    v = ring.reshape(-1, 3)
    tris = []
    for r in range(rows):
        for c in range(segs):
            a = r * segs + c
            b = r * segs + (c + 1) % segs
            cc = a + segs
            dd = b + segs
            tris += [(a, cc, dd), (a, dd, b)]
    names = skel.names
    jp = names.index("pelvis")
    s = np.clip((top_y - v[:, 1]) / (top_y - hem_y), 0, 1)
    ang = np.arctan2(v[:, 0] - center[0], v[:, 2] - center[2])
    side_l = np.clip(0.5 + v[:, 0] / (0.16 * u), 0, 1)
    front = np.clip(0.5 + np.cos(ang) * 0.9, 0, 1)
    J = np.zeros((len(v), 4), np.int64)
    W = np.zeros((len(v), 4))
    J[:, 0] = jp
    J[:, 1] = names.index("thigh_l")
    J[:, 2] = names.index("thigh_r")
    lvl = np.clip(np.round(1 + s * 2).astype(int), 1, 3)
    J[:, 3] = [names.index(f"cloth_{'front' if f > 0.5 else 'back'}_0{l}") for f, l in zip(front, lvl)]
    legw = 0.55 * s ** 1.2
    clothw = 0.35 * s * np.abs(np.cos(ang)) ** 2
    W[:, 1] = legw * side_l
    W[:, 2] = legw * (1 - side_l)
    W[:, 3] = clothw
    W[:, 0] = np.clip(1 - W[:, 1] - W[:, 2] - W[:, 3], 0, 1)
    W /= W.sum(1, keepdims=True)
    return Part(kind if kind == "skirt" else "robe_skirt", v, np.array(tris), f"cloth_{kind}", J, W,
                uvs=np.array(uvs), double_sided=True,
                extras={"garment": kind, "covers": ["pelvis"], "runtime_strategy": "skinned to thighs + cloth bones"})


def loincloth_parts(body_verts, body_normals, tpl, skel_t, skel, field) -> list[Part]:
    m = skel.marks
    u = m["height"] / 1.75
    yh = m["y_hip"]
    belt_mask = region_mask("briefs", tpl, skel_t)
    v = tpl.verts
    belt_mask &= (v[:, 1] > skel_t.marks["y_hip"] + 0.025 * skel_t.marks["height"] / 1.75)  # template-based: fixed topology
    parts = []
    used, t = _submesh(belt_mask, tpl.tris)
    if len(t):
        bv = body_verts[used] + body_normals[used] * 0.004 * u
        parts.append(Part("loincloth_belt", bv, t, "cloth_loincloth", tpl.joints[used], tpl.weights[used],
                          uvs=np.stack([bv[:, 0] * 8, bv[:, 1] * 8], 1), double_sided=True,
                          extras={"garment": "loincloth", "covers": []}))
    names = skel.names
    for label, sign in (("front", 1.0), ("back", -1.0)):
        c1, c2, c3 = (skel[f"cloth_{label}_0{i}"] for i in (1, 2, 3))
        tip = c3 + (c3 - c2) * 0.6
        pts = [c1, c2, c3, tip]
        cols, rows = 8, 16
        vv, uvs = [], []
        for r in range(rows + 1):
            s = r / rows
            seg = min(int(s * 3), 2)
            ls = s * 3 - seg
            p = pts[seg] * (1 - ls) + pts[seg + 1] * ls
            half = (0.085 - 0.02 * s) * u
            for c in range(cols + 1):
                q = p + np.array([(-1 + 2 * c / cols) * half, 0.0, 0.0])
                vv.append(q)
                uvs.append((c / cols * 2, s * 4))
        vv = np.array(vv)
        for _ in range(5):  # clear the body with a small gap
            d = field.evaluate(vv)
            g = field.gradient(vv)
            g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
            vv = vv + g * np.clip(0.008 * u - d, 0, None)[:, None]
        tris = []
        for r in range(rows):
            for c in range(cols):
                a = r * (cols + 1) + c
                q = (a, a + cols + 1, a + cols + 2, a + 1)
                if sign < 0:
                    q = q[::-1]
                tris += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
        chain = [(names.index("pelvis"), c1 + np.array([0, 0.03 * u, 0]), c1)] + \
                [(names.index(f"cloth_{label}_0{i}"), pts[i - 1], pts[i]) for i in (1, 2, 3)]
        J, W = segment_weights(vv, chain, sharp=0.02 * u)
        parts.append(Part(f"loincloth_{label}", vv, np.array(tris), "cloth_loincloth", J, W, uvs=np.array(uvs),
                          double_sided=True, extras={"garment": "loincloth", "covers": ["pelvis"] if label == "front" else []}))
    return parts


def build_garments(outfit, body_verts, body_normals, tpl, skel_t, skel, field, body_morphs=None) -> list[Part]:
    u = skel.marks["height"] / 1.75
    out = []
    for kind in outfit:
        if kind not in GARMENTS:
            raise ValueError(f"unknown garment {kind!r}; choose from {GARMENTS}")
        if kind in ("briefs", "bra"):
            out.append(shell_garment(kind, body_verts, body_normals, tpl, skel_t, skel, field, 0.0022 * u, body_morphs))
        elif kind in ("tshirt", "shorts", "pants"):
            out.append(shell_garment(kind, body_verts, body_normals, tpl, skel_t, skel, field,
                                     (0.0065 if kind == "tshirt" else 0.0055) * u, body_morphs))
        elif kind == "skirt":
            out.append(skirt_garment("skirt", skel, field, "knee"))
        elif kind == "robe":
            out.append(shell_garment("robe", body_verts, body_normals, tpl, skel_t, skel, field, 0.008 * u, body_morphs))
            out.append(skirt_garment("robe", skel, field, "ankle"))
        elif kind == "loincloth":
            out.extend(loincloth_parts(body_verts, body_normals, tpl, skel_t, skel, field))
    return out
