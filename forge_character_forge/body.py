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


def face_landmarks(fp: FaceParams) -> np.ndarray:
    """Normalized head-frame landmarks (meters for a 0.23 m head), matching anatomy._head's construction.

    The last rows are anchors that must not move (crown, back of head, ears, neck)."""
    fw, fl = fp.face_width, fp.face_length
    nl, nw, nb = fp.nose_length, fp.nose_width, fp.nose_bridge
    tip_y = 0.119 - 0.044 * nl + 0.004 * fp.nose_upturn
    pts = [
        (0, tip_y * fl, 0.118 + 0.006 * (nl - 1.0) + 0.009 * fp.nose_tip),
        (0, 0.117 * fl, 0.088 + 0.004 * nb + 0.0065 * nb),
        (0.0125 * nw * fw, (tip_y - 0.003) * fl, 0.104 + 0.0095),
        (-0.0125 * nw * fw, (tip_y - 0.003) * fl, 0.104 + 0.0095),
        (0, 0.016 * (2.0 - fp.chin_length) * fl, 0.083 * fp.chin_projection + 0.016),
        (0, 0.016 * (2.0 - fp.chin_length) * fl - 0.017 * fp.chin_length * fl, 0.07 * fp.chin_projection),
        (0.051 * fp.jaw_width * fw, (0.032 + 0.006 * (1.0 - fp.jaw_angle)) * fl, -0.008),
        (-0.051 * fp.jaw_width * fw, (0.032 + 0.006 * (1.0 - fp.jaw_angle)) * fl, -0.008),
        (0, 0.0525 * fl, 0.0955 + 0.0085 * fp.lip_upper),
        (0, 0.0405 * fl, 0.093 + 0.0092 * fp.lip_lower),
        (0.025 * fp.mouth_width * fw, 0.047 * fl, 0.085),
        (-0.025 * fp.mouth_width * fw, 0.047 * fl, 0.085),
        (0, 0.128 * fp.brow_height * fl, 0.09 + 0.007 * fp.brow_prominence),
        (0.03 * fw, 0.128 * fp.brow_height * fl, 0.08),
        (-0.03 * fw, 0.128 * fp.brow_height * fl, 0.08),
        (0.047 * fp.cheekbone_width * fw, 0.094 * fp.cheekbone_height * fl, 0.079),
        (-0.047 * fp.cheekbone_width * fw, 0.094 * fp.cheekbone_height * fl, 0.079),
        (0.04 * fw, 0.066 * fl, 0.082 * fp.cheek_fullness ** 0.3),
        (-0.04 * fw, 0.066 * fl, 0.082 * fp.cheek_fullness ** 0.3),
        (0.068 * fw, 0.087 * fl, 0.03),
        (-0.068 * fw, 0.087 * fl, 0.03),
    ]
    ex = 0.137 * 0.23 * fp.eye_spacing * fw
    ey = 0.483 * 0.23 * fl
    es = fp.eye_size
    for side in (1.0, -1.0):
        pts += [(side * ex, ey, 0.065), (side * ex, ey + 0.0075 * es, 0.077), (side * ex, ey - 0.0075 * es, 0.076),
                (side * (ex + 0.015 * es), ey, 0.07), (side * (ex - 0.015 * es), ey, 0.072)]
    pts += [
        # anchors
        (0, 0.232, -0.01), (0, 0.13, -0.113), (0.083, 0.098, -0.014), (-0.083, 0.098, -0.014),
        (0, -0.02, -0.03), (0.05, 0.0, -0.05), (-0.05, 0.0, -0.05),
    ]
    return np.array(pts, float)


def face_prewarp(verts: np.ndarray, region: np.ndarray, src_face: FaceParams, dst_face: FaceParams, skel) -> np.ndarray:
    """Gaussian-RBF warp of head vertices that carries features with their landmarks before projection."""
    L0, L1 = face_landmarks(src_face), face_landmarks(dst_face)
    D = L1 - L0
    if np.abs(D).max() < 1e-9:
        return verts
    O = np.array([0.0, skel.marks["y_chin"], skel.marks["head_z"]])
    k = skel.marks["head_h"] / 0.23
    sigma = 0.028
    r = np.linalg.norm(L0[:, None] - L0[None], axis=2)
    Phi = np.exp(-(r / sigma) ** 2) + 1e-6 * np.eye(len(L0))
    W = np.linalg.solve(Phi, D)
    head = region == 1
    q = (verts[head] - O) / k
    phi = np.exp(-(np.linalg.norm(q[:, None] - L0[None], axis=2) / sigma) ** 2)
    out = verts.copy()
    out[head] = verts[head] + (phi @ W) * k
    return out


def build_body(body: BodyParams, face: FaceParams, *, nipples: bool = True, fast: bool = False,
               genital: GenitalParams | None = None) -> BodyMesh:
    tpl = get_template()
    skel = build_skeleton(body, face, genital)
    field = build_field(body, face, skel, nipples=nipples)
    v = proportion_warp(tpl.verts, tpl.joints, tpl.weights, tpl.skeleton, skel)
    from forge_character_forge.template import template_params
    v = face_prewarp(v, tpl.region_of_vertex, template_params()[1], face, skel)
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
