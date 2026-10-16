"""Lash contact (Phase 4A): lashes bend on the lid skin instead of passing through it.

Lashes are rigid in their root triangle's frame. Closing the eye turns the upper lashes onto the lower lid, and
without contact their tips run up to ~1.7 mm into the lower lid skin. In the expression pose (the blink's closed
end), each lash point is kept at least as far outside the outer lid skin as it was in the open pose, and at least
``CLEAR`` outside it (exact distance to the nearest skin triangle), at the closed end and along the straight morph
path to it (weights 0.25-0.75, as for the lid chords): a point that would come closer is pushed out along that
triangle's normal, and the push is carried
to the rest of the strand (the lash bends at that point instead of kinking). The rest pose is never changed.

The studio applies the same rule (studio.js ``lashContact``) when it builds the lash morph, so the preview and the
GLB's lash morph targets carry it. Each strand is tested against every outer-skin triangle of its eye (649).
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from forge_character_forge.v3 import grooming, mh, model

CLEAR = 0.0001   # m outside the skin
FIRST_POINT = 1  # the root point stays on its triangle
PATH_TS = (1.0, 0.75, 0.5, 0.25)
MAX_DEPTH = 0.003  # a point counts as behind the skin only directly behind a triangle (its nearest point inside the
                   # triangle) and within the lid's thickness; past the patch edge or deeper, it is beside the lid


@lru_cache(maxsize=None)
def outer_skin() -> np.ndarray:
    """Split-body vertex ids of the outer lid skin (both eyes): lid-region vertices at least 0.4 mm outside the
    eyeball sphere, in front of its centre (the hidden lining is excluded)."""
    v = model.neutral()
    src, *_ = model.body_surface()
    ids = []
    for s in "lr":
        c, R = model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])
        reg = model.lid_region(s, model.CORRECTIVE_RINGS)
        rel = v[reg] - c
        ids.append(reg[(np.linalg.norm(rel, axis=1) - R > 0.0004) & (rel[:, 2] > 0)])
    return np.nonzero(np.isin(src, np.concatenate(ids)))[0]


def centres(pos: np.ndarray, K: int) -> np.ndarray:
    """Ribbon vertices [strand][point][left, right] -> point centres (S, K, 3)."""
    return pos.reshape(-1, K, 2, 3).mean(2)


@lru_cache(maxsize=None)
def eye_tris() -> dict:
    """{side: split-body outer-skin triangles of that eye}; a strand is tested against its own eye's skin."""
    src, *_ = model.body_surface()
    t = outer_skin_tris()
    return {s: t[np.isin(src[t], model.lid_region(s, model.CORRECTIVE_RINGS)).all(1)] for s in "lr"}


def strand_sides(c_rest: np.ndarray) -> np.ndarray:
    """Eye of each strand from its root (+x = the character's left eye)."""
    return np.where(c_rest[:, 0, 0] > 0, "l", "r")


def apply(c_rest, P_rest, c_closed, P_closed) -> np.ndarray:
    """Contact offsets (S, K, 3) for the closed lash point centres (split-body positions open and closed)."""
    S, K, _ = c_closed.shape
    off = np.zeros_like(c_closed)
    sides = strand_sides(c_rest)
    for side, tris in eye_tris().items():
        m = sides == side
        carry = np.zeros((m.sum(), 3))
        for k in range(K):
            if k >= FIRST_POINT:
                sd0, _ = signed_to_skin(c_rest[m, k], P_rest, tris)
                floor = np.minimum(sd0, CLEAR)
                for _ in range(2):  # the nearest triangle may change after a push
                    for t in PATH_TS:  # the closed end and the straight morph path to it (see model._clear_chords)
                        c = c_rest[m, k] + t * (c_closed[m, k] + carry - c_rest[m, k])
                        sd, n = signed_to_skin(c, P_rest + t * (P_closed - P_rest), tris)
                        carry = carry + (np.maximum(floor - sd, 0) / t)[:, None] * n
            off[m, k] = carry
    return off


def point_triangle(p: np.ndarray, a: np.ndarray, b: np.ndarray, c: np.ndarray):
    """Closest points of points p (M,3) on triangles (M,T,3 each, or T,3 broadcast): (closest (M,T,3), distance (M,T)).
    Standard region test (Ericson, Real-Time Collision Detection 5.1.5), vectorised."""
    p = p[:, None, :]
    ab, ac, ap = b - a, c - a, p - a
    d1, d2 = (ab * ap).sum(-1), (ac * ap).sum(-1)
    bp = p - b
    d3, d4 = (ab * bp).sum(-1), (ac * bp).sum(-1)
    cp = p - c
    d5, d6 = (ab * cp).sum(-1), (ac * cp).sum(-1)
    va, vb, vc = d3 * d6 - d5 * d4, d5 * d2 - d1 * d6, d1 * d4 - d3 * d2
    den = np.where(np.abs(va + vb + vc) < 1e-30, 1e-30, va + vb + vc)
    v, w = vb / den, vc / den
    q = a + ab * v[..., None] + ac * w[..., None]                       # interior
    sel = lambda m, r: np.where(m[..., None], r, q)
    with np.errstate(divide="ignore", invalid="ignore"):
        q = sel((va <= 0) & (d4 - d3 >= 0) & (d5 - d6 >= 0), b + (c - b) * np.nan_to_num((d4 - d3) / ((d4 - d3) + (d5 - d6)))[..., None])
        q = sel((vb <= 0) & (d2 >= 0) & (d6 <= 0), a + ac * np.nan_to_num(d2 / (d2 - d6))[..., None])
    q = sel((d6 >= 0) & (d5 <= d6), np.broadcast_to(c, q.shape))
    with np.errstate(divide="ignore", invalid="ignore"):  # later assignments win: priority A, B, AB, C, AC, BC
        q = sel((vc <= 0) & (d1 >= 0) & (d3 <= 0), a + ab * np.nan_to_num(d1 / (d1 - d3))[..., None])
    q = sel((d3 >= 0) & (d4 <= d3), np.broadcast_to(b, q.shape))
    q = sel((d1 <= 0) & (d2 <= 0), np.broadcast_to(a, q.shape))
    return q, np.linalg.norm(p - q, axis=-1)


@lru_cache(maxsize=None)
def outer_skin_tris() -> np.ndarray:
    """Split-body triangles of the outer lid skin (every corner on the outer skin)."""
    _, _, tris, _ = model.body_surface()
    return tris[np.isin(tris, outer_skin()).all(1)]


def signed_to_skin(pts: np.ndarray, P: np.ndarray, tris: np.ndarray | None = None):
    """Signed distance of points (M,3) to the outer lid skin of split-body positions P: distance to the nearest
    triangle, negative only when directly behind it (nearest point inside the triangle, along its outward normal)
    and within ``MAX_DEPTH``. Returns (signed, unit normal)."""
    t = outer_skin_tris() if tris is None else tris
    a, b, c = P[t[:, 0]], P[t[:, 1]], P[t[:, 2]]
    q, dist = point_triangle(pts, a, b, c)
    k = np.argmin(dist, 1)
    n = np.cross(b - a, c - a)
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-15
    nk = n[k]
    r = np.arange(len(pts))
    plane = ((pts - q[r, k]) * nk).sum(1)
    behind = (plane < 0) & (np.abs(plane) >= 0.98 * dist[r, k]) & (dist[r, k] < MAX_DEPTH)
    return np.where(behind, -dist[r, k], dist[r, k]), nk
