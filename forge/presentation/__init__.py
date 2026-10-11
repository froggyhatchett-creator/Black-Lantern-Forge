"""Step 2 presentation layer: normals, UVs, and materials derived from a frozen SwordAsset.

    from forge import generate_sword
    from forge.presentation import PRESENTATION_V1, derive_presentation
    presented = derive_presentation(generate_sword(1337, 1), PRESENTATION_V1)

Every version is explicit. There is no implicit "latest": PRESENTATION_V1
is a named, frozen bundle. The geometry is read, never modified.
"""

from __future__ import annotations

from forge.errors import PresentationError
from forge.presentation.materials import SUPPORTED_MATERIAL_VERSIONS, Material, select_materials
from forge.presentation.model import ComponentPresentation, PresentationVersions, PresentedSword
from forge.presentation.normals import SUPPORTED_NORMALS_VERSIONS, compute_normals
from forge.presentation.uv import SUPPORTED_UV_VERSIONS, compute_uvs
from forge.sword.asset import SwordAsset
from forge.versioning import require_version

SUPPORTED_PRESENTATION_VERSIONS = (1,)

PRESENTATION_V1 = PresentationVersions(
    presentation_version=1, normals_version=1, uv_version=1, material_version=1
)
LATEST_PRESENTATION = PRESENTATION_V1  # what the CLI writes; always recorded explicitly


def validate_versions(versions: object) -> PresentationVersions:
    if not isinstance(versions, PresentationVersions):
        raise PresentationError(f"expected PresentationVersions; got {type(versions).__name__}")
    require_version("presentation_version", versions.presentation_version, SUPPORTED_PRESENTATION_VERSIONS)
    require_version("normals_version", versions.normals_version, SUPPORTED_NORMALS_VERSIONS)
    require_version("uv_version", versions.uv_version, SUPPORTED_UV_VERSIONS)
    require_version("material_version", versions.material_version, SUPPORTED_MATERIAL_VERSIONS)
    return versions


def derive_presentation(asset: SwordAsset, versions: PresentationVersions) -> PresentedSword:
    """Derive normals, UVs, and materials for a frozen sword. Pure function of (asset, versions)."""
    if not isinstance(asset, SwordAsset):
        raise PresentationError(f"expected SwordAsset; got {type(asset).__name__}")
    validate_versions(versions)
    materials = select_materials(asset.seed, versions.material_version)
    comps = []
    for mesh in asset.components:
        normals, normal_idx = compute_normals(mesh, versions.normals_version)
        uvs, uv_idx = compute_uvs(mesh, versions.uv_version)
        comps.append(ComponentPresentation(
            name=mesh.name, normals=normals, normal_indices=normal_idx,
            uvs=uvs, uv_indices=uv_idx, material=materials[mesh.name],
        ))
    return PresentedSword(asset=asset, versions=versions, components=tuple(comps))


__all__ = [
    "LATEST_PRESENTATION",
    "PRESENTATION_V1",
    "SUPPORTED_PRESENTATION_VERSIONS",
    "ComponentPresentation",
    "Material",
    "PresentationVersions",
    "PresentedSword",
    "derive_presentation",
    "validate_versions",
]
