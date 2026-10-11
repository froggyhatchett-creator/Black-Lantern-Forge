"""Presentation data for the Step 6A connected character mesh."""

from __future__ import annotations

from dataclasses import dataclass

from forge.blades.presentation import compute_normals, compute_uvs
from forge.presentation.materials import Material, validate_material
from forge.presentation.model import ComponentPresentation, PresentationVersions, PresentedSword
from forge_character_studio.model import CharacterAsset

PRESENTATION_ID = "forge.character-presentation"
PRESENTATION_VERSION = 1


@dataclass(frozen=True)
class SkinPattern:
    seed: int
    strength: float = 0.025
    kind: str = "character_skin_v1"

    def factor(self, u: float, v: float) -> float:
        # Small integer-derived variation; deterministic and intentionally subtle.
        x = (int(u * 4096.0) * 0x45D9F3B) ^ (int(v * 4096.0) * 0x119DE1F3) ^ self.seed
        x = ((x ^ (x >> 16)) * 0x45D9F3B) & 0xFFFFFFFF
        n = (x ^ (x >> 16)) / 4294967296.0
        return 1.0 + self.strength * (2.0 * n - 1.0)

    def to_dict(self) -> dict:
        return {"type": self.kind, "seed": self.seed, "strength": self.strength}


def present_character(asset: CharacterAsset) -> PresentedSword:
    if not isinstance(asset, CharacterAsset):
        raise TypeError("present_character expects CharacterAsset")
    normals, normal_indices = compute_normals(asset.body, "crease", -1.0)
    uvs, uv_indices = compute_uvs(asset.body, "box")
    material = Material("body", "neutral_skin", (0.56, 0.36, 0.27), 0.0, 0.72,
                        SkinPattern(asset.seed & 0xFFFFFFFF))
    validate_material(material)
    component = ComponentPresentation("body", normals, normal_indices, uvs, uv_indices, material)
    versions = PresentationVersions(PRESENTATION_VERSION, 1, 1, 1)
    return PresentedSword(asset, versions, (component,))
