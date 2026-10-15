"""Eyes, teeth/tongue, eyebrows, eyelashes and hair, built against the generated body."""

from __future__ import annotations

import math

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.anatomy import head_frame
from forge_character_forge.appearance import AppearanceParams
from forge_character_forge.parts import Part, rigid_weights
from forge_character_forge.sdf import Ellipsoid, Field, RoundBox, RoundCone, rot_xyz


def _v(*a):
    return np.array(a, float)


def uv_sphere(rings: int, segs: int):
    """Sphere with poles on +z/-z. Returns unit verts, tris, polar angle, azimuth."""
    verts, theta, phi = [_v(0, 0, 1)], [0.0], [0.0]
    for i in range(1, rings):
        th = math.pi * i / rings
        for j in range(segs):
            ph = 2 * math.pi * j / segs
            verts.append(_v(math.sin(th) * math.cos(ph), math.sin(th) * math.sin(ph), math.cos(th)))
            theta.append(th)
            phi.append(ph)
    verts.append(_v(0, 0, -1))
    theta.append(math.pi)
    phi.append(0.0)
    tris = []
    for j in range(segs):  # front cap (outward = CCW seen from +z)
        tris.append((0, 1 + j, 1 + (j + 1) % segs))
    for i in range(rings - 2):
        a0 = 1 + i * segs
        b0 = a0 + segs
        for j in range(segs):
            a, a1 = a0 + j, a0 + (j + 1) % segs
            b, b1 = b0 + j, b0 + (j + 1) % segs
            tris += [(a, b, b1), (a, b1, a1)]
    last = len(verts) - 1
    base = 1 + (rings - 2) * segs
    for j in range(segs):
        tris.append((last, base + (j + 1) % segs, base + j))
    return np.array(verts), np.array(tris), np.array(theta), np.array(phi)


def build_eyes(skel, app: AppearanceParams) -> list[Part]:
    parts = []
    re = skel.marks["eye_r"]
    unit, tris, theta, phi = uv_sphere(28, 40)
    iris_theta = math.asin(min(0.5, 0.0062 / 0.012))
    uv_r = 0.5 * np.minimum(theta / (iris_theta * 1.087), 1.0) * np.where(theta > iris_theta * 1.087, 0.98, 1.0)
    uvs = np.stack([0.5 + uv_r * np.cos(phi), 0.5 - uv_r * np.sin(phi)], 1)
    for lab in ("l", "r"):
        c = skel[f"eye_{lab}"]
        j, w = rigid_weights(len(unit), skel.index(f"eye_{lab}"))
        parts.append(Part(f"eye_{lab}", c + unit * re, tris, "eye", j, w, normals=unit.copy(), uvs=uvs.copy()))
        # cornea: transparent bulge over the iris
        cap = unit[theta < iris_theta * 1.35]
        idx = np.nonzero(theta < iris_theta * 1.35)[0]
        remap = -np.ones(len(unit), np.int64)
        remap[idx] = np.arange(len(idx))
        ct = remap[tris]
        ct = ct[(ct >= 0).all(1)]
        bulge = 1.0 + 0.09 * np.cos(np.clip(theta[idx] / (iris_theta * 1.35), 0, 1) * math.pi / 2)
        cv = c + cap * re * bulge[:, None] * 1.003
        j, w = rigid_weights(len(cv), skel.index(f"eye_{lab}"))
        parts.append(Part(f"cornea_{lab}", cv, ct, "cornea", j, w))
    return parts


def build_mouth(skel) -> list[Part]:
    O, h = head_frame(skel)
    k = h / 0.23

    def P(x, y, z):
        return tuple(O + _v(x, y, z) * k)

    up, low = Field(), Field()
    mouth_y = 0.0468
    for i in range(-7, 8):
        x = 0.0032 * i * (1.0 + 0.10 * abs(i))
        x = float(np.sign(i) * min(abs(x), 0.0195))
        z = 0.0855 - 62.0 * x * x
        wdt = 0.0042 if abs(i) <= 1 else (0.0036 if abs(i) <= 3 else 0.0048)
        yaw = math.atan2(-124.0 * x, 1.0)
        rot = rot_xyz(0, yaw, 0)
        up.add(RoundBox("head", 0.0006 * k, center=P(x, mouth_y + 0.0052, z), half=(wdt * k * 0.5, 0.0052 * k, 0.0032 * k),
                        radius=0.0012 * k, rot=rot, tag="tooth"))
        low.add(RoundBox("jaw", 0.0006 * k, center=P(x * 0.95, mouth_y - 0.0050, z - 0.0012), half=(wdt * 0.92 * k * 0.5, 0.0048 * k, 0.003 * k),
                         radius=0.0012 * k, rot=rot, tag="tooth"))
    # gums follow the arch
    for fld, y, bone, zoff in ((up, mouth_y + 0.0105, "head", 0.0), (low, mouth_y - 0.0098, "jaw", -0.0012)):
        xs = np.linspace(-0.0195, 0.0195, 9)
        for a, b in zip(xs[:-1], xs[1:]):
            fld.add(RoundCone(bone, 0.002 * k, a=P(a, y, 0.0855 - 62 * a * a + zoff - 0.0005),
                              b=P(b, y, 0.0855 - 62 * b * b + zoff - 0.0005), ra=0.0036 * k, rb=0.0036 * k, tag="gum"))
    low.add(Ellipsoid("jaw", 0.004 * k, center=P(0, mouth_y - 0.0075, 0.06), radii=(0.016 * k, 0.0055 * k, 0.024 * k),
                      tag="tongue"))
    parts = []
    for name, fld, bone in (("teeth_upper", up, "head"), ("teeth_lower", low, "jaw")):
        lo = np.min([p.bounds()[0] for p in fld.prims], axis=0) - 0.004
        hi = np.max([p.bounds()[1] for p in fld.prims], axis=0) + 0.004
        v, t = mesher.mesh_box(fld.evaluate, lo, hi, 0.0011 * k)
        v, t, _ = mesher.repair(v, t)
        v = mesher.relax(v, t, fld, iterations=2, strength=0.5)
        # color: enamel vs gum vs tongue by nearest primitive tag
        tags = _nearest_tag(v, fld)
        col = np.where(tags[:, None] == "tooth", np.array([0.80, 0.76, 0.66]),
                       np.where(tags[:, None] == "gum", np.array([0.55, 0.16, 0.16]), np.array([0.50, 0.14, 0.15])))
        j, w = rigid_weights(len(v), skel.index(bone))
        parts.append(Part(name, v, t, "teeth", j, w, colors=col))
    return parts


def _nearest_tag(v, fld: Field) -> np.ndarray:
    best = np.full(len(v), np.inf)
    out = np.array([""] * len(v), dtype=object)
    for p in fld.prims:
        d = np.abs(p.distance(v))
        b = d < best
        best[b] = d[b]
        out[b] = p.tag
    return out.astype(str)


def _project_from_front(field: Field, pts: np.ndarray) -> np.ndarray:
    """Project points (given x, y, and a starting z in front of the face) onto the skin."""
    return field.project(pts, iterations=8, max_step=0.01)


def build_brows_lashes(skel, field: Field, app: AppearanceParams, face) -> list[Part]:
    O, h = head_frame(skel)
    k = h / 0.23
    parts = []
    head_j = skel.index("head")
    bv, bt, buv = [], [], []
    lv, lt, luv = [], [], []
    for side, lab in ((1.0, "l"), (-1.0, "r")):
        E = skel[f"eye_{lab}"]
        ey = (E[1] - O[1]) / k
        n_seg = 14
        rows = []
        for i in range(n_seg + 1):
            t = i / n_seg
            x = side * (0.011 + 0.042 * t) * face.face_width
            y = ey + (0.019 + 0.005 * math.sin(math.pi * min(t * 1.15, 1.0)) - 0.006 * t * t) * face.brow_height ** 0.5
            rows.append(O + _v(x, y, 0.14) * k)
        center = _project_from_front(field, np.array(rows))
        nrm = field.gradient(center)
        nrm /= np.linalg.norm(nrm, axis=1, keepdims=True)
        up = np.cross(nrm, np.tile(_v(side, 0, 0), (len(center), 1)) * -1.0)
        up = np.where((up[:, 1] < 0)[:, None], -up, up)
        up /= np.linalg.norm(up, axis=1, keepdims=True)
        base = len(bv)
        for i, (c, n, uvec) in enumerate(zip(center, nrm, up)):
            t = i / n_seg
            half = (0.0030 - 0.0016 * t) * k * (1.15 if t < 0.2 else 1.0)
            bv += [c + n * 0.0007 * k - uvec * half, c + n * 0.0007 * k + uvec * half]
            buv += [(t, 1.0), (t, 0.0)]
        for i in range(n_seg):
            a = base + 2 * i
            q = (a, a + 2, a + 3, a + 1) if side > 0 else (a, a + 1, a + 3, a + 2)
            bt += [(q[0], q[1], q[2]), (q[0], q[2], q[3])]
        # upper lashes along the lid margin
        es = face.eye_size
        aw, ah = 0.0146 * k * es, 0.0062 * k * es
        rot = rot_xyz(0, side * 0.08, side * 0.10 * face.eye_tilt)
        n_l = 16
        margin = []
        for i in range(n_l + 1):
            th = math.radians(18 + 144 * i / n_l)
            p = E + rot @ _v(math.cos(th) * aw, math.sin(th) * ah * 0.92, 0.0) + _v(-side * 0.0016 * k, 0, skel.marks["eye_r"] * 1.05)
            margin.append(p)
        margin = field.project(np.array(margin), iterations=6, max_step=0.004)
        base = len(lv)
        for i, p in enumerate(margin):
            t = i / n_l
            length = (0.0055 + 0.004 * math.sin(math.pi * t)) * k
            outward = _v(0, 0.55, 1.0)
            outward /= np.linalg.norm(outward)
            tip = p + outward * length + _v(0, length * 0.35, 0)
            lv += [p + _v(0, 0, 0.0006 * k), tip]
            luv += [(t, 0.0), (t, 1.0)]
        for i in range(n_l):
            a = base + 2 * i
            lt += [(a, a + 2, a + 3), (a, a + 3, a + 1)]
    j, w = rigid_weights(len(bv), head_j)
    parts.append(Part("eyebrows", np.array(bv), np.array(bt), "brow", j, w, uvs=np.array(buv), double_sided=True))
    j, w = rigid_weights(len(lv), head_j)
    parts.append(Part("eyelashes", np.array(lv), np.array(lt), "lash", j, w, uvs=np.array(luv), double_sided=True))
    return parts


def hair_mask(tpl, skel_tpl) -> np.ndarray:
    """Scalp vertices on the template (rest pose), from a hairline defined in head coordinates."""
    O, h = head_frame(skel_tpl)
    k = h / 0.23
    q = (tpl.verts - O) / k
    names = tpl.tag_names
    ear = np.isin(tpl.tags, [names.index(n) for n in ("ear", "concha") if n in names])
    x, y, z = q[:, 0], q[:, 1], q[:, 2]
    hairline = np.interp(z, [-0.2, -0.04, 0.0, 0.03, 0.06, 0.2], [0.07, 0.075, 0.128, 0.145, 0.168, 0.172])
    temple = np.clip((np.abs(x) - 0.035) / 0.03, 0, 1) * np.clip((z - 0.0) / 0.06, 0, 1) * 0.02
    mask = (y > hairline - temple) & (tpl.region_of_vertex == 1) & ~ear
    # keep away from the ears: an exclusion bubble around each ear
    for side in (1.0, -1.0):
        mask &= np.linalg.norm((q - _v(side * 0.075, 0.098, -0.014)) / _v(1.0, 1.0, 1.0), axis=1) > 0.034
    return mask


def build_hair(body_verts, body_normals, tpl, skel, skel_tpl, app: AppearanceParams, field: Field) -> list[Part]:
    if app.hair_style in ("bald", "buzz"):
        return []
    mask = hair_mask(tpl, skel_tpl)
    tri_in = mask[tpl.tris].all(1)
    t = tpl.tris[tri_in]
    used = np.unique(t)
    remap = -np.ones(len(body_verts), np.int64)
    remap[used] = np.arange(len(used))
    t = remap[t]
    v0 = body_verts[used]
    n0 = body_normals[used]
    O, h = head_frame(skel)
    k = h / 0.23
    # thickness: 0 at the hairline, full volume on top
    adj = mesher.neighbors(len(v0), t)
    loops = mesher.boundary_loops(t)
    edge = np.zeros(len(v0))
    for lp in loops:
        edge[lp] = 1.0
    dist = 1.0 - edge
    for _ in range(25):
        dist = np.minimum(dist, mesher.laplacian(dist[:, None], adj)[:, 0] + 0.08)
        dist[edge > 0] = 0.0
    top = np.clip((v0[:, 1] - O[1]) / (0.23 * k), 0, 1)
    thick = (0.004 + 0.010 * top) * k * np.clip(dist * 1.6, 0, 1) ** 1.2
    v = v0 + n0 * (thick + 0.0008 * k)[:, None]
    for lp in loops:  # smooth the hairline
        lp = np.array(lp)
        for _ in range(10):
            v[lp] = 0.5 * v[lp] + 0.25 * (np.roll(v[lp], 1, 0) + np.roll(v[lp], -1, 0))
    for _ in range(3):  # smooth out small surface detail so the hair reads as volume
        v = v + 0.5 * (mesher.laplacian(v, adj) - v) * (dist > 0.1)[:, None]
    uv = np.stack([np.arctan2(v[:, 0] - O[0], -(v[:, 2] - O[2])) / math.pi * 2.0, (v[:, 1] - O[1]) / (0.08 * k)], 1)
    head_j = skel.index("head")
    j, w = rigid_weights(len(v), head_j)
    parts = [Part("hair_cap", v, t, "hair", j, w, uvs=uv, double_sided=True)]
    if app.hair_style == "long":
        parts.append(_hair_curtain(skel, field, k, O))
    elif app.hair_style == "bun":
        fld = Field()
        fld.add(Ellipsoid("head", 0.004, center=tuple(O + _v(0, 0.20, -0.095) * k), radii=(0.03 * k, 0.026 * k, 0.026 * k)))
        lo, hi = O + _v(-0.05, 0.15, -0.14) * k, O + _v(0.05, 0.25, -0.05) * k
        bv, bt = mesher.mesh_box(fld.evaluate, lo, hi, 0.002 * k)
        buv = np.stack([np.arctan2(bv[:, 0] - O[0], bv[:, 1] - O[1] - 0.2 * k) * 1.5, (bv[:, 2] - O[2]) / (0.02 * k)], 1)
        jj, ww = rigid_weights(len(bv), head_j)
        parts.append(Part("hair_bun", bv, bt, "hair", jj, ww, uvs=buv))
    return parts


def _hair_curtain(skel, field: Field, k: float, O: np.ndarray) -> Part:
    """Long hair: a sheet hanging from the back/sides of the head, pushed out of the body."""
    cols, rows = 30, 22
    length = 0.36 * k
    verts, uvs = [], []
    y_top = 0.13
    for r in range(rows + 1):
        s = r / rows
        for c in range(cols + 1):
            a = math.radians(-100 + 200 * c / cols)  # 0 = straight back
            rx = (0.088 + 0.03 * s) * k
            rz = (0.112 + 0.02 * s) * k
            p = O + _v(math.sin(a) * rx, y_top * k - length * s, -0.008 * k - math.cos(a) * rz)
            verts.append(p)
            uvs.append((c / cols * 3.0, s * 4.0))
    v = np.array(verts)
    # push out of the body (shoulders/back) with a small clearance
    for _ in range(6):
        d = field.evaluate(v)
        g = field.gradient(v)
        g /= np.maximum(np.linalg.norm(g, axis=1, keepdims=True), 1e-9)
        push = np.clip(0.006 * k - d, 0, None)
        v = v + g * push[:, None]
    tris = []
    for r in range(rows):
        for c in range(cols):
            a = r * (cols + 1) + c
            b, cc, d = a + 1, a + cols + 1, a + cols + 2
            tris += [(a, cc, d), (a, d, b)]
    # weights: head at the top blending into neck/upper spine down the back
    y = v[:, 1]
    names = skel.names
    jh, jn, js = names.index("head"), names.index("neck_01"), names.index("spine_03")
    t = np.clip((O[1] + y_top * k - y) / length, 0, 1)
    J = np.zeros((len(v), 4), np.int64)
    W = np.zeros((len(v), 4))
    J[:, 0], J[:, 1], J[:, 2] = jh, jn, js
    W[:, 0] = np.clip(1 - 2.2 * t, 0, 1)
    W[:, 2] = np.clip(2.0 * t - 0.6, 0, 1)
    W[:, 1] = np.clip(1 - W[:, 0] - W[:, 2], 0, 1)
    W /= W.sum(1, keepdims=True)
    return Part("hair_long", v, np.array(tris), "hair", J, W, uvs=np.array(uvs), double_sided=True)
