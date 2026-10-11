"""Geometry-bound preview framing: preview renderer "forge.preview.fit" version 1 (Step 5A).

Frozen preview v1 ("forge.preview" v1, forge/render/camera.py) frames a fixed 0.84 m window sized
for the short sword. That's too small for a great sword and too loose for a dagger. This renderer
reuses everything else unchanged: the same view directions, the same rasterizer and shader, the
same PNG and metadata. Only the framing is new:

  basis       the same as preview v1 for the view (right, up, direction toward the camera)
  extents     every vertex of every component, projected onto right and up
  target      the center of those projected extents (depth 0 along the view direction)
  frame       half_height = max(span_up / 2, span_right / 2 * H / W) * (1 + MARGIN)
              half_width  = half_height * W / H
The asset is read and never moved. Only + - * / and comparisons are used, so the framing is as
deterministic as the geometry. The short sword keeps forge.preview v1, so its pixels can't change.
"""

from __future__ import annotations

from forge.errors import RenderError
from forge.presentation.model import PresentedSword
from forge.render import PreviewImage
from forge.render.camera import Camera, camera_for
from forge.render.raster import render_pixels
from forge.render.settings import PreviewSettings

FIT_PREVIEW_ID = "forge.preview.fit"
MARGIN = 0.06


def fit_camera(presented: PresentedSword, view: str, width_px: int, height_px: int) -> Camera:
    base = camera_for(view, width_px, height_px)
    r, u = base.right, base.up
    lo_r = lo_u = None
    hi_r = hi_u = None
    for mesh in presented.asset.components:
        for p in mesh.positions:
            sr = p[0] * r[0] + p[1] * r[1] + p[2] * r[2]
            su = p[0] * u[0] + p[1] * u[1] + p[2] * u[2]
            if lo_r is None:
                lo_r = hi_r = sr
                lo_u = hi_u = su
                continue
            lo_r, hi_r = min(lo_r, sr), max(hi_r, sr)
            lo_u, hi_u = min(lo_u, su), max(hi_u, su)
    if lo_r is None:
        raise RenderError("cannot frame an asset with no vertices")
    cr, cu = (lo_r + hi_r) * 0.5, (lo_u + hi_u) * 0.5
    target = (r[0] * cr + u[0] * cu, r[1] * cr + u[1] * cu, r[2] * cr + u[2] * cu)
    half_h = max((hi_u - lo_u) * 0.5, (hi_r - lo_r) * 0.5 * height_px / width_px) * (1.0 + MARGIN)
    if not half_h > 0.0:
        raise RenderError("asset has zero extent in this view")
    half_w = half_h * width_px / height_px
    return Camera(view, base.direction, r, u, target, half_w, half_h, width_px, height_px)


def render_fit_preview(presented: PresentedSword, settings: PreviewSettings) -> PreviewImage:
    if not isinstance(presented, PresentedSword):
        raise RenderError(f"render_fit_preview expects a PresentedSword; got {type(presented).__name__}")
    if not isinstance(settings, PreviewSettings):
        raise RenderError(f"render_fit_preview expects PreviewSettings; got {type(settings).__name__}")
    camera = fit_camera(presented, settings.view, settings.width, settings.height)
    pixels = render_pixels(presented, camera, settings.ssaa)
    if len(pixels) != settings.width * settings.height * 3:
        raise RenderError("renderer produced a pixel buffer of the wrong size")
    return PreviewImage(settings, camera, settings.width, settings.height, pixels)
