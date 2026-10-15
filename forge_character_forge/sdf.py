"""Vectorized signed-distance primitives for the anatomical body field.

Every primitive evaluates a batch of points (N x 3 float64) and returns an
approximate signed distance in meters (negative inside).  Primitives carry the
name of the skeleton bone that owns them; the body field uses that tag to derive
skin weights by soft attribution, so the field that shapes the surface is the
same field that decides which bone moves it.

Distances are Lipschitz-bounded approximations (ellipsoid and scaled cones are
not exact SDFs).  The mesher only needs a correct zero set and a usable
gradient, which these provide.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


def _frame_from_axis(axis: np.ndarray, hint: np.ndarray | None = None) -> np.ndarray:
    """Rows are the local x, y, z axes; local y is ``axis``."""
    y = axis / np.linalg.norm(axis)
    hint = np.array([0.0, 0.0, 1.0]) if hint is None else np.asarray(hint, float)
    if abs(float(np.dot(hint, y))) > 0.95:
        hint = np.array([1.0, 0.0, 0.0])
    x = np.cross(y, hint)
    x /= np.linalg.norm(x)
    z = np.cross(x, y)
    return np.stack([x, y, z])


def rot_xyz(rx: float = 0.0, ry: float = 0.0, rz: float = 0.0) -> np.ndarray:
    """Rotation matrix R = Rz @ Ry @ Rx (radians)."""
    cx, sx, cy, sy, cz, sz = np.cos(rx), np.sin(rx), np.cos(ry), np.sin(ry), np.cos(rz), np.sin(rz)
    mx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
    my = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])
    mz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])
    return mz @ my @ mx


@dataclass
class Prim:
    """Base primitive. ``blend`` is the smooth-union radius used when it joins the field."""

    bone: str
    blend: float = 0.02
    subtract: bool = False
    tag: str = ""

    def distance(self, p: np.ndarray) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:  # pragma: no cover - abstract
        raise NotImplementedError


@dataclass
class Ellipsoid(Prim):
    center: tuple = (0.0, 0.0, 0.0)
    radii: tuple = (0.1, 0.1, 0.1)
    rot: np.ndarray | None = None  # world-from-local rotation

    def distance(self, p):
        q = p - np.asarray(self.center)
        if self.rot is not None:
            q = q @ np.asarray(self.rot)  # local = R^T q  ->  row form q @ R
        r = np.asarray(self.radii)
        k0 = np.linalg.norm(q / r, axis=1)
        k1 = np.linalg.norm(q / (r * r), axis=1)
        k1 = np.maximum(k1, 1e-12)
        return k0 * (k0 - 1.0) / k1

    def bounds(self):
        c, m = np.asarray(self.center), max(self.radii)
        return c - m, c + m


@dataclass
class RoundCone(Prim):
    """Tapered capsule from ``a`` (radius ra) to ``b`` (radius rb).

    ``squash`` scales the cross-section (local x, local z) to make it elliptic,
    oriented by ``hint`` (local z points along the hint projected off the axis).
    """

    a: tuple = (0.0, 0.0, 0.0)
    b: tuple = (0.0, 1.0, 0.0)
    ra: float = 0.05
    rb: float = 0.04
    squash: tuple = (1.0, 1.0)
    hint: tuple | None = None

    def distance(self, p):
        a, b = np.asarray(self.a, float), np.asarray(self.b, float)
        axis = b - a
        h = float(np.linalg.norm(axis))
        frame = _frame_from_axis(axis, None if self.hint is None else np.asarray(self.hint, float))
        q = (p - a) @ frame.T  # local coords: y along axis
        sx, sz = self.squash
        q = np.stack([q[:, 0] / sx, q[:, 1], q[:, 2] / sz], axis=1)
        scale = min(sx, sz)
        r1, r2 = self.ra, self.rb
        # Inigo Quilez round cone, axis along +y from 0 to h
        qx = np.sqrt(q[:, 0] ** 2 + q[:, 2] ** 2)
        qy = q[:, 1]
        bb = (r1 - r2) / h
        aa = np.sqrt(max(1.0 - bb * bb, 1e-9))
        k = qx * (-bb) + qy * aa  # dot(q, vec2(-b, a))
        d_side = qx * aa + qy * bb - r1
        d_bot = np.sqrt(qx * qx + qy * qy) - r1
        d_top = np.sqrt(qx * qx + (qy - h) ** 2) - r2
        d = np.where(k < 0.0, d_bot, np.where(k > aa * h, d_top, d_side))
        return d * scale

    def bounds(self):
        a, b = np.asarray(self.a), np.asarray(self.b)
        m = max(self.ra, self.rb) * max(self.squash)
        return np.minimum(a, b) - m, np.maximum(a, b) + m


@dataclass
class RoundBox(Prim):
    center: tuple = (0.0, 0.0, 0.0)
    half: tuple = (0.05, 0.05, 0.05)
    radius: float = 0.01
    rot: np.ndarray | None = None

    def distance(self, p):
        q = p - np.asarray(self.center)
        if self.rot is not None:
            q = q @ np.asarray(self.rot)
        d = np.abs(q) - (np.asarray(self.half) - self.radius)
        outside = np.linalg.norm(np.maximum(d, 0.0), axis=1)
        inside = np.minimum(np.max(d, axis=1), 0.0)
        return outside + inside - self.radius

    def bounds(self):
        c, m = np.asarray(self.center), float(np.linalg.norm(self.half))
        return c - m, c + m


def smin(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    """Polynomial smooth minimum (C1)."""
    if k <= 0.0:
        return np.minimum(a, b)
    h = np.maximum(k - np.abs(a - b), 0.0) / k
    return np.minimum(a, b) - h * h * k * 0.25


def smax(a: np.ndarray, b: np.ndarray, k: float) -> np.ndarray:
    return -smin(-a, -b, k)


@dataclass
class Field:
    """Ordered smooth CSG of primitives.  Additive prims are unioned, then subtractive ones carve."""

    prims: list = field(default_factory=list)
    clip_planes: list = field(default_factory=list)  # (point, normal): keep the side the normal points to

    def add(self, prim: Prim) -> Prim:
        self.prims.append(prim)
        return prim

    def _prim_distances(self, p: np.ndarray, prims, far: float) -> np.ndarray:
        out = np.full((len(prims), len(p)), far)
        for i, prim in enumerate(prims):
            lo, hi = prim.bounds()
            margin = prim.blend + far
            mask = np.all((p >= lo - margin) & (p <= hi + margin), axis=1)
            if np.any(mask):
                out[i, mask] = prim.distance(p[mask])
        return out

    def evaluate(self, p: np.ndarray, far: float = 0.08, with_parts: bool = False):
        p = np.asarray(p, dtype=np.float64)
        add = [q for q in self.prims if not q.subtract]
        sub = [q for q in self.prims if q.subtract]
        dists = self._prim_distances(p, add, far)
        d = np.full(len(p), far)
        for i, prim in enumerate(add):
            d = smin(d, dists[i], prim.blend)
        if sub:
            sd = self._prim_distances(p, sub, far)
            for i, prim in enumerate(sub):
                d = smax(d, -sd[i], prim.blend)
        for point, normal in self.clip_planes:
            n = np.asarray(normal, float)
            d = np.maximum(d, -((p - np.asarray(point)) @ n))
        if with_parts:
            return d, dists, add
        return d

    def gradient(self, p: np.ndarray, eps: float = 2e-4) -> np.ndarray:
        offs = np.eye(3) * eps
        cols = []
        for k in range(3):
            cols.append((self.evaluate(p + offs[k]) - self.evaluate(p - offs[k])) / (2 * eps))
        return np.stack(cols, axis=1)

    def project(self, p: np.ndarray, iterations: int = 4, max_step: float = 0.02) -> np.ndarray:
        """Newton-project points onto the zero set, limiting each step."""
        p = np.array(p, dtype=np.float64)
        for _ in range(iterations):
            d = self.evaluate(p)
            g = self.gradient(p)
            gn2 = np.maximum(np.sum(g * g, axis=1), 1e-10)
            step = (d / gn2)[:, None] * g
            sl = np.linalg.norm(step, axis=1)
            scale = np.where(sl > max_step, max_step / np.maximum(sl, 1e-12), 1.0)
            p -= step * scale[:, None]
        return p
