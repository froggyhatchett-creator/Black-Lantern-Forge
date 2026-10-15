"""Fixed-topology body generation: template -> re-proportioned skeleton warp -> projection onto the target field."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.anatomy import build_field
from forge_character_forge.params import BodyParams, FaceParams, GenitalParams
from forge_character_forge.rig import proportion_warp
from forge_character_forge.sdf import Field
from forge_character_forge.skeleton import Skeleton, build_skeleton
from forge_character_forge.template import Template, get_template


@dataclass
class BodyMesh:
    verts: np.ndarray
    tris: np.ndarray
    normals: np.ndarray
    joints: np.ndarray
    weights: np.ndarray
    skeleton: Skeleton
    field: Field
    template: Template
    quality: dict


def build_body(body: BodyParams, face: FaceParams, *, nipples: bool = True, fast: bool = False,
               genital: GenitalParams | None = None) -> BodyMesh:
    tpl = get_template()
    skel = build_skeleton(body, face, genital)
    field = build_field(body, face, skel, nipples=nipples)
    v = proportion_warp(tpl.verts, tpl.joints, tpl.weights, tpl.skeleton, skel)
    v = field.project(v, iterations=3 if fast else 5, max_step=0.015)
    if not fast:
        v = mesher.relax(v, tpl.tris, field, iterations=2, strength=0.45)
    n = mesher.vertex_normals(v, tpl.tris)
    quality = {}
    if not fast:
        quality = surface_quality(v, tpl, field)
    return BodyMesh(v, tpl.tris, n, tpl.joints, tpl.weights, skel, field, tpl, quality)


def surface_quality(v: np.ndarray, tpl: Template, field: Field) -> dict:
    d = np.abs(field.evaluate(v))
    t = tpl.tris
    fn0 = np.cross(tpl.verts[t[:, 1]] - tpl.verts[t[:, 0]], tpl.verts[t[:, 2]] - tpl.verts[t[:, 0]])
    fn1 = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    flipped = int(np.sum(np.sum(fn0 * fn1, axis=1) < 0))
    area = 0.5 * np.linalg.norm(fn1, axis=1)
    return {"surface_residual_mean_mm": round(float(d.mean()) * 1000, 4),
            "surface_residual_p99_mm": round(float(np.percentile(d, 99)) * 1000, 4),
            "flipped_triangles_vs_template": flipped,
            "degenerate_triangles": int(np.sum(area < 1e-10))}
