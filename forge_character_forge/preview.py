"""Render previews of a built character (rest, posed, morphed) with the software rasterizer."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image

from forge_character_forge import appearance as appx
from forge_character_forge.mesher import vertex_normals
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet
from forge_character_forge.rig import forward_kinematics, lbs, skinning_matrices

_MAT = {"skin": dict(roughness=0.5, specular=0.25, sss=1.0), "eye": dict(roughness=0.15, specular=0.8),
        "teeth": dict(roughness=0.3, specular=0.4), "hair": dict(roughness=0.55, specular=0.35),
        "brow": dict(roughness=0.7, specular=0.1), "lash": dict(roughness=0.7, specular=0.1)}


def _iris_vertex_colors(part, app) -> np.ndarray:
    img = np.asarray(Image.open(io.BytesIO(appx.iris_texture(app.eye_linear()))).convert("RGB")) / 255.0
    lin = appx.srgb_to_linear(img)
    h, w = lin.shape[:2]
    uv = np.clip(part.uvs, 0, 0.9999)
    return lin[(uv[:, 1] * h).astype(int), (uv[:, 0] * w).astype(int)]


def posed_parts(ch, pose: dict | None = None, root_offset=None, morph_weights: dict | None = None,
                local_trans: dict | None = None, include=None):
    G = forward_kinematics(ch.skeleton, pose or {}, root_offset=root_offset, local_trans=local_trans)
    S = skinning_matrices(ch.skeleton, G)
    out = []
    for p in ch.parts:
        if p.material == "cornea":
            continue
        if include is not None and p.name not in include:
            continue
        v = p.verts.copy()
        for name, wgt in (morph_weights or {}).items():
            if name in p.morphs and wgt:
                v = v + p.morphs[name] * wgt
        v = lbs(v, p.joints, p.weights, S)
        out.append((p, v))
    return out, G


def draw_items(ch, posed) -> list[DrawItem]:
    app = ch.spec.appearance
    items = []
    from forge_character_forge.clothing import COLORS
    for p, v in posed:
        kw = dict(_MAT.get(p.material, dict(roughness=0.85, specular=0.08)))
        colors, color = p.colors, (0.7, 0.7, 0.7)
        if p.material == "eye":
            colors = _iris_vertex_colors(p, app)
        elif p.material == "hair":
            color = tuple(app.hair_linear())
        elif p.material == "brow":
            color = tuple(app.brow_linear())
        elif p.material == "lash":
            color = (0.02, 0.015, 0.012)
        elif p.material.startswith("cloth_"):
            color = COLORS[p.material[6:]]
        items.append(DrawItem(v, p.tris, colors=colors, color=color, double_sided=p.double_sided, **kw))
    return items


def render_character(ch, pose=None, root_offset=None, morph_weights=None, yaw=20.0, pitch=4.0, W=480, H=900,
                     target=None, distance=None, fov=24.0, local_trans=None, include=None, text=None):
    posed, G = posed_parts(ch, pose, root_offset, morph_weights, local_trans, include)
    h = ch.skeleton.marks["height"]
    tgt = target if target is not None else (0.0, h * 0.5, 0.0)
    dist = distance if distance is not None else h * 2.85
    img = rasterize(draw_items(ch, posed), Camera(yaw_deg=yaw, pitch_deg=pitch, target=tgt, distance=dist, fov_deg=fov),
                    W=W, H=H)
    if text:
        img = label(img, text)
    return img


def render_face(ch, morph_weights=None, pose=None, yaw=15.0, W=480, H=560, text=None):
    m = ch.skeleton.marks
    tgt = (0.0, m["y_chin"] + 0.55 * m["head_h"], 0.0)
    return render_character(ch, pose=pose, morph_weights=morph_weights, yaw=yaw, pitch=2.0, W=W, H=H, target=tgt,
                            distance=m["head_h"] * 3.6, text=text)
