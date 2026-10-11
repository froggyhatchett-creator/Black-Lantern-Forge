"""Topology and deformation-readiness measurements for generated characters."""
from __future__ import annotations

import math
from dataclasses import dataclass

from forge_character_studio.model import CharacterAsset
from forge_character_studio.skeleton import build_skeleton


@dataclass(frozen=True)
class JointDiagnostic:
    joint: str
    nearby_vertices: int
    radial_rings: int
    max_normalized_gap: float


def _distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def joint_topology_diagnostics(asset: CharacterAsset) -> tuple[JointDiagnostic, ...]:
    """Measure density and angular coverage around deformation-critical joints."""
    joints = build_skeleton(asset.parameters).by_name()
    names = ("left_shoulder", "left_elbow", "left_hip", "left_knee",
             "right_shoulder", "right_elbow", "right_hip", "right_knee")
    out = []
    for name in names:
        joint = joints[name]
        radius = joint.radius * 2.25
        nearby = [p for p in asset.body.positions if _distance(p, joint.position) <= radius]
        distances = sorted(_distance(p, joint.position) / radius for p in nearby)
        occupied = {min(5, int(value * 6.0)) for value in distances}
        gaps = [distances[i+1] - distances[i] for i in range(len(distances)-1)]
        out.append(JointDiagnostic(name, len(nearby), len(occupied), max(gaps, default=1.0)))
    return tuple(out)


def deformation_diagnostics(asset: CharacterAsset) -> dict[str, dict[str, float | int | bool]]:
    """Predict whether four canonical poses have enough local support to rig safely.

    This intentionally does not implement animation. It reports support density
    and an estimated normalized stretch under continuous two-bone weighting.
    """
    topology = {d.joint: d for d in joint_topology_diagnostics(asset)}
    cases = {
        "arm_raise": ("left_shoulder", 80.0), "elbow_bend": ("left_elbow", 95.0),
        "knee_bend": ("left_knee", 100.0), "hip_rotation": ("left_hip", 45.0),
    }
    result = {}
    for case, (joint, angle) in cases.items():
        item = topology[joint]
        stretch = (1.0 - math.cos(math.radians(angle))) / max(12.0, item.nearby_vertices)
        result[case] = {"joint": joint, "angle_degrees": angle, "support_vertices": item.nearby_vertices,
                        "estimated_normalized_stretch": stretch, "passes": item.nearby_vertices >= 18 and stretch < .08}
    return result


def surface_quality(asset: CharacterAsset) -> dict[str, float | int]:
    mesh = asset.body
    edges = set()
    areas = []
    for a, b, c in mesh.triangles:
        pa, pb, pc = mesh.positions[a], mesh.positions[b], mesh.positions[c]
        edges.update(((min(a,b),max(a,b)), (min(b,c),max(b,c)), (min(c,a),max(c,a))))
        ux, uy, uz = pb[0]-pa[0], pb[1]-pa[1], pb[2]-pa[2]
        vx, vy, vz = pc[0]-pa[0], pc[1]-pa[1], pc[2]-pa[2]
        areas.append(.5*math.sqrt((uy*vz-uz*vy)**2+(uz*vx-ux*vz)**2+(ux*vy-uy*vx)**2))
    return {"vertices": mesh.vertex_count, "triangles": mesh.triangle_count, "edges": len(edges),
            "euler_characteristic": mesh.vertex_count-len(edges)+mesh.triangle_count,
            "minimum_triangle_area_m2": min(areas), "maximum_triangle_area_m2": max(areas)}
