"""Asset kit: the character pipeline's building blocks, reused for non-character assets.

Everything here is asset-agnostic and has no Blender/Unreal dependency:
  * ``sdf.Field`` smooth CSG of primitives  -> any solid shape (props, armor plates, weapon parts, creature masses,
    building trims)
  * ``mesher.mesh_box``                     -> watertight surface-nets mesh
  * ``lod.decimate``                        -> quadric LODs on existing vertices (attributes carry over by index)
  * ``Part`` + skeleton joint               -> rigid attachment; exported, validated and skinned like any garment
This module adds a few helpers and two example assets (a hand lantern and a shoulder pauldron) used by the
phase 2 demonstration and tests.
"""

from __future__ import annotations

import numpy as np

from forge_character_forge import mesher
from forge_character_forge.lod import decimate
from forge_character_forge.mesher import vertex_normals
from forge_character_forge.parts import Part, rigid_weights
from forge_character_forge.sdf import Ellipsoid, Field, RoundBox, RoundCone, rot_xyz


def mesh_field(field: Field, lo, hi, h: float, target_tris: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    v, t = mesher.mesh_box(field.evaluate, np.asarray(lo, float), np.asarray(hi, float), h)
    if target_tris and len(t) > target_tris:
        keep, t = decimate(v, t, target_tris)
        v = v[keep]
    return v, t


def lod_chain(verts, tris, ratios=(0.5, 0.25)) -> list[tuple[np.ndarray, np.ndarray]]:
    out = [(verts, tris)]
    for r in ratios:
        keep, t = decimate(verts, tris, max(int(len(tris) * r), 64))
        out.append((verts[keep], t))
    return out


def attach(skeleton, name: str, verts: np.ndarray, tris: np.ndarray, joint: str, material: str,
           local_rot=None, offset=(0.0, 0.0, 0.0)) -> Part:
    """Place a mesh built around the origin at a joint's rest position and bind it rigidly to that joint."""
    R = np.eye(3) if local_rot is None else np.asarray(local_rot)
    v = verts @ R.T + skeleton[joint] + np.asarray(offset)
    j, w = rigid_weights(len(v), skeleton.index(joint))
    return Part(name, v, tris, material, j, w, normals=vertex_normals(v, tris), extras={"kit_asset": True, "joint": joint})


def lantern(scale: float = 1.0) -> dict:
    """A hand lantern: metal frame (cap, base, posts, bail) and a glass globe.  Origin at the bail top."""
    s = scale
    frame = Field()
    frame.add(Ellipsoid("prop", 0.006 * s, center=(0, -0.045 * s, 0), radii=(0.045 * s, 0.012 * s, 0.045 * s)))   # cap
    frame.add(RoundBox("prop", 0.004 * s, center=(0, -0.205 * s, 0), half=(0.048 * s, 0.01 * s, 0.048 * s), radius=0.004 * s))  # base
    for a in range(4):
        x, z = 0.04 * s * np.cos(a * np.pi / 2 + np.pi / 4), 0.04 * s * np.sin(a * np.pi / 2 + np.pi / 4)
        frame.add(RoundCone("prop", 0.003 * s, a=(x, -0.05 * s, z), b=(x, -0.2 * s, z), ra=0.004 * s, rb=0.004 * s))
    frame.add(RoundCone("prop", 0.004 * s, a=(-0.03 * s, -0.04 * s, 0), b=(0, 0.0, 0), ra=0.003 * s, rb=0.003 * s))
    frame.add(RoundCone("prop", 0.004 * s, a=(0.03 * s, -0.04 * s, 0), b=(0, 0.0, 0), ra=0.003 * s, rb=0.003 * s))
    glass = Field()
    glass.add(Ellipsoid("prop", 0.004 * s, center=(0, -0.125 * s, 0), radii=(0.034 * s, 0.07 * s, 0.034 * s)))
    lo, hi = np.array([-0.07, -0.24, -0.07]) * s, np.array([0.07, 0.02, 0.07]) * s
    return {"frame": mesh_field(frame, lo, hi, 0.0025 * s, 6000), "glass": mesh_field(glass, lo, hi, 0.003 * s, 2500)}


def pauldron(scale: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    """A layered shoulder plate (two overlapping shells), origin at the shoulder joint, +x outward."""
    s = scale
    f = Field()
    for i, (y, r) in enumerate(((0.035, 0.085), (0.0, 0.08))):
        outer = Ellipsoid("prop", 0.004 * s, center=(0.02 * s, y * s, 0), radii=(r * s, 0.06 * s, r * 0.95 * s))
        f.add(outer)
    f.add(Ellipsoid("prop", 0.003 * s, subtract=True, center=(0.012 * s, 0.01 * s, 0), radii=(0.075 * s, 0.055 * s, 0.072 * s)))
    f.clip_planes.append(((0, -0.03 * s, 0), (0, 1, 0)))
    f.clip_planes.append(((-0.02 * s, 0, 0), (1, 0, 0)))
    return mesh_field(f, np.array([-0.06, -0.06, -0.11]) * s, np.array([0.13, 0.11, 0.11]) * s, 0.003 * s, 5000)


def equip_demo(ch) -> list[Part]:
    """Attach the example lantern (right hand) and pauldron (left shoulder) to a built character."""
    sk = ch.skeleton
    lt = lantern()
    hand_off = sk["hand_r"] - sk["lowerarm_r"]
    hand_off = hand_off / np.linalg.norm(hand_off) * 0.09
    parts = [attach(sk, "kit_lantern_frame", *lt["frame"], "hand_r", "kit_metal", offset=hand_off),
             attach(sk, "kit_lantern_glass", *lt["glass"], "hand_r", "kit_glass", offset=hand_off)]
    pv, pt = pauldron()
    parts.append(attach(sk, "kit_pauldron", pv, pt, "upperarm_l", "kit_leather", local_rot=rot_xyz(0, 0, 0.5),
                        offset=(0.0, 0.03, 0.0)))
    return parts
