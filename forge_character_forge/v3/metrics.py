"""Measurements for v3 evidence and tests: eyeball exposure, flipped triangles, area change."""

from __future__ import annotations

import numpy as np

from forge_character_forge.render import Camera, DrawItem, rasterize
from forge_character_forge.v3 import mh, model


def eye_exposure_pixels(v: np.ndarray, W: int = 240, H: int = 160) -> int:
    """Front-view count of visible eyeball (sclera/iris shell) pixels; eyes flat red, skin flat grey."""
    src, _, tris, _ = model.body_surface()
    ev = mh.fit_eyes(v)
    items = [DrawItem(v[src], tris, color=(0.5, 0.5, 0.5), roughness=1, specular=0)]
    for side in ("l", "r"):
        ids, t = model.eye_parts()[f"eye_{side}"]
        items.append(DrawItem(ev[ids], t, color=(1.0, 0.0, 0.0), roughness=1, specular=0, double_sided=True))
    c = ev.mean(0)
    ipd = abs(ev[ev[:, 0] > 0, 0].mean() - ev[ev[:, 0] < 0, 0].mean())
    cam = Camera(yaw_deg=0, pitch_deg=0, target=tuple(c), distance=1.0, ortho_height=ipd * 1.3)
    img = rasterize(items, cam, W=W, H=H, background=(1, 1, 1), ground_y=None, ssaa=1).astype(int)
    return int(((img[:, :, 0] > 120) & (img[:, :, 1] < 70) & (img[:, :, 2] < 70)).sum())


def tri_quality(v_ref: np.ndarray, v: np.ndarray, vertex_ids: np.ndarray) -> dict:
    """Flipped triangles and area ratios on body triangles touching ``vertex_ids`` (relative to ``v_ref``)."""
    src, _, tris, _ = model.body_surface()
    t = src[tris]
    sel = np.isin(t, vertex_ids).any(1)
    t = t[sel]
    n0 = np.cross(v_ref[t[:, 1]] - v_ref[t[:, 0]], v_ref[t[:, 2]] - v_ref[t[:, 0]])
    n1 = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    a0, a1 = np.linalg.norm(n0, axis=1), np.linalg.norm(n1, axis=1)
    ratio = np.maximum(a1 / np.maximum(a0, 1e-12), a0 / np.maximum(a1, 1e-12))
    return {"triangles": int(len(t)), "flipped": int((np.sum(n0 * n1, 1) < 0).sum()),
            "max_area_ratio": round(float(ratio.max()), 2), "p99_area_ratio": round(float(np.percentile(ratio, 99)), 2)}
