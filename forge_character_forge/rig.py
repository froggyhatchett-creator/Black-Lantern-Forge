"""Skin weights, forward kinematics and linear blend skinning.

Weights come from the anatomy field itself: every additive primitive belongs to
a bone, so a vertex is attributed to the bones whose primitives are nearest
(soft-min over signed distances, per-primitive temperature so fingers do not
bleed into each other), then diffused along mesh edges and pruned to 4
influences.  Breast bones get an explicit chest-surface falloff so physics can
drive them even on flat-chested bodies.
"""

from __future__ import annotations

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.sdf import Ellipsoid, Field, RoundBox, RoundCone
from forge_character_forge.skeleton import CLOTH_BONES, DEV_BONES, Skeleton

MAX_INFLUENCES = 4
NON_DEFORM = {"root", "eye_l", "eye_r"} | set(DEV_BONES)
WARP_EXCLUDE = {"eye_l", "eye_r", "breast_l", "breast_r"} | set(DEV_BONES) | set(CLOTH_BONES)


def _prim_scale(p) -> float:
    if isinstance(p, Ellipsoid):
        return float(min(p.radii))
    if isinstance(p, RoundCone):
        return float(min(p.ra, p.rb))
    if isinstance(p, RoundBox):
        return float(min(p.half))
    return 0.02


def compute_skin_weights(verts: np.ndarray, tris: np.ndarray, field: Field, skel: Skeleton,
                         diffuse_iters: int = 12) -> tuple[np.ndarray, np.ndarray]:
    """Return (joints (V,4) int, weights (V,4) float) indexed into skel.names."""
    adds = [p for p in field.prims if not p.subtract]
    bones = sorted({p.bone for p in adds})
    bidx = {b: i for i, b in enumerate(bones)}
    V = len(verts)
    W = np.zeros((V, len(bones)))
    dists = np.full((len(adds), V), 1.0)
    for i, p in enumerate(adds):
        lo, hi = p.bounds()
        mask = np.all((verts >= lo - 0.06) & (verts <= hi + 0.06), axis=1)
        if mask.any():
            dists[i, mask] = p.distance(verts[mask])
    dmin = dists.min(axis=0)
    for i, p in enumerate(adds):
        tau = float(np.clip(0.45 * _prim_scale(p), 0.0012, 0.014))
        contrib = np.exp(-np.maximum(dists[i] - dmin, 0.0) / tau)
        W[:, bidx[p.bone]] += contrib
    W /= W.sum(axis=1, keepdims=True)
    adj = mesher.neighbors(V, tris)
    for _ in range(diffuse_iters):
        W = 0.5 * W + 0.5 * mesher.laplacian(W, adj)
    # breast influence: smooth radial falloff on the front of the chest
    names = list(skel.names)
    full = np.zeros((V, len(names)))
    for b, i in bidx.items():
        full[:, names.index(b)] = W[:, i]
    normals = mesher.vertex_normals(verts, tris)
    u = skel.marks["height"] / 1.75
    for lab in ("l", "r"):
        c = skel.marks.get(f"nipple_{lab}", skel[f"breast_{lab}"])
        c = np.asarray(c) - np.array([0.0, 0.0, 0.02 * u])
        r = np.linalg.norm((verts - c) * np.array([1.0, 1.15, 0.8]), axis=1)
        fall = np.clip(1.0 - r / (0.085 * u), 0.0, 1.0)
        fall = fall * fall * (3 - 2 * fall)
        fall *= np.clip(normals[:, 2] * 2.0 + 0.4, 0.0, 1.0)
        spine = [names.index(n) for n in ("spine_02", "spine_03")]
        on_torso = full[:, spine].sum(axis=1)
        wb = fall * on_torso * 0.9
        scale = np.where(on_torso > 1e-9, (on_torso - wb) / np.maximum(on_torso, 1e-9), 1.0)
        full[:, spine] *= scale[:, None]
        full[:, names.index(f"breast_{lab}")] += wb
    order = np.argsort(-full, axis=1)[:, :MAX_INFLUENCES]
    wts = np.take_along_axis(full, order, axis=1)
    wts /= wts.sum(axis=1, keepdims=True)
    # quantize to float32-friendly and renormalize exactly
    wts = np.round(wts, 6)
    wts[:, 0] += 1.0 - wts.sum(axis=1)
    return order.astype(np.int64), wts


# ---------------------------------------------------------------- kinematics

def quat_from_euler(rx: float, ry: float, rz: float) -> np.ndarray:
    """XYZ intrinsic (R = Rz @ Ry @ Rx as rot_xyz), quaternion (x, y, z, w)."""
    cx, sx = np.cos(rx / 2), np.sin(rx / 2)
    cy, sy = np.cos(ry / 2), np.sin(ry / 2)
    cz, sz = np.cos(rz / 2), np.sin(rz / 2)
    qx = np.array([sx, 0, 0, cx])
    qy = np.array([0, sy, 0, cy])
    qz = np.array([0, 0, sz, cz])
    return quat_mul(qz, quat_mul(qy, qx))


def quat_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return np.array([aw * bx + ax * bw + ay * bz - az * by,
                     aw * by - ax * bz + ay * bw + az * bx,
                     aw * bz + ax * by - ay * bx + az * bw,
                     aw * bw - ax * bx - ay * by - az * bz])


def quat_to_mat(q: np.ndarray) -> np.ndarray:
    x, y, z, w = q / np.linalg.norm(q)
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                     [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                     [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])


def mat_to_quat(m: np.ndarray) -> np.ndarray:
    t = np.trace(m)
    if t > 0:
        s = np.sqrt(t + 1.0) * 2
        q = [(m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s, 0.25 * s]
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = np.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2
        q = [0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s, (m[2, 1] - m[1, 2]) / s]
    elif m[1, 1] > m[2, 2]:
        s = np.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2
        q = [(m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s, (m[0, 2] - m[2, 0]) / s]
    else:
        s = np.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2
        q = [(m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s, (m[1, 0] - m[0, 1]) / s]
    q = np.array(q)
    q /= np.linalg.norm(q)
    return q if q[3] >= 0 else -q


def forward_kinematics(skel: Skeleton, local_rot: dict[str, np.ndarray] | None = None,
                       root_offset: np.ndarray | None = None,
                       local_trans: dict[str, np.ndarray] | None = None) -> np.ndarray:
    """World 4x4 matrices for each joint. Rest local orientation is identity.

    local_rot maps joint name -> quaternion (x,y,z,w) applied in the joint's local frame.
    local_trans maps joint name -> extra local translation (physics/stretch).
    """
    local_rot = local_rot or {}
    local_trans = local_trans or {}
    offs = skel.local_offsets()
    G = np.zeros((len(skel.names), 4, 4))
    for j, name in enumerate(skel.names):
        L = np.eye(4)
        if name in local_rot:
            L[:3, :3] = quat_to_mat(np.asarray(local_rot[name], float))
        L[:3, 3] = offs[j] + (local_trans[name] if name in local_trans else 0.0)
        if j == 0 and root_offset is not None:
            L[:3, 3] = L[:3, 3] + root_offset
        p = skel.parents[j]
        G[j] = L if p < 0 else G[p] @ L
    return G


def skinning_matrices(skel: Skeleton, G: np.ndarray) -> np.ndarray:
    """G_j @ inverse(bind_j); bind is the rest translation (identity rotation)."""
    S = G.copy()
    S[:, :3, 3] = G[:, :3, 3] - np.einsum("jab,jb->ja", G[:, :3, :3], skel.rest)
    return S


def lbs(verts: np.ndarray, joints: np.ndarray, weights: np.ndarray, S: np.ndarray,
        normals: np.ndarray | None = None):
    """Linear blend skinning. Returns posed verts (and normals if given)."""
    M = np.einsum("vk,vkab->vab", weights, S[joints])
    out = np.einsum("vab,vb->va", M[:, :3, :3], verts) + M[:, :3, 3]
    if normals is None:
        return out
    n = np.einsum("vab,vb->va", M[:, :3, :3], normals)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    return out, n


def proportion_warp(verts: np.ndarray, joints: np.ndarray, weights: np.ndarray, src: Skeleton, dst: Skeleton) -> np.ndarray:
    """Move template vertices from the source rest skeleton onto a re-proportioned one.

    Each bone gets a regularized affine map fitted from its joint and children joints,
    defaulting to the global scale ratio in directions the joints do not constrain.
    """
    s = dst.marks["height"] / src.marks["height"]
    s_head = dst.marks["head_h"] / src.marks["head_h"]
    s_hand = dst.marks["hand_len"] / src.marks["hand_len"]
    lam = 1e-4
    A = np.zeros((len(src.names), 3, 4))
    for j, name in enumerate(src.names):
        if name in ("head", "jaw", "eye_l", "eye_r"):
            sj = s_head
        elif name.startswith(("hand_", "thumb", "index", "middle", "ring", "pinky")):
            sj = s_hand
        else:
            sj = s
        kids = [i for i, p in enumerate(src.parents) if p == j and src.names[i] not in WARP_EXCLUDE]
        P = np.array([src.rest[i] - src.rest[j] for i in kids]).reshape(-1, 3)
        Q = np.array([dst.rest[i] - dst.rest[j] for i in kids]).reshape(-1, 3)
        M = (Q.T @ P + lam * sj * np.eye(3)) @ np.linalg.inv(P.T @ P + lam * np.eye(3))
        A[j, :, :3] = M
        A[j, :, 3] = dst.rest[j] - M @ src.rest[j]
    T = np.einsum("vk,vkab->vab", weights, A[joints])
    return np.einsum("vab,vb->va", T[:, :, :3], verts) + T[:, :, 3]
