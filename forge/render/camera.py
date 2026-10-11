"""Fixed preview cameras (preview_version 1).

Orthographic projection, so there is no perspective divide and attribute
interpolation is exactly affine. Framing is fixed in world space and doesn't
depend on the asset: every v1 sword is shown at the same scale and position.

  target        (0, 0.295, 0) m   midpoint of the v1 sword's Y range [-0.085, 0.675]
  frame height  0.84 m            visible world height; width = 0.84 * W / H
  world up      +Y                screen up is +Y projected (the coordinate system is preserved)

  view            direction toward the camera (unnormalized)
  front           ( 0,   0,   1 )    looks at the blade flat; +X is screen-right
  side            ( 1,   0,   0 )    looks at the blade edge; -Z is screen-right
  three_quarter   ( 1,   0.5, 2 )    default; about 26.6 deg yaw, 12.6 deg elevation

Basis: d = normalize(direction), right = normalize(Y x d), up = d x right.
Only + - * / sqrt are used.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from forge.errors import RenderError

VIEW_DIRECTIONS = {
    "front": (0.0, 0.0, 1.0),
    "side": (1.0, 0.0, 0.0),
    "three_quarter": (1.0, 0.5, 2.0),
}
FRAME_TARGET = (0.0, 0.295, 0.0)
FRAME_HEIGHT = 0.84


def _norm(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / length, v[1] / length, v[2] / length)


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


@dataclass(frozen=True)
class Camera:
    view: str
    direction: tuple[float, float, float]  # unit vector from target toward camera
    right: tuple[float, float, float]
    up: tuple[float, float, float]
    target: tuple[float, float, float]
    half_width: float   # meters
    half_height: float  # meters
    width_px: int
    height_px: int

    def project(self, p):
        """World point -> (pixel x, pixel y (down), depth (larger = closer))."""
        qx, qy, qz = p[0] - self.target[0], p[1] - self.target[1], p[2] - self.target[2]
        sx = qx * self.right[0] + qy * self.right[1] + qz * self.right[2]
        sy = qx * self.up[0] + qy * self.up[1] + qz * self.up[2]
        depth = qx * self.direction[0] + qy * self.direction[1] + qz * self.direction[2]
        px = (sx / self.half_width + 1.0) * 0.5 * self.width_px
        py = (1.0 - sy / self.half_height) * 0.5 * self.height_px
        return px, py, depth

    def to_dict(self) -> dict:
        return {"view": self.view, "projection": "orthographic", "direction": list(self.direction),
                "right": list(self.right), "up": list(self.up), "target": list(self.target),
                "frame_width_m": self.half_width * 2.0, "frame_height_m": self.half_height * 2.0}


def camera_for(view: str, width_px: int, height_px: int) -> Camera:
    if view not in VIEW_DIRECTIONS:
        raise RenderError(f"unknown view {view!r}; known: {sorted(VIEW_DIRECTIONS)}")
    d = _norm(VIEW_DIRECTIONS[view])
    right = _norm(_cross((0.0, 1.0, 0.0), d))
    up = _cross(d, right)
    half_h = FRAME_HEIGHT * 0.5
    half_w = half_h * width_px / height_px
    return Camera(view, d, right, up, FRAME_TARGET, half_w, half_h, width_px, height_px)
