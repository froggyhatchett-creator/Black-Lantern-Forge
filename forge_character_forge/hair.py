"""Volumetric hairstyles meshed once in unit head space.

Each style is an SDF built from the default character's skin distance (sampled once on a grid in the
head frame: chin at y=0, tragion near z=0, face toward +z, 0.23 reference head height) combined with
style rules: an offset shell over the scalp, a straight-falling curtain below the crown (the cranium's
cross-section swept downward, so the hair falls past the jaw instead of hugging it), hairline and face
cut-outs, fringes, and layered/ragged ends from deterministic value noise.

The mesh is placed per character with that character's head frame (``O + v * k``), exactly like the
teeth and bun, so it has a fixed topology for every body and face and needs no per-parameter deltas.
Long hair hangs onto the neck and upper back of the *default* body with clearance; very broad or very
heavy builds can clip into it, and that limit is recorded on the part.
"""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.anatomy import head_frame
from forge_character_forge.parts import Part

STYLES = ("pixie", "bob", "bangs", "long")
LABELS = {"pixie": "Pixie / shag", "bob": "Layered bob", "bangs": "Bob with asymmetric bangs", "long": "Long layered"}
GRID_LO = np.array([-0.18, -0.50, -0.27])
GRID_HI = np.array([0.18, 0.30, 0.21])
GRID_H = 0.004
MESH_H = 0.0032
TARGET_TRIS = {"pixie": 14000, "bob": 16000, "bangs": 18000, "long": 22000}
_CACHE = Path(__file__).resolve().parent.parent / ".forge_cache"


def _key(*extra, include_styles: bool = True) -> str:
    src = Path(__file__).read_bytes() if include_styles else b"hairgrid-v2"
    for name in ("anatomy.py", "sdf.py", "mesher.py", "skeleton.py", "params.py", "lod.py", "body.py"):
        src += (Path(__file__).parent / name).read_bytes()
    return hashlib.sha256(src + repr(extra).encode()).hexdigest()[:16]


# ------------------------------------------------------------------ skin distance in unit head space
def _distance_grid() -> np.ndarray:
    path = _CACHE / f"hairgrid_{_key(include_styles=False)}.npy"
    if path.exists():
        return np.load(path)
    from forge_character_forge.body import build_body
    from forge_character_forge.params import preset
    b, f, _ = preset("neutral")
    bm = build_body(b, f, nipples=False)
    O, h = head_frame(bm.skeleton)
    k = h / 0.23
    shape = tuple(int(round((GRID_HI[i] - GRID_LO[i]) / GRID_H)) + 1 for i in range(3))
    g = np.stack(np.meshgrid(*[GRID_LO[i] + np.arange(shape[i]) * GRID_H for i in range(3)], indexing="ij"), -1).reshape(-1, 3)
    d = np.concatenate([bm.field.evaluate(O + g[s:s + 300_000] * k, far=0.12) for s in range(0, len(g), 300_000)]) / k
    grid = d.reshape(shape).astype(np.float32)
    _CACHE.mkdir(parents=True, exist_ok=True)
    np.save(path, grid)
    return grid


def _interp(grid: np.ndarray, p: np.ndarray) -> np.ndarray:
    f = (np.asarray(p, float) - GRID_LO) / GRID_H
    hi = np.array(grid.shape) - 1.000001
    f = np.clip(f, 0, hi)
    i = np.minimum(f.astype(int), np.array(grid.shape) - 2)
    t = f - i
    out = np.zeros(len(p))
    for ox in (0, 1):
        wx = t[:, 0] if ox else 1 - t[:, 0]
        for oy in (0, 1):
            wy = t[:, 1] if oy else 1 - t[:, 1]
            for oz in (0, 1):
                wz = t[:, 2] if oz else 1 - t[:, 2]
                out += wx * wy * wz * grid[i[:, 0] + ox, i[:, 1] + oy, i[:, 2] + oz]
    return out


# ------------------------------------------------------------------ deterministic value noise
def _hash(i: np.ndarray, seed: int) -> np.ndarray:
    h = (i[..., 0] * 73856093) ^ (i[..., 1] * 19349663) ^ (i[..., 2] * 83492791) ^ (seed * 2654435761)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 0xFFFF) / 65535.0


def noise3(p: np.ndarray, seed: int = 0) -> np.ndarray:
    p = np.asarray(p, float)
    i = np.floor(p).astype(np.int64)
    f = p - i
    f = f * f * (3 - 2 * f)
    out = np.zeros(len(p))
    for ox in (0, 1):
        for oy in (0, 1):
            for oz in (0, 1):
                w = (f[:, 0] if ox else 1 - f[:, 0]) * (f[:, 1] if oy else 1 - f[:, 1]) * (f[:, 2] if oz else 1 - f[:, 2])
                out += w * _hash(i + np.array([ox, oy, oz]), seed)
    return out


def _ss(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def _smin(a, b, r):
    h = np.clip(0.5 + 0.5 * (b - a) / r, 0, 1)
    return b * (1 - h) + a * h - r * h * (1 - h)


# ------------------------------------------------------------------ style SDFs (unit head space)
_EARS = (np.array([0.075, 0.098, -0.014]), np.array([-0.075, 0.098, -0.014]))


def _hairline(z, drop=0.0):
    return np.interp(z, [-0.2, -0.04, 0.0, 0.03, 0.06, 0.2], [0.07, 0.075, 0.128, 0.145, 0.168, 0.172]) - drop


def style_sdf(style: str, grid: np.ndarray):
    if style not in STYLES:
        raise ValueError(f"unknown hairstyle {style!r}")

    def fn(p):
        p = np.asarray(p, float)
        x, y, z = p[:, 0], p[:, 1], p[:, 2]
        D = _interp(grid, p)
        n1 = noise3(p * np.array([45.0, 8.0, 45.0]), 1)      # strand clumps (stretched along the fall)
        if style == "pixie":
            hl = _hairline(z, 0.012) + 0.010 * (noise3(np.stack([x * 70, z * 70, x * 0], 1), 3) - 0.5)
            hl = np.where(z > 0.03, np.maximum(hl, 0.150 + 0.012 * np.abs(x) / 0.06), hl)  # short swept fringe
            T = 0.004 + 0.011 * _ss(0.10, 0.21, y) + 0.004 * (n1 - 0.5)
            T *= np.clip((y - hl) / 0.035, 0.12, 1.0)  # thin, tapered edges at the hairline and nape
            d = np.maximum(D - T, -(D + 0.004))
            d = np.maximum(d, hl - y)
            for e in _EARS:
                d = np.maximum(d, 0.036 - np.linalg.norm(p - e, axis=1))
            return d
        ys = 0.15
        Dp = _interp(grid, np.stack([x, np.maximum(y, ys), z], 1))
        long = style == "long"
        if long:  # fall onto the neck/back of the default body with clearance
            Dp = np.minimum(Dp, D - 0.012)
        fall = np.clip((ys - y) / 0.12, 0, 1)
        T = 0.010 + 0.008 * _ss(0.15, 0.22, y) + 0.010 * fall + 0.004 * (n1 - 0.5)
        T *= np.where(z > 0.0, np.clip((y - _hairline(z)) / 0.04, 0.15, 1.0), 1.0)  # thin front edges, full at the back
        if long:
            ybot = -0.36 + 0.08 * np.clip(np.abs(x) / 0.11, 0, 1) ** 2 + 0.035 * (noise3(np.stack([x * 45, z * 45, x * 0], 1), 4) - 0.5)
            T *= np.clip((y - ybot) / 0.08, 0.4, 1.0)
            zf = np.interp(y, [-0.06, 0.02], [-0.035, 0.035])
        else:
            ybot = 0.032 - 0.022 * np.clip((z + 0.05) / 0.1, 0, 1) + 0.012 * (noise3(np.stack([x * 60, z * 60, x * 0], 1), 4) - 0.5)
            T *= np.clip((y - ybot) / 0.03, 0.55, 1.0)
            zf = 0.035
        d = np.maximum(Dp - T, -(Dp + 0.004))
        d = np.maximum(d, ybot - y)
        if long:  # strands fall from the head: no wider than the curtain across the shoulders
            d = np.maximum(d, np.abs(x) - (0.125 + 0.01 * (noise3(np.stack([y * 40, z * 40, y * 0], 1), 6) - 0.5)))
        face = np.maximum(zf - z, y - _hairline(z))  # the face: in front of the cheeks and below the hairline
        d = np.maximum(d, -face)
        if style == "bangs":
            yb = 0.150 - 0.040 * np.clip((0.06 - x) / 0.13, 0, 1) + 0.008 * (noise3(np.stack([x * 90, z * 9, x * 0], 1), 5) - 0.5)
            fr = np.maximum(D - (0.009 + 0.004 * (n1 - 0.5)), -(D + 0.003))
            fr = np.maximum(fr, yb - y)
            fr = np.maximum(fr, 0.02 - z)
            fr = np.maximum(fr, y - 0.215)
            d = _smin(d, fr, 0.006)
        return d
    return fn


def _uv(v):
    return np.stack([np.arctan2(v[:, 0], -v[:, 2]) / math.pi * 2.0, (v[:, 1] - 0.1) / 0.08], 1)


def unit_mesh(style: str) -> tuple[np.ndarray, np.ndarray]:
    """(verts, tris) in unit head space, cached on disk."""
    path = _CACHE / f"hair_{style}_{_key(style, TARGET_TRIS[style], MESH_H)}.npz"
    if path.exists():
        z = np.load(path)
        return z["v"], z["t"]
    from forge_character_forge.lod import decimate
    grid = _distance_grid()
    lo = np.array([-0.16, -0.46 if style == "long" else -0.02, -0.22])
    hi = np.array([0.16, 0.27, 0.17])
    v, t = mesher.mesh_box(style_sdf(style, grid), lo, hi, MESH_H, coarse=3)
    # drop the inner shell where it is buried in the skin (never visible), keep the rest
    c = v[t].mean(1)
    t = t[_interp(grid, c) > -0.0015]
    # remove tiny disconnected islands
    t = _largest_components(len(v), t, min_frac=0.02)
    used = np.unique(t)
    remap = -np.ones(len(v), np.int64)
    remap[used] = np.arange(len(used))
    v, t = v[used], remap[t]
    for _ in range(2):  # relax surface-nets stair noise
        adj = mesher.neighbors(len(v), t)
        v = 0.5 * v + 0.5 * mesher.laplacian(v, adj)
    keep, nt = decimate(v, t, TARGET_TRIS[style])
    v, t = v[keep], nt
    _CACHE.mkdir(parents=True, exist_ok=True)
    np.savez(path, v=v, t=t)
    return v, t


def _largest_components(nv, t, min_frac):
    parent = np.arange(nv)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a
    for a, b, c in t.tolist():
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[find(rc)] = ra
    roots = np.array([find(a) for a in t[:, 0].tolist()])
    ids, counts = np.unique(roots, return_counts=True)
    good = ids[counts >= min_frac * len(t)]
    return t[np.isin(roots, good)]


def hair_weights(skel, unit_v: np.ndarray, style: str):
    names = skel.names
    jh = names.index("head")
    J = np.zeros((len(unit_v), 4), np.int64)
    W = np.zeros((len(unit_v), 4))
    J[:, 0] = jh
    W[:, 0] = 1.0
    if style == "long":
        jn, js = names.index("neck_01"), names.index("spine_03")
        t = np.clip((0.06 - unit_v[:, 1]) / 0.30, 0, 1)
        J[:, 1], J[:, 2] = jn, js
        W[:, 0] = np.clip(1 - 2.2 * t, 0, 1)
        W[:, 2] = np.clip(2.0 * t - 0.6, 0, 1)
        W[:, 1] = np.clip(1 - W[:, 0] - W[:, 2], 0, 1)
        W /= W.sum(1, keepdims=True)
    return J, W


def build_style(skel, style: str) -> Part:
    v, t = unit_mesh(style)
    O, h = head_frame(skel)
    k = h / 0.23
    J, W = hair_weights(skel, v, style)
    return Part(f"hair_{style}", O + v * k, t.copy(), "hair", J, W, uvs=_uv(v), double_sided=True,
                extras={"head_space": True, "style": style,
                        "limits": "rigid in head space; long hair is fitted to the default body's neck and back"})
