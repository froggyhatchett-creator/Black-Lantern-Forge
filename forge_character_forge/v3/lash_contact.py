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
MAX_PATH_STEP = 0.001  # m: largest single push for an in-between weight (divided by t it would grow 4x at t = 0.25)
MAX_BEND = 0.0025      # m: largest total push of a lash point (lashes bend over the lid; they do not jump off it)
BEND_RATIO = 0.5       # and at most this fraction of its distance from the root (about a 27 degree bend)
MAX_BEND_OWN = 0.001   # m: smaller allowance against the lash's own lid (its folded skin would fling the lash off)
MAX_DEPTH = 0.003  # a point counts as behind the skin only directly behind a triangle (its nearest point inside the
                   # triangle) and within the lid's thickness; past the patch edge or deeper, it is beside the lid
# Phase 4A.1 (expression lash orientation, see expression_lashes); TURN_SIGMA = 0 reproduces Phase 4A
TURN_SIGMA = 0.0015     # m: root normals are averaged over neighbouring strands of the same lid (Gaussian of root distance)
TURN_RADIUS = 0.004     # m: ... within this distance


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
    """{side: split-body outer-skin triangles of that eye} (the lash penetration measurement tests all of them)."""
    src, *_ = model.body_surface()
    t = outer_skin_tris()
    return {s: t[np.isin(src[t], model.lid_region(s, model.CORRECTIVE_RINGS)).all(1)] for s in "lr"}


@lru_cache(maxsize=None)
def lid_tris() -> dict:
    """{(side, upper): outer-skin triangles of that eye's upper or lower lid (by MakeHuman's lid-bone weights)}.
    Contact acts between the lids: upper lashes meet the lower lid's skin and lower lashes the upper lid's. A lash
    is rigid on its own lid, and the folded skin near the corners there would push it off the lid, not bend it."""
    src, *_ = model.body_surface()
    out = {}
    for s, t in eye_tris().items():
        wu, wl = model._lid_bone_weights(s)
        up = (wu[src[t]] - wl[src[t]]).mean(1) > 0
        out[(s, True)], out[(s, False)] = t[up], t[~up]
    return out


def strand_upper(c_rest: np.ndarray) -> np.ndarray:
    """Upper-lid strands: the tip above the root in the open pose (upper lashes curl up, lower lashes down)."""
    return c_rest[:, -1, 1] > c_rest[:, 0, 1]


def strand_sides(c_rest: np.ndarray) -> np.ndarray:
    """Eye of each strand from its root (+x = the character's left eye)."""
    return np.where(c_rest[:, 0, 0] > 0, "l", "r")


def _contact(off, m, tris, c_rest, P_rest, c_closed, P_closed, max_bend):
    """One contact stage for strands ``m`` against ``tris``: its push starts at the root and is carried to the tip
    (the lash bends), on top of earlier stages' pushes already in ``off`` (S, K, 3); capped at ``max_bend`` and at
    BEND_RATIO x the point's distance from the root."""
    S, K, _ = c_closed.shape
    base = off[m].copy()
    carry = np.zeros((int(m.sum()), 3))
    for k in range(K):
        if k >= FIRST_POINT:
            sd0, _ = signed_to_skin(c_rest[m, k], P_rest, tris)
            floor = np.minimum(sd0, CLEAR)
            reach = BEND_RATIO * np.linalg.norm(c_closed[m, k] - c_closed[m, 0], axis=1)
            for _ in range(2):  # the nearest triangle may change after a push
                for t in PATH_TS:  # the closed end and the straight morph path to it (see model._clear_chords)
                    c = c_rest[m, k] + t * (c_closed[m, k] + base[:, k] + carry - c_rest[m, k])
                    sd, n = signed_to_skin(c, P_rest + t * (P_closed - P_rest), tris)
                    step = np.maximum(floor - sd, 0) / t
                    if t < 1:  # path corrections are capped: they must not fling the lash away from the lid
                        step = np.minimum(step, MAX_PATH_STEP)
                    carry = carry + step[:, None] * n
                L = np.linalg.norm(carry, axis=1, keepdims=True)  # bend, not detachment
                carry = carry * np.minimum(1.0, np.minimum(max_bend, reach)[:, None] / np.maximum(L, 1e-12))
        off[m, k] = base[:, k] + carry


def apply(c_rest, P_rest, c_closed, P_closed) -> np.ndarray:
    """Contact offsets (S, K, 3) for the closed lash point centres (split-body positions open and closed): first
    between the lids (upper lashes on the lower lid's skin and the reverse), then upper lashes on their own lid's fold
    with a smaller allowance (``MAX_BEND_OWN``: near the inner corner that skin folds over the lashes as it closes)."""
    off = np.zeros_like(c_closed)
    sides, upper = strand_sides(c_rest), strand_upper(c_rest)
    for (side, up_lid), tris in lid_tris().items():
        _contact(off, (sides == side) & (upper != up_lid), tris, c_rest, P_rest, c_closed, P_closed, MAX_BEND)
    for side in "lr":
        _contact(off, (sides == side) & upper, lid_tris()[(side, True)], c_rest, P_rest, c_closed, P_closed, MAX_BEND_OWN)
    return off


def _rotation_between(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Minimal rotations (S, 3, 3) taking unit vectors a (S, 3) onto b (Rodrigues)."""
    v = np.cross(a, b)
    c = (a * b).sum(1)
    K = np.zeros((len(a), 3, 3))
    K[:, 0, 1], K[:, 0, 2], K[:, 1, 0], K[:, 1, 2], K[:, 2, 0], K[:, 2, 1] = -v[:, 2], v[:, 1], v[:, 2], -v[:, 0], -v[:, 1], v[:, 0]
    return np.eye(3)[None] + K + np.einsum("sij,sjk->sik", K, K) / (1 + c)[:, None, None]


def root_normals(P: np.ndarray, tri: np.ndarray) -> np.ndarray:
    """Smoothed surface normal at each lash root (S, 3): the vertex normals (area-weighted over every body triangle
    at the vertex) of its root triangle's corners, averaged. Split-body positions P."""
    _, _, tris, weld = model.body_surface()
    fn = np.cross(P[tris[:, 1]] - P[tris[:, 0]], P[tris[:, 2]] - P[tris[:, 0]])
    n = np.zeros_like(P)
    for k in range(3):
        np.add.at(n, np.asarray(weld)[tris[:, k]], fn)  # accumulate on the first UV-seam copy (as the studio does)
    n = n[np.asarray(weld)]
    n /= np.linalg.norm(n, axis=1, keepdims=True) + 1e-30  # unit vertex normals, as the studio's normals()
    r = n[tri].sum(1)
    return r / np.linalg.norm(r, axis=1, keepdims=True)


@lru_cache(maxsize=None)
def turn_neighbours():
    """(strand index i, neighbour j, weight) of the root-normal smoothing: strands of the same eye and lid, roots within
    ``TURN_RADIUS`` on the neutral, Gaussian weights normalised per strand (the studio reads them from the pack)."""
    if not TURN_SIGMA:
        return np.zeros((0, 2), np.int64), np.zeros(0)
    from forge_character_forge.v3 import blink_quality as Q
    c = Q.lash_points(model.neutral())
    root, grp = c[:, 0], np.char.add(strand_sides(c), np.where(strand_upper(c), "u", "d"))
    d = np.linalg.norm(root[:, None] - root[None], axis=2)
    m = (d < TURN_RADIUS) & (grp[:, None] == grp[None])
    i, j = np.nonzero(m)
    w = np.exp(-0.5 * (d[i, j] / TURN_SIGMA) ** 2)
    s = np.zeros(len(c))
    np.add.at(s, i, w)
    return np.c_[i, j], w / s[i]


def _smoothed(n: np.ndarray) -> np.ndarray:
    ij, w = turn_neighbours()
    if not len(w):
        return n
    out = np.zeros_like(n)
    np.add.at(out, ij[:, 0], w[:, None] * n[ij[:, 1]])
    return out / np.linalg.norm(out, axis=1, keepdims=True)


def expression_lashes(c_rest: np.ndarray, root_closed: np.ndarray, P_rest: np.ndarray, P_closed: np.ndarray) -> np.ndarray:
    """Closed lash point centres (S, K, 3): the root stays on its triangle (``root_closed``) and the lash turns with
    the surface normal at its root, averaged over the neighbouring strands of its lid (Phase 4A.1). (Rigid in the root
    triangle's own frame, a lash stood upright on the closed lid wherever blink model 2 shears that one margin
    triangle while the lid around it turns. With single-triangle normals, neighbouring lashes turned by different
    amounts and scattered. Lashes at the canthi still keep their open angle when closed: the canthus skin barely
    turns in blink model 2; turning those lashes down regardless drives their base into the lid margin.)"""
    tri = np.asarray(grooming.parts()["lashes"]["anchor"]["tri"])
    R = _rotation_between(_smoothed(root_normals(P_rest, tri)), _smoothed(root_normals(P_closed, tri)))
    rel = c_rest - c_rest[:, :1]
    return root_closed[:, None, :] + np.einsum("sij,skj->ski", R, rel)


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
