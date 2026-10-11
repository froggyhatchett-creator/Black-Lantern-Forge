"""Versioned neutral joint-landmark contract; this is not an animation rig."""

from __future__ import annotations

from dataclasses import dataclass

from forge_character_studio.model import CharacterParameters

SKELETON_CONTRACT_ID = "forge.character-skeleton-landmarks"
SKELETON_CONTRACT_VERSION = 1


@dataclass(frozen=True)
class JointLandmark:
    name: str
    parent: str | None
    position: tuple[float, float, float]
    radius: float


@dataclass(frozen=True)
class SkeletonLandmarks:
    contract_id: str
    contract_version: int
    joints: tuple[JointLandmark, ...]

    def by_name(self) -> dict[str, JointLandmark]:
        return {joint.name: joint for joint in self.joints}

    def to_dict(self) -> dict:
        return {"contract": {"id": self.contract_id, "version": self.contract_version}, "joints": [
            {"name": j.name, "parent": j.parent, "position": list(j.position), "radius": j.radius}
            for j in self.joints
        ]}


def build_skeleton(parameters: CharacterParameters) -> SkeletonLandmarks:
    p, h = parameters, parameters.height_m
    hip_y = h * (0.475 + 0.025 * (p.leg_scale - 1.0))
    shoulder_y = hip_y + h * 0.245 * p.torso_scale
    pelvis_x = h * 0.064 * p.hip_scale * p.pelvis_width
    shoulder_x = h * 0.145 * p.chest_scale * p.shoulder_width
    joints = [
        JointLandmark("root", None, (0.0, hip_y, 0.0), h * 0.055),
        JointLandmark("spine_lower", "root", (0.0, hip_y + h * .08, 0.0), h * .05),
        JointLandmark("spine_chest", "spine_lower", (0.0, shoulder_y - h * .08, 0.0), h * .065),
        JointLandmark("neck", "spine_chest", (0.0, shoulder_y + h * .07, 0.0), h * .035),
        JointLandmark("head", "neck", (0.0, shoulder_y + h * .19, 0.0), h * .065),
    ]
    for label, side in (("left", 1.0), ("right", -1.0)):
        arm_local = 1.0 + (getattr(p, f"{label}_arm_scale") - 1.0) * (1.0 - p.symmetry)
        leg_local = 1.0 + (getattr(p, f"{label}_leg_scale") - 1.0) * (1.0 - p.symmetry)
        sx = side * shoulder_x
        elbow = (side * (shoulder_x + h * .055 * p.arm_scale * arm_local), shoulder_y - h * .145 * p.arm_scale * arm_local, 0.0)
        wrist = (side * (shoulder_x + h * .075 * p.arm_scale * arm_local), shoulder_y - h * .26 * p.arm_scale * arm_local, 0.0)
        hip = (side * pelvis_x, hip_y, 0.0)
        knee = (side * pelvis_x, hip_y * .52 * leg_local, 0.006 * h)
        ankle = (side * pelvis_x, h * .075, 0.0)
        joints.extend((
            JointLandmark(f"{label}_shoulder", "spine_chest", (sx, shoulder_y, 0.0), h * .045),
            JointLandmark(f"{label}_elbow", f"{label}_shoulder", elbow, h * .032),
            JointLandmark(f"{label}_wrist", f"{label}_elbow", wrist, h * .025),
            JointLandmark(f"{label}_hand", f"{label}_wrist", (wrist[0], wrist[1] - h * .055, -h * .006), h * .03),
            JointLandmark(f"{label}_hip", "root", hip, h * .05),
            JointLandmark(f"{label}_knee", f"{label}_hip", knee, h * .038),
            JointLandmark(f"{label}_ankle", f"{label}_knee", ankle, h * .026),
            JointLandmark(f"{label}_foot", f"{label}_ankle", (ankle[0], h * .025, -h * .065), h * .035),
        ))
    return SkeletonLandmarks(SKELETON_CONTRACT_ID, SKELETON_CONTRACT_VERSION, tuple(joints))
