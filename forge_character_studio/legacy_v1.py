"""Exact Step 6A generator retained for v1 recipe compatibility."""

from forge.prng import derive_stream
from forge_character_studio.implicit import FieldVolume, OrganicField, extract_surface
from forge_character_studio.model import CharacterAsset, CharacterParameters


def _v(x, y, z, rx, ry, rz, weight=1.0):
    return FieldVolume((float(x), float(y), float(z)), (float(rx), float(ry), float(rz)), float(weight))


def generate_character_v1(seed: int, p: CharacterParameters) -> CharacterAsset:
    h = p.height_m
    rng = derive_stream(seed, "forge.character.humanoid-base.v1.morphology")
    variation = rng.uniform(0.985, 1.015)
    hip_y = h * (0.475 + 0.025 * (p.leg_scale - 1.0))
    shoulder_y = hip_y + h * 0.245 * p.torso_scale
    waist_y = hip_y + (shoulder_y - hip_y) * 0.48
    chest_y = hip_y + (shoulder_y - hip_y) * 0.78
    hip_x = h * 0.070 * p.hip_scale
    leg_r = h * 0.060 * variation
    arm_r = h * 0.047 * p.arm_scale * variation
    shoulder_x = h * 0.145 * p.chest_scale
    hand_y = shoulder_y - h * 0.30 * p.arm_scale
    volumes = [
        _v(0, hip_y, 0, h*.135*p.hip_scale, h*.115, h*.088*p.hip_scale, 1.15),
        _v(0, waist_y, 0, h*.105*p.waist_scale, h*.135, h*.075*p.waist_scale, 1.10),
        _v(0, chest_y, 0, h*.145*p.chest_scale, h*.145, h*.093*p.chest_scale, 1.15),
        _v(0, shoulder_y, 0, h*.175*p.chest_scale, h*.085, h*.085, 1.05),
        _v(0, shoulder_y+h*.105, 0, h*.052, h*.085, h*.050, 1.0),
        _v(0, shoulder_y+h*.205, 0, h*.076, h*.112, h*.084, 1.10),
    ]
    for side in (-1.0, 1.0):
        x = side * hip_x
        knee_y, ankle_y = hip_y*.52, h*.075
        volumes.extend((_v(x, hip_y-h*.095, 0, leg_r*1.12, h*.165*p.leg_scale, leg_r*1.05, 1.15),
                        _v(x, knee_y, 0, leg_r, h*.155*p.leg_scale, leg_r*.95, 1.05),
                        _v(x, ankle_y+h*.105, 0, leg_r*.82, h*.145*p.leg_scale, leg_r*.82, 1.0),
                        _v(x, h*.035, -h*.030, leg_r*.90, h*.042, h*.090, 1.10)))
        sx = side*shoulder_x
        elbow_x = side*(shoulder_x+h*.055*p.arm_scale)
        wrist_x = side*(shoulder_x+h*.075*p.arm_scale)
        volumes.extend((_v(sx, shoulder_y-h*.035, 0, arm_r*1.30, h*.110, arm_r*1.25, 1.20),
                        _v(elbow_x, shoulder_y-h*.145*p.arm_scale, 0, arm_r, h*.135*p.arm_scale, arm_r, 1.05),
                        _v(wrist_x, hand_y+h*.070, 0, arm_r*.82, h*.115*p.arm_scale, arm_r*.82, 1.0),
                        _v(wrist_x, hand_y, -h*.004, arm_r*.92, h*.065, arm_r*.65, 1.0)))
    field = OrganicField(tuple(volumes))
    top = max(1.08, .475+.025*(p.leg_scale-1.0)+.245*p.torso_scale+.34)
    mesh = extract_surface(field, ((-.42*h, -.025*h, -.22*h), (.42*h, top*h, .22*h)))
    return CharacterAsset(seed, 1, p, "humanoid.neutral.v1", mesh)
