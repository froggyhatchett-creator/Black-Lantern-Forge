"""Fixed-topology template mesh.

The template is meshed once from the neutral parameter set.  Every character
afterwards reuses its vertices/triangles (same counts, same order) and only
moves vertices, so morph targets, skin weights, UVs and garment bindings stay
valid across edits.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.anatomy import build_field
from forge_character_forge.params import BodyParams, FaceParams
from forge_character_forge.sdf import Field
from forge_character_forge.skeleton import Skeleton, build_skeleton

TEMPLATE_VERSION = 1
BODY_CELL = 0.0095
HEAD_CELL = 0.0030
HAND_CELL = 0.0030
GAP = 0.006


@dataclass
class Region:
    name: str
    plane_point: np.ndarray
    plane_normal: np.ndarray      # points into the region
    ball_center: np.ndarray | None
    ball_radius: float
    cell: float

    def sdf(self, p: np.ndarray, offset: float = 0.0) -> np.ndarray:
        d = -((p - (self.plane_point + self.plane_normal * offset)) @ self.plane_normal)
        if self.ball_center is not None:
            d = np.maximum(d, np.linalg.norm(p - self.ball_center, axis=1) - self.ball_radius)
        return d


def regions_for(skel: Skeleton) -> list[Region]:
    m = skel.marks
    s = m["scale"]
    out = [Region("head", np.array([0.0, m["y_chin"] - 0.014 * s, 0.0]), np.array([0.0, 1.0, 0.0]), None, 0.0,
                  HEAD_CELL)]
    for lab in ("l", "r"):
        wr, el = skel[f"hand_{lab}"], skel[f"lowerarm_{lab}"]
        d = (wr - el) / np.linalg.norm(wr - el)
        out.append(Region(f"hand_{lab}", wr - d * 0.014 * s, d, wr + d * 0.07 * s, 0.17 * s, HAND_CELL))
    return out


def _bbox(field: Field, margin: float):
    lo = np.full(3, np.inf)
    hi = np.full(3, -np.inf)
    for p in field.prims:
        if p.subtract:
            continue
        a, b = p.bounds()
        lo = np.minimum(lo, a)
        hi = np.maximum(hi, b)
    return lo - margin, hi + margin


def _region_bbox(field: Field, region: Region, margin: float):
    lo, hi = _bbox(field, margin)
    if region.ball_center is not None:
        lo = np.maximum(lo, region.ball_center - region.ball_radius - margin)
        hi = np.minimum(hi, region.ball_center + region.ball_radius + margin)
    else:
        lo = lo.copy()
        lo[1] = region.plane_point[1] - margin
    return lo, hi


@dataclass
class Template:
    verts: np.ndarray
    tris: np.ndarray
    region_of_vertex: np.ndarray   # 0 body, 1 head, 2 hand_l, 3 hand_r
    skeleton: Skeleton
    field: Field
    stats: dict
    joints: np.ndarray | None = None
    weights: np.ndarray | None = None
    tags: np.ndarray | None = None        # per-vertex index into tag_names
    tag_names: list | None = None


def vertex_tags(verts: np.ndarray, field: Field) -> tuple[np.ndarray, list]:
    """Name of the primitive whose surface each vertex lies on (its tag, or its bone)."""
    names = sorted({p.tag or p.bone for p in field.prims})
    best = np.full(len(verts), np.inf)
    tag = np.zeros(len(verts), dtype=np.int64)
    for p in field.prims:
        lo, hi = p.bounds()
        mask = np.all((verts >= lo - 0.01) & (verts <= hi + 0.01), axis=1)
        if not mask.any():
            continue
        d = np.abs(p.distance(verts[mask]))
        idx = np.nonzero(mask)[0]
        better = d < best[idx]
        best[idx[better]] = d[better]
        tag[idx[better]] = names.index(p.tag or p.bone)
    return tag, names


def template_params() -> tuple[BodyParams, FaceParams]:
    """Neutral proportions with a moderate bust so every body type has vertex density on the chest."""
    return BodyParams(breast_size=0.6, femininity=0.5), FaceParams()


REGION_IDS = {"body": 0, "head": 1, "hand_l": 2, "hand_r": 3}


def build_template(body: BodyParams | None = None, face: FaceParams | None = None, verbose: bool = False) -> Template:
    body = body or BodyParams()
    face = face or FaceParams()
    t0 = time.perf_counter()
    skel = build_skeleton(body, face)
    field = build_field(body, face, skel)
    regions = regions_for(skel)

    def body_fn(p):
        d = field.evaluate(p)
        for r in regions:
            d = np.maximum(d, -r.sdf(p))
        return d

    pieces = []
    lo, hi = _bbox(field, 0.03)
    v, t = mesher.mesh_box(body_fn, lo, hi, BODY_CELL)
    v, t, nrep = mesher.repair(v, t)
    repairs = {"body": nrep}
    pieces.append(("body", v, t))
    for r in regions:
        def region_fn(p, r=r):
            return np.maximum(field.evaluate(p), r.sdf(p, offset=GAP))
        rlo, rhi = _region_bbox(field, r, 0.02)
        v, t = mesher.mesh_box(region_fn, rlo, rhi, r.cell)
        v, t, nrep = mesher.repair(v, t)
        repairs[r.name] = nrep
        pieces.append((r.name, v, t))
    if verbose:
        print(f"  meshed regions in {time.perf_counter() - t0:.1f}s:",
              {n: (len(v), len(t)) for n, v, t in pieces})

    # delete caps, find loops
    all_v, all_t, rid, loops = [], [], [], {}
    offset = 0
    for name, v, t in pieces:
        if name == "body":
            for r in regions:
                t = mesher.delete_cap(v, t, field.evaluate, r.sdf)
        else:
            r = next(rr for rr in regions if rr.name == name)
            t = mesher.delete_cap(v, t, field.evaluate, lambda p, r=r: r.sdf(p, offset=GAP))
        t = mesher.clean_boundary(t)
        v, t = mesher.compact(v, t)
        lps = mesher.boundary_loops(t)
        if name == "body":
            if len(lps) != len(regions):
                raise RuntimeError(f"body should have {len(regions)} open loops, found {len(lps)}")
            for lp in lps:
                c = v[lp].mean(axis=0)
                r = min(regions, key=lambda rr: abs((c - rr.plane_point) @ rr.plane_normal)
                        + (0 if rr.ball_center is None else 0.2 * np.linalg.norm(c - rr.ball_center)))
                loops[("body", r.name)] = [i + offset for i in lp]
        else:
            if len(lps) != 1:
                raise RuntimeError(f"region {name} should have 1 open loop, found {len(lps)}")
            loops[(name, name)] = [i + offset for i in lps[0]]
        all_v.append(v)
        all_t.append(t + offset)
        rid.append(np.full(len(v), REGION_IDS[name]))
        offset += len(v)
    verts = np.concatenate(all_v)
    tris = np.concatenate(all_t)
    rid = np.concatenate(rid)

    for r in regions:
        la, lb = loops[("body", r.name)], loops[(r.name, r.name)]
        mesher.snap_loop(verts, la, field, r.plane_point, r.plane_normal)
        mesher.snap_loop(verts, lb, field, r.plane_point + r.plane_normal * GAP, r.plane_normal)
        center = verts[la].mean(axis=0)
        strip = mesher.zipper(verts, la, lb, center, r.plane_normal)
        tris = np.concatenate([tris, strip])
    check = mesher.check_closed_manifold(tris)
    if not check["closed_oriented"]:
        raise RuntimeError(f"stitched template is not closed/oriented: {check}")

    # relax: equalize spacing and re-project onto the true surface
    verts = mesher.relax(verts, tris, field, iterations=4, strength=0.5)
    stats = {"vertices": int(len(verts)), "triangles": int(len(tris)), "build_seconds": round(time.perf_counter() - t0, 2),
             "regions": {n: int(np.sum(rid == i)) for n, i in REGION_IDS.items()},
             "repaired_nonmanifold_vertices": repairs, **check}
    if verbose:
        print("  template:", stats)
    return Template(verts, tris, rid, skel, field, stats)


def template_cache_key() -> str:
    src = "".join(Path(__file__).with_name(n).read_text() for n in
                  ("template.py", "mesher.py", "anatomy.py", "sdf.py", "skeleton.py", "params.py", "rig.py"))
    return hashlib.sha256(src.encode() + str(np.__version__).encode()).hexdigest()[:16]


_CACHE: dict = {}


def get_template(cache_dir: str | Path | None = None, verbose: bool = False) -> Template:
    """Build (or load) the neutral template. The disk cache is keyed by the generator sources."""
    from forge_character_forge.rig import compute_skin_weights

    key = template_cache_key()
    if key in _CACHE:
        return _CACHE[key]
    cache_dir = Path(cache_dir) if cache_dir else Path(__file__).resolve().parent.parent / ".forge_cache"
    path = cache_dir / f"template_{key}.npz"
    body, face = template_params()
    if path.exists():
        z = np.load(path)
        skel = build_skeleton(body, face)
        tpl = Template(z["verts"], z["tris"], z["rid"], skel, build_field(body, face, skel),
                       json.loads(str(z["stats"])), z["joints"], z["weights"], z["tags"], json.loads(str(z["tag_names"])))
    else:
        tpl = build_template(body, face, verbose=verbose)
        tpl.joints, tpl.weights = compute_skin_weights(tpl.verts, tpl.tris, tpl.field, tpl.skeleton)
        tpl.tags, tpl.tag_names = vertex_tags(tpl.verts, tpl.field)
        cache_dir.mkdir(parents=True, exist_ok=True)
        np.savez(path, verts=tpl.verts, tris=tpl.tris, rid=tpl.region_of_vertex, stats=json.dumps(tpl.stats),
                 joints=tpl.joints, weights=tpl.weights, tags=tpl.tags, tag_names=json.dumps(tpl.tag_names))
    _CACHE[key] = tpl
    return tpl
