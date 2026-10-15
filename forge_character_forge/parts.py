"""Mesh part container shared by the body, accessories, garments and developer anatomy."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class Part:
    name: str
    verts: np.ndarray
    tris: np.ndarray
    material: str
    joints: np.ndarray            # (V, 4) indices into the skeleton
    weights: np.ndarray           # (V, 4)
    normals: np.ndarray | None = None
    uvs: np.ndarray | None = None
    colors: np.ndarray | None = None
    morphs: dict = field(default_factory=dict)   # name -> (V, 3) position deltas
    dev_only: bool = False
    double_sided: bool = False
    extras: dict = field(default_factory=dict)

    def __post_init__(self):
        self.verts = np.asarray(self.verts, float)
        self.tris = np.asarray(self.tris, np.int64)
        if self.normals is None:
            from forge_character_forge.mesher import vertex_normals
            self.normals = vertex_normals(self.verts, self.tris)


def rigid_weights(n: int, joint: int) -> tuple[np.ndarray, np.ndarray]:
    j = np.zeros((n, 4), np.int64)
    j[:, 0] = joint
    w = np.zeros((n, 4))
    w[:, 0] = 1.0
    return j, w


def segment_weights(verts: np.ndarray, chain: list[tuple[int, np.ndarray, np.ndarray]], sharp: float = 0.012):
    """Weights by soft nearest-segment distance. chain: [(joint_index, a, b), ...]."""
    d = []
    for _, a, b in chain:
        ab = b - a
        t = np.clip(((verts - a) @ ab) / max(float(ab @ ab), 1e-12), 0, 1)
        d.append(np.linalg.norm(verts - (a + t[:, None] * ab), axis=1))
    d = np.stack(d, 1)
    w = np.exp(-(d - d.min(1, keepdims=True)) / sharp)
    order = np.argsort(-w, axis=1)[:, :4]
    ww = np.take_along_axis(w, order, axis=1)
    ww /= ww.sum(1, keepdims=True)
    ids = np.array([c[0] for c in chain])
    jj = ids[order]
    if jj.shape[1] < 4:
        pad = 4 - jj.shape[1]
        jj = np.concatenate([jj, np.repeat(jj[:, :1], pad, 1)], 1)
        ww = np.concatenate([ww, np.zeros((len(ww), pad))], 1)
    return jj, ww
