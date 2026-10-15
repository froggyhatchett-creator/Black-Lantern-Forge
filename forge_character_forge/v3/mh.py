"""Readers for the MakeHuman hm08 CC0 data files used by generator v3 (new Forge code; no MakeHuman code).

Units: MakeHuman files are in decimetres; everything returned here is in metres, +Y up, +Z front, and MakeHuman's
".L" / "l-" side is +X, which is Forge's ``_l`` side.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np

ASSETS = Path(__file__).resolve().parent / "assets"
DM = 0.1  # decimetres -> metres


@lru_cache(maxsize=None)
def base_obj():
    """hm08 base mesh: (verts incl. helpers (V,3), body quads (F,4) vertex ids, body quads uv ids, uvs (T,2), groups)."""
    verts, uvs, groups, cur = [], [], {}, None
    with open(ASSETS / "3dobjs" / "base.obj") as fh:
        lines = fh.readlines()
    for line in lines:
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("vt "):
            uvs.append([float(x) for x in line.split()[1:3]])
        elif line.startswith("g "):
            cur = line.split()[1]
            groups.setdefault(cur, [])
        elif line.startswith("f "):
            groups.setdefault(cur, []).append([tuple(int(t) - 1 for t in tok.split("/")[:2]) for tok in line.split()[1:]])
    body = groups["body"]
    if any(len(f) != 4 for f in body):
        raise ValueError("hm08 body group is expected to be all quads")
    fv = np.array([[c[0] for c in f] for f in body], np.int64)
    ft = np.array([[c[1] for c in f] for f in body], np.int64)
    return np.array(verts) * DM, fv, ft, np.array(uvs), {k: v for k, v in groups.items()}


@lru_cache(maxsize=None)
def target(rel: str) -> tuple[np.ndarray, np.ndarray]:
    """A MakeHuman .target: (vertex ids, deltas in metres)."""
    idx, d = [], []
    with open(ASSETS / "targets" / rel) as fh:
        for line in fh:
            if line.startswith("#") or not line.strip():
                continue
            i, x, y, z = line.split()
            idx.append(int(i))
            d.append((float(x), float(y), float(z)))
    return np.array(idx, np.int64), np.array(d).reshape(-1, 3) * DM


def target_sum(n: int, weighted) -> np.ndarray:
    out = np.zeros((n, 3))
    for rel, w in weighted:
        i, d = target(rel)
        out[i] += d * w
    return out


@lru_cache(maxsize=None)
def eye_proxy():
    """High-poly eyes: mhclo references (idx (E,3), weights (E,3), offsets (E,3)), scale refs, triangles."""
    with open(ASSETS / "eyes" / "high-poly" / "high-poly.mhclo") as fh:
        lines = [l.split() for l in fh if l.strip() and not l.startswith("#")]
    scale = {}
    for l in lines:
        if l[0] in ("x_scale", "y_scale", "z_scale"):
            scale["xyz".index(l[0][0])] = (int(l[1]), int(l[2]), float(l[3]))
    i = next(k for k, l in enumerate(lines) if l[0] == "verts")
    refs = []
    for l in lines[i + 1:]:
        if len(l) != 9:
            break
        refs.append([float(x) for x in l])
    r = np.array(refs)
    faces = []
    with open(ASSETS / "eyes" / "high-poly" / "high-poly.obj") as fh:
        obj = fh.readlines()
    for line in obj:
        if line.startswith("f "):
            faces.append([int(t.split("/")[0]) - 1 for t in line.split()[1:]])
    tris = np.array([(f[0], f[k], f[k + 1]) for f in faces for k in range(1, len(f) - 1)], np.int64)
    return r[:, :3].astype(np.int64), r[:, 3:6], r[:, 6:9], scale, tris


def fit_eyes(verts: np.ndarray) -> np.ndarray:
    """Eye proxy vertices on a (possibly morphed) base: weighted triangle point + offset scaled by the base's size."""
    idx, w, off, scale, _ = eye_proxy()
    s = np.array([abs(verts[a, ax] - verts[b, ax]) / den for ax, (a, b, den) in sorted(scale.items())])  # m per dm offset
    return (verts[idx] * w[:, :, None]).sum(1) + off * s


@lru_cache(maxsize=None)
def skeleton():
    d = json.loads((ASSETS / "rigs" / "default.mhskel").read_text())
    return d["bones"], d["joints"]


@lru_cache(maxsize=None)
def skin_weights() -> dict:
    return json.loads((ASSETS / "rigs" / "default_weights.mhw").read_text())["weights"]


def joint_positions(verts: np.ndarray) -> dict[str, np.ndarray]:
    """Each named MakeHuman joint is the mean of its helper-vertex group (so joints follow every target)."""
    _, joints = skeleton()
    return {k: verts[np.asarray(v)].mean(0) for k, v in joints.items()}


def bone_head(bone: str, jp: dict) -> np.ndarray:
    bones, _ = skeleton()
    return jp[bones[bone]["head"]]


def bvh_pose_unit(unit: str) -> dict[str, tuple[float, float, float]]:
    """Per-bone (X, Y, Z) rotation in degrees of one named frame of the face pose-unit BVH."""
    lines = (ASSETS / "poseunits" / "face-poseunits.bvh").read_text().split("\n")
    order, chans = [], []
    for l in lines:
        tok = l.split()
        if tok and tok[0] in ("ROOT", "JOINT"):
            order.append(tok[1])
        elif tok and tok[0] == "CHANNELS":
            chans.append(tok[2:])
    m = next(k for k, l in enumerate(lines) if l.startswith("MOTION"))
    frames = [list(map(float, l.split())) for l in lines[m + 3:] if l.strip()]
    fi = json.loads((ASSETS / "poseunits" / "face-poseunits.json").read_text())["framemapping"].index(unit)
    vals, out, k = frames[fi], {}, 0
    for name, ch in zip(order, chans):
        rot = {c[0]: vals[k + j] for j, c in enumerate(ch) if c.endswith("rotation")}
        k += len(ch)
        if any(abs(v) > 1e-3 for v in rot.values()):
            out[name] = (rot.get("X", 0.0), rot.get("Y", 0.0), rot.get("Z", 0.0))
    return out
