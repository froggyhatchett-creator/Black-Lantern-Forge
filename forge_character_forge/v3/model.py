"""Generator v3 geometry: the neutral adult, per-control deltas, eyes, UV-split body and the corrected blink.

The neutral is hm08 + 0.5 female + 0.5 male macro, uniformly scaled to 1.75 m (the v2 ``height_m`` default) with the
soles at y = 0. Every control delta is linear (MakeHuman targets are linear deltas) and keeps the soles on the floor.
All arrays are over base.obj's full vertex list (body + helpers), so joints, which are helper-vertex means, follow.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from forge_character_forge.v3 import controls, mh

HEIGHT_M = 1.75
BLINK_UNITS = {"l": "LeftUpperLidClosed", "r": "RightUpperLidClosed"}
LOWER_LID = {"l": "LeftLowerLidUp", "r": "RightLowerLidUp"}
BLINK_K = 1.2        # closing factor on the pose unit's 33.2 deg upper-lid rotation (angle-weighted rotation travels less)
UNTANGLE_ROUNDS = 12


@lru_cache(maxsize=None)
def body_vertex_ids() -> np.ndarray:
    _, fv, *_ = mh.base_obj()
    return np.unique(fv)


def _soles(v: np.ndarray) -> float:
    return float(v[body_vertex_ids(), 1].min())


@lru_cache(maxsize=None)
def _frame() -> tuple[float, float]:
    v0, *_ = mh.base_obj()
    raw = v0 + mh.target_sum(len(v0), controls.NEUTRAL)
    b = raw[body_vertex_ids(), 1]
    return HEIGHT_M / float(b.max() - b.min()), float(b.min())


@lru_cache(maxsize=None)
def neutral() -> np.ndarray:
    v0, *_ = mh.base_obj()
    s, y0 = _frame()
    raw = v0 + mh.target_sum(len(v0), controls.NEUTRAL)
    out = raw.copy()
    out[:, 1] -= y0
    out = out * s
    out.flags.writeable = False
    return out


def targets_delta(weighted) -> np.ndarray:
    """Delta of a weighted target list in neutral space (scaled), soles kept on the floor."""
    v = neutral()
    s, _ = _frame()
    d = mh.target_sum(len(v), weighted) * s
    d[:, 1] -= _soles(v + d)
    return d


def control_delta(key: str, side: str) -> tuple[np.ndarray, float] | None:
    """(delta at the slider end, slider value at that end) for one control side, or None if the side is unused."""
    quality, hi, lo, _ = controls.CONTROLS[key]
    from forge_character_forge.studio_bake import BODY_RANGES, FACE_RANGES
    group, name = key.split(".")
    rmin, rmax = (BODY_RANGES if group == "body" else FACE_RANGES)[name]
    at = rmax if side == "hi" else rmin
    spec = hi if side == "hi" else lo
    if spec == "scale":
        return neutral() * (at / HEIGHT_M - 1.0), at
    if not spec:
        return None
    return targets_delta(spec), at


# ---------------------------------------------------------------- body surface with UV seams split
@lru_cache(maxsize=None)
def body_surface():
    """(src vertex id per split vertex, uv per split vertex, triangles over split vertices, weld id per split vertex).

    hm08 has UV seams; GPU vertices are split per (vertex, uv) pair so the UVs are preserved exactly. ``weld`` maps
    each split vertex to its first copy so normals can be averaged across seams (no visible seam in shading).
    """
    v0, fv, ft, uv, _ = mh.base_obj()
    pairs = np.stack([fv.ravel(), ft.ravel()], 1)
    uniq, inv = np.unique(pairs, axis=0, return_inverse=True)
    inv = inv.reshape(fv.shape)
    src, uvi = uniq[:, 0], uniq[:, 1]
    tris = np.concatenate([inv[:, [0, 1, 2]], inv[:, [0, 2, 3]]])
    # outward winding (MakeHuman's winding is not assumed)
    p = neutral()[src]
    n = np.cross(p[tris[:, 1]] - p[tris[:, 0]], p[tris[:, 2]] - p[tris[:, 0]])
    if (np.sum(n * (p[tris].mean(1) - p.mean(0)), 1) > 0).mean() < 0.5:
        tris = tris[:, ::-1]
    first = {}
    weld = np.array([first.setdefault(int(s), k) for k, s in enumerate(src)], np.int64)
    return src, uv[uvi], np.ascontiguousarray(tris), weld


# ---------------------------------------------------------------- eyes
@lru_cache(maxsize=None)
def eye_parts():
    """Split the eye proxy into eye_l/r (inner shell: sclera and iris) and cornea_l/r (outer shell, bulged)."""
    *_, tris = mh.eye_proxy()
    n = int(tris.max()) + 1
    parent = np.arange(n)

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for a, b, c in tris:
        parent[find(a)] = find(b)
        parent[find(b)] = find(c)
    comp = np.array([find(i) for i in range(n)])
    pos = mh.fit_eyes(neutral())
    out = {}
    for cid in np.unique(comp):
        ids = np.nonzero(comp == cid)[0]
        side = "l" if pos[ids, 0].mean() > 0 else "r"
        out.setdefault(side, []).append(ids)
    parts = {}
    for side, (a, b) in out.items():
        # the outer shell reaches further forward: cornea
        cornea, eye = (a, b) if pos[a, 2].max() > pos[b, 2].max() else (b, a)
        for name, ids in ((f"eye_{side}", eye), (f"cornea_{side}", cornea)):
            remap = -np.ones(n, np.int64)
            remap[ids] = np.arange(len(ids))
            t = tris[np.all(np.isin(tris, ids), 1)]
            parts[name] = (ids, remap[t])
    return parts


def sphere_fit(p: np.ndarray) -> tuple[np.ndarray, float]:
    A = np.c_[2 * p, np.ones(len(p))]
    s = np.linalg.lstsq(A, (p ** 2).sum(1), rcond=None)[0]
    c = s[:3]
    return c, float(np.sqrt(s[3] + c @ c))


# ---------------------------------------------------------------- blink
def _rot_x(deg):
    a = np.radians(deg)
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def lid_pose(v: np.ndarray, side: str, k: float = 1.0, mode: str = "angle", lower: float = 0.0) -> np.ndarray:
    """Close one eye's lids.

    mode "lbs": MakeHuman's bone skinning (vertex = blend of rotated and rest positions; partially weighted vertices
    travel along chords, inside the eyeball, which crumples the lid). mode "angle": each vertex rotates by its weight
    times the angle about the lid pivot, so it stays at its distance from the eyeball centre (corrective, used by v3).
    """
    out = v.copy()
    jp = mh.joint_positions(v)
    W = mh.skin_weights()
    S = side.upper()
    units = [(mh.bvh_pose_unit(BLINK_UNITS[side]), k)]
    if lower:
        units.append((mh.bvh_pose_unit(LOWER_LID[side]), lower))
    for rots, kk in units:
        for bone, (rx, _, _) in rots.items():
            if not bone.endswith("." + S) or bone not in W:
                continue
            head = mh.bone_head(bone, jp)
            p = np.asarray(W[bone], float)
            idx, w = p[:, 0].astype(np.int64), p[:, 1]
            rel = out[idx] - head
            if mode == "lbs":
                moved = rel @ _rot_x(rx * kk).T
                out[idx] += (moved - rel) * w[:, None]
            else:
                for i, (r, ww) in enumerate(zip(rel, w)):
                    out[idx[i]] = head + _rot_x(rx * kk * ww) @ r
    return out


CORRECTIVE_RINGS = 2  # the blink corrective may also move this many vertex rings around the lid bones' region


def lid_region(side: str, rings: int = 0) -> np.ndarray:
    """Skin vertices weighted to one eye's lid bones, optionally grown by ``rings`` edge rings."""
    W = mh.skin_weights()
    S = side.upper()
    ids = [np.asarray(W[b], float)[:, 0].astype(np.int64) for b in ("orbicularis03." + S, "orbicularis04." + S) if b in W]
    region = np.intersect1d(np.concatenate(ids), body_vertex_ids())  # skin only (helpers are not rendered)
    nb = _neighbours()
    for _ in range(rings):
        region = np.unique(np.concatenate([region] + [np.fromiter(nb[int(i)], np.int64) for i in region]))
    return region


@lru_cache(maxsize=None)
def _neighbours():
    _, fv, *_ = mh.base_obj()
    nb: dict[int, set] = {}
    for q in fv:
        for a, b in zip(q, np.roll(q, 1)):
            nb.setdefault(int(a), set()).add(int(b))
            nb.setdefault(int(b), set()).add(int(a))
    return nb


def relax(d: np.ndarray, region: np.ndarray, iters: int = 6, lam: float = 0.5, fixed=()) -> np.ndarray:
    """Laplacian smoothing of a displacement field on a vertex region (boundary of the region and ``fixed`` held)."""
    nb = _neighbours()
    rs = set(int(i) for i in region)
    fx = set(int(i) for i in fixed)
    inner = [int(i) for i in region if int(i) not in fx and all(j in rs for j in nb.get(int(i), ()))]
    lists = [list(nb[int(i)]) for i in inner]
    d = d.copy()
    for _ in range(iters):
        new = d.copy()
        for i, js in zip(inner, lists):
            new[i] = d[i] + lam * (d[js].mean(0) - d[i])
        d = new
    return d


def _flipped_vertices(v: np.ndarray, d: np.ndarray, region: np.ndarray) -> np.ndarray:
    _, fv, *_ = mh.base_obj()
    t = np.concatenate([fv[:, [0, 1, 2]], fv[:, [0, 2, 3]]])
    t = t[np.isin(t, region).any(1)]
    c = v + d
    n0 = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    n1 = np.cross(c[t[:, 1]] - c[t[:, 0]], c[t[:, 2]] - c[t[:, 0]])
    return np.unique(t[np.sum(n0 * n1, 1) <= 0])


def _keep_off_cornea(v, d, region, side):
    eye = eye_parts()[f"cornea_{side}"][0]
    c, R = sphere_fit(mh.fit_eyes(v)[eye])
    r_open = np.linalg.norm(v[region] - c, axis=1)
    p = v[region] + d[region]
    r = np.linalg.norm(p - c, axis=1)
    need = np.minimum(r_open, R * 1.003)
    push = (r < need) & (np.linalg.norm(d[region], axis=1) > 1e-6)
    p[push] = c + (p[push] - c) / r[push, None] * need[push, None]
    d = d.copy()
    d[region] = p - v[region]
    return d


def blink_delta(v: np.ndarray, side: str, k: float = BLINK_K, corrected: bool = True, lower: float = 0.0) -> np.ndarray:
    """Blink morph delta (closed minus open) for one eye on a base ``v``.

    Corrected (v3): angle-weighted lid rotation (no chord collapse), Laplacian relaxation of the displacement over
    the lid region, lid vertices kept off the cornea, then local untangling of any triangle that still folds over.
    """
    if not corrected:
        return lid_pose(v, side, k, mode="lbs") - v
    region = lid_region(side, CORRECTIVE_RINGS)
    d = lid_pose(v, side, k, mode="angle", lower=lower) - v
    d = _keep_off_cornea(v, relax(d, region), region, side)
    nb = _neighbours()
    for _ in range(UNTANGLE_ROUNDS):
        bad = _flipped_vertices(v, d, region)
        if not len(bad):
            break
        ring = np.unique(np.concatenate([bad] + [np.fromiter(nb[int(i)], np.int64) for i in bad]))
        ring = np.intersect1d(ring, region)
        grow = np.intersect1d(np.concatenate([ring] + [np.fromiter(nb[int(i)], np.int64) for i in ring]), region)
        d = relax(d, grow, iters=2)  # only lid vertices move
        d = _keep_off_cornea(v, d, region, side)
    return d


BLINK_GRID = [(k, lower) for lower in (0.0, 0.5) for k in (1.0, 1.1, 1.2, 1.3, 1.4, 1.5)]


def fit_blink(v: np.ndarray, target: float = 0.005):
    """Corrected blink fitted to the eye shape of ``v`` (a fixed angle under-closes large eyes and over-closes small
    ones). Grid over the upper-lid closing factor and a lower-lid raise; the choice closes the eye (front-view
    eyeball exposure <= ``target``) with the fewest folded lid triangles, else the smallest exposure.
    Returns (delta, {"factor", "lower", "exposure", "flipped"})."""
    from forge_character_forge.v3 import metrics
    open_px = max(metrics.eye_exposure_pixels(v), 1)
    region = np.concatenate([lid_region(s, CORRECTIVE_RINGS) for s in "lr"])
    best = None
    for k, lower in BLINK_GRID:
        d = blink_delta(v, "l", k, lower=lower) + blink_delta(v, "r", k, lower=lower)
        e = metrics.eye_exposure_pixels(v + d) / open_px
        f = metrics.tri_quality(v, v + d, region)["flipped"]
        score = (e > target, f if e <= target else e, k)
        if best is None or score < best[0]:
            best = (score, d, {"factor": k, "lower": lower, "exposure": round(e, 4), "flipped": f})
    return best[1], best[2]


# ---------------------------------------------------------------- blink model 2 (Phase 4A)
# The Phase 1-3 blink rotated each lid by one global angle (a factor on MakeHuman's pose unit) chosen from a coarse
# grid by front-view exposure. An almond opening cannot close evenly that way: the middle overshoots past the lower
# lid while the corners still close, which folds the lower lid; the grid choice also jumps between neighbouring
# characters, so correctives built from it summed badly. Model 2 closes every column of the opening exactly:
BLINK_MODEL = 2
CLOSE_AT = 0.3        # the lids meet 30 % of the way up from the lower margin (the upper lid does most of the travel)
CLOSE_OVERLAP = 0.03  # rad past the meeting line: lid edges are thick, so the margins overlap slightly to hide the eye
FORNIX = (0.0012, 3.0, 15.0)
MARGIN_MIN_W = 0.2    # margin samples must carry at least this lid-bone weight
CANTHUS_TURN = 0.5    # turn at the canthus vertices relative to the nearest margin sample (0 left a gap at the corners
                      # of wide-set eyes; 1 folds the corners)  # lining within 1.2 mm of the eyeball, 3-15 deg past a margin, is anchored (see below)


@lru_cache(maxsize=None)
def lid_margins() -> dict:
    """Per eye and lid: base-vertex ids of the lid margin, ordered across the opening (found once on the neutral;
    the topology is fixed, so every character uses the same ids)."""
    from forge_character_forge.v3 import grooming
    m, _ = grooming._lid_margins()
    return m


@lru_cache(maxsize=None)
def _lid_bone_weights(side: str):
    W = mh.skin_weights()
    out = []
    for b in (f"orbicularis03.{side.upper()}", f"orbicularis04.{side.upper()}"):
        w = np.zeros(len(neutral()))
        q = np.asarray(W[b], float)
        w[q[:, 0].astype(np.int64)] = q[:, 1]
        out.append(w)
    return out


def _smoothstep(x):
    t = np.clip(x, 0, 1)
    return t * t * (3 - 2 * t)


def blink_closed(v: np.ndarray, side: str) -> np.ndarray:
    """Blink model 2: closed minus open for one eye of character ``v`` (all base vertices).

    Lid vertices turn about the eyeball centre (an axis along x), so lid skin keeps its distance from the eyeball.
    Per column across the opening (lateral position x), the upper margin turns down and the lower margin up until
    they meet at ``CLOSE_AT`` of the opening (plus ``CLOSE_OVERLAP``); every lid vertex turns by its MakeHuman lid-bone
    weight relative to the margin's weight in its column, so the lid keeps MakeHuman's falloff toward the crease and
    cheek but closes evenly from corner to corner. The lining that wraps from the margins back onto the eyeball (the
    fornix) is anchored to the eyeball beyond a few degrees past the margin, as in a real eye; without that it is
    dragged along unevenly and folds. Then the existing relaxation, keep-off-cornea and untangling passes.
    Continuous in the geometry (no grid choice), so correctives between characters change smoothly."""
    c, R = sphere_fit(mh.fit_eyes(v)[eye_parts()[f"eye_{side}"][0]])
    wu, wl = _lid_bone_weights(side)
    sg = 1.0 if side == "l" else -1.0

    def profile(ids, w):  # margin vertices that carry real lid weight (the ring also holds corner/lining strays)
        ids = ids[w[ids] >= MARGIN_MIN_W]
        r = v[ids] - c
        x = sg * r[:, 0]
        o = np.argsort(x)
        return x[o], np.arctan2(r[o, 1], r[o, 2]), w[ids][o]

    up, lo = lid_margins()[(side, True)], lid_margins()[(side, False)]
    canthi = np.sort(sg * (v[np.r_[up[[0, -1]], lo[[0, -1]]]] - c)[:, 0])[[0, -1]]  # shared end vertices: zero opening
    xu, au, wum = profile(up, wu)
    xl, al, wlm = profile(lo, wl)
    xs = np.unique(np.r_[xu, xl])  # columns where both margins are known: turn amounts there, reduced at the canthi
    AU, AL = np.interp(xs, xu, au), np.interp(xs, xl, al)
    AC = AL + CLOSE_AT * (AU - AL)
    tu = np.maximum(AU - AC + CLOSE_OVERLAP, 0)  # elevation angle the upper margin loses
    tl = np.maximum(AC - AL + CLOSE_OVERLAP, 0)  # and the lower margin gains
    xs = np.r_[canthi[0], xs, canthi[1]]
    tu = np.r_[CANTHUS_TURN * tu[0], tu, CANTHUS_TURN * tu[-1]]
    tl = np.r_[CANTHUS_TURN * tl[0], tl, CANTHUS_TURN * tl[-1]]
    region = lid_region(side, CORRECTIVE_RINGS)
    r = v[region] - c
    x = sg * r[:, 0]
    a = np.arctan2(r[:, 1], r[:, 2])
    turn_u, turn_l = np.interp(x, xs, tu), np.interp(x, xs, tl)
    AU, AL = np.interp(x, xu, au), np.interp(x, xl, al)
    gu = np.clip(wu[region] / np.maximum(np.interp(x, xu, wum), 1e-3), 0, 1)
    gl = np.clip(wl[region] / np.maximum(np.interp(x, xl, wlm), 1e-3), 0, 1)
    th = turn_u * gu - turn_l * gl
    dist = np.linalg.norm(r, axis=1) - R
    past = np.degrees(np.maximum(a - AU, 0) + np.maximum(AL - a, 0))
    lining = 1 - _smoothstep((dist - FORNIX[0] * 0.5) / (FORNIX[0] * 0.5))
    th *= 1 - lining * _smoothstep((past - FORNIX[1]) / (FORNIX[2] - FORNIX[1]))
    ct, st = np.cos(th), np.sin(th)  # turn about x through c: the elevation angle atan2(y, z) decreases by th
    q = r.copy()
    q[:, 1] = r[:, 1] * ct - r[:, 2] * st
    q[:, 2] = r[:, 1] * st + r[:, 2] * ct
    d = np.zeros_like(v)
    d[region] = q - r
    margin = np.r_[up[wu[up] >= MARGIN_MIN_W], lo[wl[lo] >= MARGIN_MIN_W]]  # land exactly on the line
    d = _keep_off_cornea(v, relax(d, region, fixed=margin), region, side)
    nb = _neighbours()
    for _ in range(UNTANGLE_ROUNDS):
        bad = _flipped_vertices(v, d, region)
        if not len(bad):
            break
        ring = np.intersect1d(np.unique(np.concatenate([bad] + [np.fromiter(nb[int(i)], np.int64) for i in bad])), region)
        grow = np.intersect1d(np.concatenate([ring] + [np.fromiter(nb[int(i)], np.int64) for i in ring]), region)
        d = _keep_off_cornea(v, relax(d, grow, iters=2), region, side)
    return _clear_chords(v, d, region, side)


CHORD_TS = (0.25, 0.5, 0.75, 1.0)


def _eye_depth(p, c, R, cc, CR):
    """Signed distance outside the eye: eyeball sphere, and the cornea sphere over its forward cap (m)."""
    de = np.linalg.norm(p - c, axis=1) - R
    rel = p - cc
    cap = rel[:, 2] / np.maximum(np.linalg.norm(rel, axis=1), 1e-12) > np.cos(0.75)
    return np.minimum(de, np.where(cap, np.linalg.norm(rel, axis=1) - CR, 1.0))


def _clear_chords(v, d, region, side, rounds=8, spread=6):
    """A morph target moves every vertex on a straight line, but the lid turns on an arc: halfway, the straight path
    of the lid edge cuts into the cornea bulge and the eye shows through the lid. Where a lid vertex's path (or its
    closed position) would come closer to the eye than when open (or than 0.2 mm), its closed position is pushed out
    from the eyeball centre just enough
    (then smoothed over its neighbours), so no in-between weight goes deeper into the eye than the open lid. The
    hidden lining on or inside the eyeball sphere is left alone."""
    ev = mh.fit_eyes(v)
    c, R = sphere_fit(ev[eye_parts()[f"eye_{side}"][0]])
    cc, CR = sphere_fit(ev[eye_parts()[f"cornea_{side}"][0]])
    rel = v[region] - c  # the lid in front of the eyeball, off its sphere (margins resting on the cornea included)
    ids = region[(np.linalg.norm(rel, axis=1) - R > 0.0004) & (rel[:, 2] > 0)]
    for _ in range(rounds):
        p0, p1 = v[ids], v[ids] + d[ids]
        floor = np.minimum(_eye_depth(p0, c, R, cc, CR), 0.0002)  # as far out as when open, up to 0.2 mm
        need = np.zeros(len(ids))
        for t in CHORD_TS:
            short = floor - _eye_depth(p0 + t * (p1 - p0), c, R, cc, CR)
            need = np.maximum(need, short / t)  # pushing the end out by x lifts the path at t by about t * x
        if need.max() < 1e-5:
            break
        push = np.zeros_like(v)
        out = p1 - c
        push[ids] = out / np.linalg.norm(out, axis=1, keepdims=True) * need[:, None]
        push = relax(push, region, iters=spread)
        d = d + push
    return d


def blink(v: np.ndarray):
    """Blink model 2 for both eyes: (delta, info)."""
    return blink_closed(v, "l") + blink_closed(v, "r"), {"model": BLINK_MODEL, "close_at": CLOSE_AT, "overlap": CLOSE_OVERLAP}
