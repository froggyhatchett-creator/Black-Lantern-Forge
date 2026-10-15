"""Surface extraction (naive surface nets) and multi-resolution region stitching.

Pipeline for the template:
  1. Each region (body, head, hand_l, hand_r) is meshed on its own axis-aligned
     grid, with the field intersected with (region) or carved by (body) the
     region's cut volume, so every piece is a closed capped surface.
  2. Cap faces are deleted, leaving exactly one open boundary loop per cut.
  3. Loops are snapped onto their cut plane and the skin contour.
  4. Matching loops (body/head, body/hand) are zipped with a triangle strip.
  5. The joined mesh is relaxed tangentially and projected back onto the field.
"""

from __future__ import annotations

import numpy as np

# cube corner offsets (i, j, k) and the 12 cube edges as corner index pairs
_CORNERS = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0], [0, 0, 1], [1, 0, 1], [0, 1, 1], [1, 1, 1]])
_EDGES = [(0, 1), (2, 3), (4, 5), (6, 7), (0, 2), (1, 3), (4, 6), (5, 7), (0, 4), (1, 5), (2, 6), (3, 7)]


def sample_grid(fn, lo: np.ndarray, shape: tuple[int, int, int], h: float, coarse: int = 4) -> np.ndarray:
    """Evaluate fn on a regular grid, exactly only inside a narrow band found from a coarse pass."""
    nx, ny, nz = shape
    cx, cy, cz = (nx - 1) // coarse + 2, (ny - 1) // coarse + 2, (nz - 1) // coarse + 2
    H = h * coarse
    gi = np.stack(np.meshgrid(np.arange(cx), np.arange(cy), np.arange(cz), indexing="ij"), -1).reshape(-1, 3)
    cv = fn(lo + gi * H).reshape(cx, cy, cz)
    # trilinear upsample
    fx = np.arange(nx) / coarse
    fy = np.arange(ny) / coarse
    fz = np.arange(nz) / coarse
    ix, iy, iz = fx.astype(int), fy.astype(int), fz.astype(int)
    tx, ty, tz = fx - ix, fy - iy, fz - iz
    v = np.zeros((nx, ny, nz))
    for ox in (0, 1):
        wx = (tx if ox else 1 - tx)[:, None, None]
        for oy in (0, 1):
            wy = (ty if oy else 1 - ty)[None, :, None]
            for oz in (0, 1):
                wz = (tz if oz else 1 - tz)[None, None, :]
                v += wx * wy * wz * cv[np.ix_(ix + ox, iy + oy, iz + oz)]
    band = np.abs(v) < 1.9 * H
    idx = np.argwhere(band)
    if len(idx):
        out = []
        for start in range(0, len(idx), 400_000):
            chunk = idx[start:start + 400_000]
            out.append(fn(lo + chunk * h))
        v[band] = np.concatenate(out)
    return v


def surface_nets(values: np.ndarray, lo: np.ndarray, h: float) -> tuple[np.ndarray, np.ndarray]:
    """Return (vertices, quads). Quads are wound counter-clockwise seen from outside (d > 0)."""
    nx, ny, nz = values.shape
    inside = values < 0.0
    corner_in = [inside[o[0]:nx - 1 + o[0], o[1]:ny - 1 + o[1], o[2]:nz - 1 + o[2]] for o in _CORNERS]
    any_in = np.zeros_like(corner_in[0])
    all_in = np.ones_like(corner_in[0])
    for c in corner_in:
        any_in |= c
        all_in &= c
    active = any_in & ~all_in
    cell_idx = np.argwhere(active)
    vid = -np.ones(active.shape, dtype=np.int64)
    vid[active] = np.arange(len(cell_idx))
    # vertex position: mean of edge crossings
    acc = np.zeros((len(cell_idx), 3))
    cnt = np.zeros(len(cell_idx))
    ci, cj, ck = cell_idx[:, 0], cell_idx[:, 1], cell_idx[:, 2]
    for a, b in _EDGES:
        oa, ob = _CORNERS[a], _CORNERS[b]
        va = values[ci + oa[0], cj + oa[1], ck + oa[2]]
        vb = values[ci + ob[0], cj + ob[1], ck + ob[2]]
        cross = (va < 0) != (vb < 0)
        tt = np.where(cross, va / np.where(cross, va - vb, 1.0), 0.0)
        p = oa[None, :] + (ob - oa)[None, :] * tt[:, None]
        acc += np.where(cross[:, None], p, 0.0)
        cnt += cross
    verts = lo + (cell_idx + acc / cnt[:, None]) * h
    quads = []
    # edges along axis a: node (i,j,k) -> +a. The 4 cells sharing that edge.
    for axis in range(3):
        u, w = [(1, 2), (0, 2), (0, 1)][axis]
        sl = [slice(None)] * 3
        sl[axis] = slice(0, values.shape[axis] - 1)
        v0 = values[tuple(sl)]
        sl2 = [slice(None)] * 3
        sl2[axis] = slice(1, None)
        v1 = values[tuple(sl2)]
        cross = (v0 < 0) != (v1 < 0)
        # exclude edges on the grid border in u or w (need cells on both sides)
        idx = np.argwhere(cross)
        keep = (idx[:, u] >= 1) & (idx[:, w] >= 1) & (idx[:, u] < values.shape[u] - 1) & (idx[:, w] < values.shape[w] - 1)
        idx = idx[keep]
        if not len(idx):
            continue
        flip = v0[tuple(idx.T)] < 0  # inside at the low end -> normal points +axis
        cells = []
        for du, dw in ((-1, -1), (0, -1), (0, 0), (-1, 0)):
            c = idx.copy()
            c[:, u] += du
            c[:, w] += dw
            cells.append(vid[tuple(c.T)])
        q = np.stack(cells, axis=1)
        # base winding (u,w) order gives normal along +axis for right-handed (u, w, axis) triples
        q = np.where(flip[:, None], q, q[:, ::-1])
        if axis == 1:  # (x, z, y) is left-handed -> reverse
            q = q[:, ::-1]
        quads.append(q)
    quads = np.concatenate(quads) if quads else np.zeros((0, 4), dtype=np.int64)
    if np.any(quads < 0):
        raise RuntimeError("surface nets produced a quad with a missing vertex")
    return verts, quads


def quads_to_tris(verts: np.ndarray, quads: np.ndarray) -> np.ndarray:
    """Split along the shorter diagonal."""
    a, b, c, d = quads.T
    d1 = np.linalg.norm(verts[a] - verts[c], axis=1)
    d2 = np.linalg.norm(verts[b] - verts[d], axis=1)
    t1 = np.where((d1 <= d2)[:, None], np.stack([a, b, c], 1), np.stack([a, b, d], 1))
    t2 = np.where((d1 <= d2)[:, None], np.stack([a, c, d], 1), np.stack([b, c, d], 1))
    return np.concatenate([t1, t2])


def mesh_box(fn, lo, hi, h, coarse=4):
    lo = np.asarray(lo, float)
    hi = np.asarray(hi, float)
    shape = tuple(int(np.ceil((hi[i] - lo[i]) / h)) + 1 for i in range(3))
    vals = sample_grid(fn, lo, shape, h, coarse)
    # the grid border must be outside
    if (vals[0] < 0).any() or (vals[-1] < 0).any() or (vals[:, 0] < 0).any() or (vals[:, -1] < 0).any() \
            or (vals[:, :, 0] < 0).any() or (vals[:, :, -1] < 0).any():
        raise RuntimeError("surface crosses the meshing box border; enlarge the box")
    v, q = surface_nets(vals, lo, h)
    return v, quads_to_tris(v, q)


# ---------------------------------------------------------------- topology helpers

def compact(verts: np.ndarray, tris: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    used = np.unique(tris)
    remap = -np.ones(len(verts), dtype=np.int64)
    remap[used] = np.arange(len(used))
    return verts[used], remap[tris]


def edge_map(tris: np.ndarray) -> dict:
    out: dict = {}
    for f, (a, b, c) in enumerate(tris.tolist()):
        for u, v in ((a, b), (b, c), (c, a)):
            out.setdefault((u, v), []).append(f)
    return out


def boundary_loops(tris: np.ndarray) -> list[list[int]]:
    """Directed boundary edges (u->v as they appear in faces with no twin), chained into loops."""
    directed = set()
    for a, b, c in tris.tolist():
        directed.update(((a, b), (b, c), (c, a)))
    nxt: dict = {}
    for u, v in directed:
        if (v, u) not in directed:
            if u in nxt:
                raise RuntimeError("non-manifold boundary vertex")
            nxt[u] = v
    loops, seen = [], set()
    for start in list(nxt):
        if start in seen:
            continue
        loop, u = [], start
        while u not in seen:
            seen.add(u)
            loop.append(u)
            u = nxt[u]
        loops.append(loop)
    return loops


def remove_dangling(tris: np.ndarray) -> np.ndarray:
    """Drop faces that share fewer than two edges with the rest (cap remnants)."""
    for _ in range(20):
        und: dict = {}
        for a, b, c in tris.tolist():
            for u, v in ((a, b), (b, c), (c, a)):
                key = (u, v) if u < v else (v, u)
                und[key] = und.get(key, 0) + 1
        bad = []
        for i, (a, b, c) in enumerate(tris.tolist()):
            shared = sum(und[(u, v) if u < v else (v, u)] >= 2 for u, v in ((a, b), (b, c), (c, a)))
            if shared < 2:
                bad.append(i)
        if not bad:
            return tris
        tris = np.delete(tris, bad, axis=0)
    return tris


def check_closed_manifold(tris: np.ndarray) -> dict:
    directed: dict = {}
    for a, b, c in tris.tolist():
        for e in ((a, b), (b, c), (c, a)):
            directed[e] = directed.get(e, 0) + 1
    dup = sum(1 for k, n in directed.items() if n > 1)
    unpaired = sum(1 for (u, v) in directed if (v, u) not in directed)
    return {"duplicate_directed_edges": dup, "boundary_edges": unpaired,
            "closed_oriented": dup == 0 and unpaired == 0}


def vertex_normals(verts: np.ndarray, tris: np.ndarray) -> np.ndarray:
    fn = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
    n = np.zeros_like(verts)
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return n / np.maximum(ln, 1e-20)


def neighbors(n_verts: int, tris: np.ndarray):
    """CSR adjacency (indptr, indices) of the undirected edge graph."""
    e = np.concatenate([tris[:, [0, 1]], tris[:, [1, 2]], tris[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    e = np.unique(e, axis=0)
    indptr = np.zeros(n_verts + 1, dtype=np.int64)
    np.add.at(indptr, e[:, 0] + 1, 1)
    indptr = np.cumsum(indptr)
    return indptr, e[:, 1]


def laplacian(values: np.ndarray, adj) -> np.ndarray:
    indptr, idx = adj
    deg = np.diff(indptr)
    rows = np.repeat(np.arange(len(deg)), deg)
    s = np.zeros_like(values)
    np.add.at(s, rows, values[idx])
    return s / np.maximum(deg, 1)[:, None] if values.ndim == 2 else s / np.maximum(deg, 1)


def relax(verts, tris, field, iterations=3, strength=0.5, project=True, fixed=None):
    adj = neighbors(len(verts), tris)
    v = verts.copy()
    for _ in range(iterations):
        n = vertex_normals(v, tris)
        lap = laplacian(v, adj) - v
        lap -= n * np.sum(lap * n, axis=1, keepdims=True)  # tangential only
        if fixed is not None:
            lap[fixed] = 0.0
        v = v + strength * lap
        if project:
            v = field.project(v, iterations=2, max_step=0.01)
    return v


# ---------------------------------------------------------------- cutting & stitching

def delete_cap(verts, tris, field_fn, region_sdf):
    """Delete faces lying on the boundary of a cut volume (region_sdf ~ 0 there, field < 0)."""
    c = verts[tris].mean(axis=1)
    rs = np.abs(region_sdf(c))
    d = field_fn(c)
    cap = (rs < np.abs(d)) & (d < 0) & (rs < 0.02)
    tris = tris[~cap]
    return remove_dangling(tris)


def snap_loop(verts, loop, field, plane_point, plane_normal, iterations=6):
    """Move loop vertices onto the plane, then onto the field contour within the plane."""
    n = plane_normal / np.linalg.norm(plane_normal)
    p = verts[loop].copy()
    for _ in range(iterations):
        p -= ((p - plane_point) @ n)[:, None] * n
        d = field.evaluate(p)
        g = field.gradient(p)
        g -= (g @ n)[:, None] * n
        gn2 = np.maximum(np.sum(g * g, axis=1), 1e-10)
        step = (d / gn2)[:, None] * g
        sl = np.linalg.norm(step, axis=1)
        step *= np.where(sl > 0.005, 0.005 / np.maximum(sl, 1e-12), 1.0)[:, None]
        p -= step
    p -= ((p - plane_point) @ n)[:, None] * n
    verts[loop] = p


def zipper(verts, loop_a: list[int], loop_b: list[int], axis_point, axis_normal) -> np.ndarray:
    """Triangulate between two boundary loops that face each other across a thin gap.

    loop_a and loop_b are in face-edge order (as boundary_loops returns them); they run in
    opposite rotational senses, so loop_b is reversed before walking.
    """
    n = axis_normal / np.linalg.norm(axis_normal)
    ref = np.cross(n, [1.0, 0.0, 0.0] if abs(n[0]) < 0.9 else [0.0, 1.0, 0.0])
    ref /= np.linalg.norm(ref)
    ref2 = np.cross(n, ref)

    def angles(loop):
        q = verts[loop] - axis_point
        return np.arctan2(q @ ref2, q @ ref)

    A = list(loop_a)
    B = list(reversed(loop_b))
    aa = angles(A)
    # orient both loops to run with increasing angle
    if np.sum(np.diff(np.unwrap(aa))) < 0:
        A = A[::-1]
        B = B[::-1]
        flip = True
    else:
        flip = False
    aa = angles(A)
    ab = angles(B)
    ia = int(np.argmin(np.abs(aa)))
    ib = int(np.argmin(np.abs(ab)))
    A = A[ia:] + A[:ia]
    B = B[ib:] + B[:ib]
    na, nb = len(A), len(B)
    i = j = 0
    tris = []
    while i < na or j < nb:
        a0, a1 = A[i % na], A[(i + 1) % na]
        b0, b1 = B[j % nb], B[(j + 1) % nb]
        if i >= na:
            adv_a = False
        elif j >= nb:
            adv_a = True
        else:
            adv_a = np.linalg.norm(verts[a1] - verts[b0]) <= np.linalg.norm(verts[b1] - verts[a0])
        if adv_a:
            tris.append((a1, a0, b0))
            i += 1
        else:
            tris.append((b0, b1, a0))
            j += 1
    tris = np.array(tris, dtype=np.int64)
    if flip:
        tris = tris[:, ::-1]
    return tris


def _bad_vertices(n_verts: int, tris: np.ndarray) -> set:
    """Vertices on non-manifold edges, or whose face fan is not a single cycle/strip."""
    directed: dict = {}
    for f, (a, b, c) in enumerate(tris.tolist()):
        for e in ((a, b), (b, c), (c, a)):
            directed.setdefault(e, []).append(f)
    bad = set()
    for (u, v), fs in directed.items():
        if len(fs) > 1:
            bad.update((u, v))
    # link check: around v, map each incident face's next-edge; must form one chain
    nxt: dict = {}
    for a, b, c in tris.tolist():
        for v, p, q in ((a, b, c), (b, c, a), (c, a, b)):
            d = nxt.setdefault(v, {})
            if p in d:
                bad.add(v)
            d[p] = q
    for v, d in nxt.items():
        if v in bad:
            continue
        start = next(iter(d))
        cur, steps = start, 0
        while cur in d and steps <= len(d):
            cur = d[cur]
            steps += 1
            if cur == start:
                break
        if steps != len(d):
            # either open (boundary vertex) or multiple fans; count chains
            starts = set(d) - set(d.values())
            if len(starts) > 1 or (not starts and steps != len(d)):
                bad.add(v)
    return bad


def repair(verts: np.ndarray, tris: np.ndarray, max_rounds: int = 6) -> tuple[np.ndarray, np.ndarray, int]:
    """Remove non-manifold spots and fan-fill the resulting small holes. Returns (verts, tris, n_repaired)."""
    repaired = 0
    verts = verts.copy()
    for _ in range(max_rounds):
        bad = _bad_vertices(len(verts), tris)
        loops = []
        if not bad:
            try:
                loops = boundary_loops(tris)
            except RuntimeError:
                loops = None
            if loops == []:
                return verts, tris, repaired
        if bad:
            repaired += len(bad)
            badarr = np.array(sorted(bad))
            # grow one ring so the hole has a clean rim
            touch = np.isin(tris, badarr).any(axis=1)
            ring = np.unique(tris[touch])
            touch = np.isin(tris, ring).any(axis=1)
            tris = remove_dangling(tris[~touch])
        try:
            loops = boundary_loops(tris)
        except RuntimeError:
            continue
        new_v, new_t = [], []
        for lp in loops:
            c = verts[lp].mean(axis=0)
            ci = len(verts) + len(new_v)
            new_v.append(c)
            for i in range(len(lp)):
                u, v = lp[i], lp[(i + 1) % len(lp)]
                new_t.append((v, u, ci))
        if new_v:
            verts = np.concatenate([verts, np.array(new_v)])
            tris = np.concatenate([tris, np.array(new_t, dtype=np.int64)])
    raise RuntimeError("mesh repair did not converge")


def clean_boundary(tris: np.ndarray, max_rounds: int = 30) -> np.ndarray:
    """Peel faces around boundary vertices that have more than one outgoing boundary edge."""
    for _ in range(max_rounds):
        directed = set()
        for a, b, c in tris.tolist():
            directed.update(((a, b), (b, c), (c, a)))
        out: dict = {}
        for u, v in directed:
            if (v, u) not in directed:
                out[u] = out.get(u, 0) + 1
        bad = [u for u, n in out.items() if n > 1]
        if not bad:
            return tris
        touch = np.isin(tris, np.array(bad)).any(axis=1)
        tris = remove_dangling(tris[~touch])
    raise RuntimeError("boundary cleanup did not converge")
