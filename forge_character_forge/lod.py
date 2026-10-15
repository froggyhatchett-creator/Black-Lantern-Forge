"""Level-of-detail generation by quadric-error edge collapse onto existing vertices (subset placement).

Because a collapse keeps one of its two endpoints, an LOD is fully described by (kept vertex indices,
new triangles).  Computed once per topology, it applies to every character sharing that topology, and
every per-vertex attribute (skin weights, colors, UV source, morph deltas) carries over by indexing.
This module is asset-agnostic: it works on any closed or open triangle mesh.
"""

from __future__ import annotations

import hashlib
import heapq
from pathlib import Path

import numpy as np


def _face_quadrics(v: np.ndarray, t: np.ndarray) -> np.ndarray:
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a)
    area = np.linalg.norm(n, axis=1)
    n = n / np.maximum(area, 1e-20)[:, None]
    d = -np.sum(n * a, axis=1)
    p = np.concatenate([n, d[:, None]], 1)  # plane (a,b,c,d)
    K = p[:, :, None] * p[:, None, :] * (area * 0.5)[:, None, None]
    return K


def decimate(verts: np.ndarray, tris: np.ndarray, target_tris: int, vertex_weight: np.ndarray | None = None,
             max_normal_turn_deg: float = 60.0) -> tuple[np.ndarray, np.ndarray]:
    """Return (kept_vertex_indices, new_tris indexed into kept list)."""
    v = np.asarray(verts, float)
    t = np.asarray(tris, np.int64).copy()
    nv = len(v)
    Kf = _face_quadrics(v, t)
    Q = np.zeros((nv, 4, 4))
    for k in range(3):
        np.add.at(Q, t[:, k], Kf)
    if vertex_weight is not None:
        Q *= np.asarray(vertex_weight, float)[:, None, None]
    # boundary edges get a perpendicular constraint plane so open borders are preserved
    from collections import defaultdict
    edge_faces = defaultdict(list)
    for f, (a, b, c) in enumerate(t.tolist()):
        for x, y in ((a, b), (b, c), (c, a)):
            edge_faces[(min(x, y), max(x, y))].append(f)
    fn = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    for (x, y), fs in edge_faces.items():
        if len(fs) == 1:
            e = v[y] - v[x]
            n = np.cross(e, fn[fs[0]])
            ln = np.linalg.norm(n)
            if ln > 1e-12:
                n /= ln
                p = np.append(n, -n @ v[x])
                K = np.outer(p, p) * 10.0 * (e @ e)
                Q[x] += K
                Q[y] += K
    vfaces = [set() for _ in range(nv)]
    for f, (a, b, c) in enumerate(t.tolist()):
        vfaces[a].add(f)
        vfaces[b].add(f)
        vfaces[c].add(f)
    alive_f = np.ones(len(t), bool)
    alive_v = np.ones(nv, bool)
    stamp = np.zeros(nv, np.int64)
    hv = np.concatenate([v, np.ones((nv, 1))], 1)

    def cost(u, w):  # collapse u -> w (keep w)
        q = Q[u] + Q[w]
        return float(hv[w] @ q @ hv[w])

    heap = []
    for (x, y) in edge_faces:
        c1, c2 = cost(x, y), cost(y, x)
        if c1 <= c2:
            heap.append((c1, x, y, 0, 0))
        else:
            heap.append((c2, y, x, 0, 0))
    heapq.heapify(heap)
    n_faces = len(t)
    cos_lim = np.cos(np.radians(max_normal_turn_deg))

    def neighbors(x):
        s = set()
        for f in vfaces[x]:
            s.update(t[f].tolist())
        s.discard(x)
        return s

    while n_faces > target_tris and heap:
        c, u, w, su, sw = heapq.heappop(heap)
        if not (alive_v[u] and alive_v[w]) or stamp[u] != su or stamp[w] != sw:
            continue
        shared = vfaces[u] & vfaces[w]
        if not shared:
            continue
        # link condition (keeps the mesh 2-manifold)
        if len(neighbors(u) & neighbors(w)) != len(shared):
            continue
        # reject collapses that flip or sharply turn any remaining face
        ok = True
        for f in vfaces[u] - shared:
            tri = t[f].copy()
            a0, b0, c0 = v[tri[0]], v[tri[1]], v[tri[2]]
            n0 = np.cross(b0 - a0, c0 - a0)
            tri[tri == u] = w
            a1, b1, c1 = v[tri[0]], v[tri[1]], v[tri[2]]
            n1 = np.cross(b1 - a1, c1 - a1)
            l0, l1 = np.linalg.norm(n0), np.linalg.norm(n1)
            if l1 < 1e-14 or (n0 @ n1) < cos_lim * l0 * l1:
                ok = False
                break
        if not ok:
            continue
        for f in shared:
            alive_f[f] = False
            for x in t[f].tolist():
                vfaces[x].discard(f)
            n_faces -= 1
        for f in list(vfaces[u]):
            t[f][t[f] == u] = w
            vfaces[w].add(f)
        vfaces[u].clear()
        alive_v[u] = False
        Q[w] += Q[u]
        stamp[w] += 1
        for x in neighbors(w):
            stamp[x] += 0
            c1, c2 = cost(x, w), cost(w, x)
            if c1 <= c2:
                heapq.heappush(heap, (c1, x, w, int(stamp[x]), int(stamp[w])))
            else:
                heapq.heappush(heap, (c2, w, x, int(stamp[w]), int(stamp[x])))
    nt = t[alive_f]
    keep = np.unique(nt)
    remap = -np.ones(nv, np.int64)
    remap[keep] = np.arange(len(keep))
    return keep, remap[nt]


def cached_decimate(verts, tris, target_tris, vertex_weight=None, cache_dir=None, tag=""):
    key = hashlib.sha256(np.ascontiguousarray(np.asarray(tris, np.int64)).tobytes()
                         + str(target_tris).encode() + tag.encode()
                         + (b"" if vertex_weight is None else np.asarray(vertex_weight, np.float32).tobytes())
                         + Path(__file__).read_bytes()).hexdigest()[:16]
    cache_dir = Path(cache_dir) if cache_dir else Path(__file__).resolve().parent.parent / ".forge_cache"
    path = cache_dir / f"lod_{key}.npz"
    if path.exists():
        z = np.load(path)
        return z["keep"], z["tris"]
    keep, nt = decimate(verts, tris, target_tris, vertex_weight)
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(path, keep=keep, tris=nt)
    return keep, nt


def character_lod(ch, ratio: float, min_tris: int = 2000):
    """A copy of a built Character with decimated parts (same skeleton, materials, morph names).

    The body LOD is computed on the shared template, so its topology is identical for every character;
    other parts are decimated on their current shape."""
    import copy

    from forge_character_forge.gltf import cylindrical_uv_layout
    from forge_character_forge.mesher import vertex_normals

    tpl = ch.template
    out = copy.copy(ch)
    parts = []
    for p in ch.parts:
        if len(p.tris) < min_tris:
            parts.append(p)
            continue
        target = max(int(len(p.tris) * ratio), min_tris // 2)
        if p.name == "body":
            w = np.where(tpl.region_of_vertex == 1, 4.0, np.where(tpl.region_of_vertex >= 2, 3.0, 1.0))
            keep, nt = cached_decimate(tpl.verts, tpl.tris, target, w, tag="body")
        else:
            keep, nt = decimate(p.verts, p.tris, target)
        q = copy.copy(p)
        q.verts = p.verts[keep]
        q.tris = nt
        q.normals = vertex_normals(q.verts, nt)
        q.joints = p.joints[keep]
        q.weights = p.weights[keep]
        q.colors = None if p.colors is None else p.colors[keep]
        q.uvs = None if p.uvs is None else p.uvs[keep]
        q.morphs = {k: d[keep] for k, d in p.morphs.items()}
        q.extras = dict(p.extras, lod_ratio=ratio, lod_source_vertices=int(len(p.verts)))
        if p.name == "body":
            q.uv_layout = cylindrical_uv_layout(tpl.skeleton, tpl.verts[keep], nt, tpl.joints[keep, 0])
        parts.append(q)
    out.parts = parts
    return out
