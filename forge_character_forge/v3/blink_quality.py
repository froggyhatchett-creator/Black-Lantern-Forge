"""Blink quality measurements (Phase 4A), per eye and per blink weight.

For a base character ``v`` (all base vertices) and a blink morph ``d`` (closed minus open, both eyes):

- exposure: front-view visible eyeball pixels of each eye, relative to the open eye;
- folds: lid-region triangles whose normal flips relative to the open lid, split into the visible lid (outer skin and
  margin: rest centroid at least 0.4 mm outside the eyeball sphere, in front of the eyeball centre) and the hidden
  lining (on or inside the eyeball sphere, or behind it: never visible, but counted and reported);
- intersections: visible lid vertices inside the eyeball sphere or the cornea cap (count, deepest in mm), reported
  as created by the blink (beyond the open pose by 0.1 mm), with the open pose's own value alongside;
- lash penetration: lash strands with a point (the two nearest the root excluded) more than 0.15 mm behind the outer
  lid skin (exact distance to the nearest outer-skin triangle, signed by its normal), counting only strands that
  are clear of the skin in the open pose (the blink's own penetrations);
- smoothness: lid-region Laplacian (umbrella) magnitude relative to the open lid (99th percentile and max ratio);
- symmetry: |exposure left - right| and the mirrored left/right closed-lid displacement difference (mm).

Phase 4A.1 adds:

- eyeball through the open lid: outer lid-skin vertices inside the eyeball or cornea meshes in the open pose
  (exact distance to the eye's own triangles, signed by their outward normals; count and deepest, mm). The bare
  neutral itself has 10-13 such margin vertices per eye, up to 1.15 mm, where the margin rests on the cornea;
- closed lash orientation: upper lashes whose root-to-tip chord still rises more than 20 degrees above horizontal at
  full closure ("upright"), and the scatter of that elevation against neighbouring strands (within 2 mm on the same
  lid; 95th percentile and max, degrees).

Lashes: anchored in their lid triangle's frame on the open body (the studio's ``anchorEval``) and following the blink
as a linear morph (closed minus open), which is what both the studio preview and the GLB morph targets show.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from forge_character_forge.render import Camera, DrawItem, rasterize
from forge_character_forge.v3 import grooming, mh, model

VISIBLE_MM = 0.4
LASH_TOL_M = 0.00015


def _eye(v, side, part="eye"):
    return model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"{part}_{side}"][0]])


@lru_cache(maxsize=None)
def _tris():
    src, _, tris, _ = model.body_surface()
    return src[tris]


def _region_tris(side):
    reg = model.lid_region(side, model.CORRECTIVE_RINGS)
    T = _tris()
    return T[np.isin(T, reg).any(1)]


def exposure_per_eye(v: np.ndarray, W: int = 320, H: int = 160) -> dict:
    """Visible eyeball pixels per eye (front orthographic view, eyes flat red, skin flat grey)."""
    src, _, tris, _ = model.body_surface()
    ev = mh.fit_eyes(v)
    items = [DrawItem(v[src], tris, color=(0.5, 0.5, 0.5), roughness=1, specular=0)]
    for side in "lr":
        ids, t = model.eye_parts()[f"eye_{side}"]
        items.append(DrawItem(ev[ids], t, color=(1.0, 0.0, 0.0), roughness=1, specular=0, double_sided=True))
    c = ev.mean(0)
    ipd = abs(ev[ev[:, 0] > 0, 0].mean() - ev[ev[:, 0] < 0, 0].mean())
    cam = Camera(yaw_deg=0, pitch_deg=0, target=tuple(c), distance=1.0, ortho_height=ipd * 1.0)
    img = rasterize(items, cam, W=W, H=H, background=(1, 1, 1), ground_y=None, ssaa=1).astype(int)
    red = (img[:, :, 0] > 120) & (img[:, :, 1] < 70) & (img[:, :, 2] < 70)
    half = W // 2  # +x (the character's left eye) is on the image's right in a front view
    return {"l": int(red[:, half:].sum()), "r": int(red[:, :half].sum())}


def lash_points(v: np.ndarray, d: np.ndarray | None = None) -> np.ndarray:
    """Lash ribbon centre points (strands, points, 3) on body ``v + d``, evaluated like the studio's anchorEval."""
    g = grooming.parts()["lashes"]
    A = g["anchor"]
    src, *_ = model.body_surface()
    P = (v if d is None else v + d)[src]
    tri, bary = np.asarray(A["tri"]), np.asarray(A["bary"])
    o = (P[tri] * bary[:, :, None]).sum(1)
    e1, e2 = P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]]
    t = e1 / np.linalg.norm(e1, axis=1, keepdims=True)
    n = np.cross(e1, e2)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    bt = np.cross(n, t)
    root, off = np.asarray(A["root"]), np.asarray(A["off"])
    pos = o[root] + off[:, :1] * t[root] + off[:, 1:2] * bt[root] + off[:, 2:3] * n[root]
    K = g["points"]
    return pos.reshape(-1, K, 2, 3).mean(2)


def lash_closed(v: np.ndarray, d: np.ndarray, contact: bool = True) -> np.ndarray:
    """Lash point centres at the closed end of expression ``d``: turned with their root patch and with lash contact
    (v3/lash_contact.py): what the studio's lash morph (and so the GLB's lash morph target) holds."""
    from forge_character_forge.v3 import lash_contact as LC
    src, *_ = model.body_surface()
    c0, c1 = lash_points(v), lash_points(v, d)
    if not contact:  # Phase 1-3: rigid lashes in their root triangle's frame
        return c1
    c1 = LC.expression_lashes(c0, c1[:, 0], v[src], (v + d)[src])  # Phase 4A: turned with their root patch
    off = LC.apply(c0, v[src], c1, (v + d)[src])
    return c1 + off


@lru_cache(maxsize=None)
def _mirror_map():
    """Left-eye lid vertex -> mirrored right-eye vertex (nearest after x -> -x on the neutral)."""
    v = model.neutral()
    L, R = model.lid_region("l", model.CORRECTIVE_RINGS), model.lid_region("r", model.CORRECTIVE_RINGS)
    q = v[L] * [-1, 1, 1]
    j = np.argmin(((q[:, None, :] - v[R][None]) ** 2).sum(2), 1)
    return L, R[j]


def _depth(p, c, R, cc, CR):
    """Signed distance outside the eye (eyeball sphere; cornea sphere only over its forward cap), metres."""
    de = np.linalg.norm(p - c, axis=1) - R
    rel = p - cc
    cap = rel[:, 2] / np.maximum(np.linalg.norm(rel, axis=1), 1e-12) > np.cos(0.75)  # within ~43 deg of the axis
    dc = np.linalg.norm(rel, axis=1) - CR
    return np.minimum(de, np.where(cap, dc, 1.0))


def _skin_tris(side):
    """Split-body outer-skin triangles of one eye."""
    from forge_character_forge.v3 import lash_contact as LC
    return LC.eye_tris()[side]


def _lash_sd(pts, p, side):
    from forge_character_forge.v3 import lash_contact as LC
    src, *_ = model.body_surface()
    return LC.signed_to_skin(pts, p[src], _skin_tris(side))[0]


def _eye_signed(v: np.ndarray, side: str, pts: np.ndarray) -> np.ndarray:
    """Signed distance (m) of points to the eye's eyeball and cornea meshes (negative inside either)."""
    from forge_character_forge.v3 import lash_contact as LC
    E = mh.fit_eyes(v)
    out = np.full(len(pts), np.inf)
    for part in ("eye", "cornea"):
        ids, t = model.eye_parts()[f"{part}_{side}"]
        P = E[ids]
        c, _ = model.sphere_fit(P)
        a, b, cc = P[t[:, 0]], P[t[:, 1]], P[t[:, 2]]
        n = np.cross(b - a, cc - a)
        n *= np.sign((((a + b + cc) / 3 - c) * n).sum(1))[:, None]  # outward
        q, dist = LC.point_triangle(pts, a, b, cc)
        k = np.argmin(dist, 1)
        r = np.arange(len(pts))
        sd = np.sign(((pts - q[r, k]) * n[k]).sum(1)) * dist[r, k]
        out = np.minimum(out, sd)
    return out


def open_skin_in_eye(v: np.ndarray) -> dict:
    """Per eye: outer lid-skin vertices inside the eyeball or cornea in the open pose (count, deepest mm)."""
    from forge_character_forge.v3 import lash_contact as LC
    src, *_ = model.body_surface()
    outer = np.unique(src[LC.outer_skin()])
    res = {}
    for s in "lr":
        ids = np.intersect1d(model.lid_region(s, model.CORRECTIVE_RINGS), outer)
        sd = _eye_signed(v, s, v[ids])
        res[s] = {"vertices": int((sd < 0).sum()), "max_mm": round(float(max(-sd.min(), 0) * 1000), 3)}
    return res


UPRIGHT_DEG = 20.0


def lash_orientation(c_open: np.ndarray, c_closed: np.ndarray) -> dict:
    """Per eye: closed upper lashes rising more than ``UPRIGHT_DEG`` and the elevation scatter against neighbours."""
    from forge_character_forge.v3 import lash_contact as LC
    up, sides = LC.strand_upper(c_open), LC.strand_sides(c_open)
    ch = c_closed[:, -1] - c_closed[:, 0]
    el = np.degrees(np.arcsin(np.clip(ch[:, 1] / np.linalg.norm(ch, axis=1), -1, 1)))
    root = c_open[:, 0]
    out = {}
    for s in "lr":
        m = up & (sides == s)
        R, E = root[m], el[m]
        dd = np.linalg.norm(R[:, None] - R[None], axis=2)
        nb = (dd < 0.002) & (dd > 0)
        mean = np.array([E[nb[i]].mean() if nb[i].any() else E[i] for i in range(len(E))])
        sc = np.abs(E - mean)
        out[s] = {"upright": int((E > UPRIGHT_DEG).sum()), "upper_strands": int(m.sum()), "max_elev_deg": round(float(E.max()), 1),
                  "scatter_p95_deg": round(float(np.percentile(sc, 95)), 1), "scatter_max_deg": round(float(sc.max()), 1)}
    return out


def measure(v: np.ndarray, d: np.ndarray, weights=(0.0, 0.25, 0.5, 0.75, 1.0), lash_contact: bool = True,
            lashes=None) -> dict:
    """``lashes`` = (open, closed) lash point centres (S, K, 3) to measure instead of evaluating them here (e.g. the
    studio's own lash geometry)."""
    nb = model._neighbours()
    open_px = exposure_per_eye(v)
    lash0, lash1 = lashes if lashes is not None else (lash_points(v), lash_closed(v, d, lash_contact))  # lashes follow the blink as a linear morph (with contact), as the studio and the GLB do
    out = {"weights": {}}
    info = {}
    for s in "lr":
        c, R = _eye(v, s)
        cc, CR = _eye(v, s, "cornea")
        reg = model.lid_region(s, model.CORRECTIVE_RINGS)
        t = _region_tris(s)
        cen = v[t].mean(1)
        vis_t = (np.linalg.norm(cen - c, axis=1) - R > VISIBLE_MM / 1000) & ((cen - c)[:, 2] > 0)
        vis_v = reg[(np.linalg.norm(v[reg] - c, axis=1) - R > VISIBLE_MM / 1000) & ((v[reg] - c)[:, 2] > 0)]
        inner = [i for i in reg if all(j in set(reg.tolist()) for j in nb[int(i)])]
        info[s] = (c, R, cc, CR, reg, t, vis_t, vis_v, inner)
    lash_side = np.sign(lash0[:, 0, 0])  # +x = left eye
    out["open_skin_in_eye"] = open_skin_in_eye(v)
    out["lash_orientation_closed"] = lash_orientation(lash0, lash1)
    rest = {}
    for s in "lr":
        c, R, cc, CR, reg, t, vis_t, vis_v, inner = info[s]
        sel = lash_side == (1 if s == "l" else -1)
        pts = lash0[sel][:, 2:].reshape(-1, 3)
        clear = ~(_lash_sd(pts, v, s) < -LASH_TOL_M).reshape(sel.sum(), -1).any(1)
        rest[s] = (sel, clear, _depth(v[vis_v], c, R, cc, CR))
    for w in weights:
        p = v + w * d
        row = {}
        px = exposure_per_eye(p) if w else open_px
        lp = lash0 + w * (lash1 - lash0)
        for s in "lr":
            c, R, cc, CR, reg, t, vis_t, vis_v, inner = info[s]
            n0 = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
            n1 = np.cross(p[t[:, 1]] - p[t[:, 0]], p[t[:, 2]] - p[t[:, 0]])
            flip = (n0 * n1).sum(1) < 0
            sel, clear, depth0 = rest[s]
            depth = _depth(p[vis_v], c, R, cc, CR)
            new_in = (depth < -0.0001) & (depth < depth0 - 0.0001)
            lap = lambda q: np.array([np.linalg.norm(q[list(nb[i])].mean(0) - q[i]) for i in inner])
            l0, l1 = lap(v), lap(p)
            ratio = l1 / np.maximum(l0, 2e-5)
            pts = lp[sel][:, 2:].reshape(-1, 3)
            pen = (_lash_sd(pts, p, s) < -LASH_TOL_M).reshape(sel.sum(), -1).any(1) & clear
            row[s] = {"exposure": round(px[s] / max(open_px[s], 1), 4), "folds_visible": int((flip & vis_t).sum()),
                      "folds_hidden_lining": int((flip & ~vis_t).sum()), "folds_total": int(flip.sum()),
                      "lid_in_eye_vertices": int(new_in.sum()),
                      "lid_in_eye_max_mm": round(float(max(-depth[new_in].min(), 0) * 1000), 3) if new_in.any() else 0.0,
                      "lid_in_eye_open_pose_vertices": int((depth0 < -0.0001).sum()),
                      "lash_strands_penetrating": int(pen.sum()), "lash_strands_measured": int(clear.sum()), "lash_strands": int(sel.sum()),
                      "smooth_p99_ratio": round(float(np.percentile(ratio, 99)), 2), "smooth_max_ratio": round(float(ratio.max()), 2)}
        L, Rm = _mirror_map()
        dm = d[Rm] * [-1, 1, 1]
        row["symmetry"] = {"exposure_diff": round(abs(row["l"]["exposure"] - row["r"]["exposure"]), 4),
                           "mirrored_disp_diff_mm": round(float(np.linalg.norm(w * (d[L] - dm), axis=1).max() * 1000), 3)}
        out["weights"][str(w)] = row
    return out


def summary(m: dict) -> dict:
    """Worst values over both eyes and all weights (the numbers the report tables use)."""
    rows = [(w, s, r[s]) for w, r in m["weights"].items() for s in "lr"]
    closed = [r for w, s, r in rows if w == "1.0"]
    return {"exposure_closed_max": max(r["exposure"] for r in closed),
            "folds_visible_max": max(r["folds_visible"] for _, _, r in rows),
            "folds_total_closed": sum(r["folds_total"] for r in closed),
            "folds_visible_closed": sum(r["folds_visible"] for r in closed),
            "folds_hidden_closed": sum(r["folds_hidden_lining"] for r in closed),
            "lid_in_eye_max_mm": max(r["lid_in_eye_max_mm"] for _, _, r in rows),
            "lash_penetrating_max": max(r["lash_strands_penetrating"] for _, _, r in rows),
            "smooth_p99_ratio_max": max(r["smooth_p99_ratio"] for _, _, r in rows),
            "symmetry_exposure_diff_max": max(m["weights"][w]["symmetry"]["exposure_diff"] for w in m["weights"]),
            "half_exposure": [m["weights"]["0.5"][s]["exposure"] for s in "lr"] if "0.5" in m["weights"] else None,
            **({"open_skin_in_eye_vertices": sum(m["open_skin_in_eye"][s]["vertices"] for s in "lr"),
                "open_skin_in_eye_max_mm": max(m["open_skin_in_eye"][s]["max_mm"] for s in "lr")} if "open_skin_in_eye" in m else {}),
            **({"lash_upright_closed": sum(m["lash_orientation_closed"][s]["upright"] for s in "lr"),
                "lash_scatter_p95_deg": max(m["lash_orientation_closed"][s]["scatter_p95_deg"] for s in "lr")}
               if "lash_orientation_closed" in m else {})}


def lash_ribbons(v: np.ndarray, d: np.ndarray | None = None):
    """Full lash ribbon vertices and triangles on body ``v + d`` (as the studio evaluates them), for renders."""
    g = grooming.parts()["lashes"]
    A = g["anchor"]
    src, *_ = model.body_surface()
    P = (v if d is None else v + d)[src]
    tri, bary = np.asarray(A["tri"]), np.asarray(A["bary"])
    o = (P[tri] * bary[:, :, None]).sum(1)
    e1, e2 = P[tri[:, 1]] - P[tri[:, 0]], P[tri[:, 2]] - P[tri[:, 0]]
    t = e1 / np.linalg.norm(e1, axis=1, keepdims=True)
    n = np.cross(e1, e2)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    bt = np.cross(n, t)
    root, off = np.asarray(A["root"]), np.asarray(A["off"])
    return o[root] + off[:, :1] * t[root] + off[:, 1:2] * bt[root] + off[:, 2:3] * n[root], np.asarray(g["tris"])
