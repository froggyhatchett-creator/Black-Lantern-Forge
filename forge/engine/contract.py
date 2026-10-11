"""Forge -> Engine Asset Contract: the versioned definition (data only).

A contract version is a frozen table of names, required values and manifest
schema. Contract v1 is defined here. A changed rule is a new version, and v1
stays as it is. Nothing here picks a version for the caller: every lookup takes
an explicit version (no implicit "latest").

The writer (forge.engine.package) and the independent validator
(forge.engine.validate) both read these tables. Apart from them, the two share
no code.
See docs/FORGE_ENGINE_CONTRACT_V1.md for the prose version of this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from forge.errors import EngineContractError

CONTRACT_ID = "forge.engine-contract"
CONTRACT_NAME = "Forge -> Engine Asset Contract"

# ---- GLB / glTF 2.0 constants (from the glTF 2.0 specification)
GLB_MAGIC = 0x46546C67          # b"glTF" little-endian
GLB_VERSION = 2
GLB_HEADER_BYTES = 12
GLB_CHUNK_HEADER_BYTES = 8
CHUNK_JSON = 0x4E4F534A         # b"JSON"
CHUNK_BIN = 0x004E4942          # b"BIN\0"
GLTF_VERSION = "2.0"

COMPONENT_FLOAT = 5126
COMPONENT_UNSIGNED_SHORT = 5123
COMPONENT_UNSIGNED_INT = 5125
TARGET_ARRAY_BUFFER = 34962
TARGET_ELEMENT_ARRAY_BUFFER = 34963
MODE_TRIANGLES = 4

# ---- channel states a manifest may declare for a material channel
CHANNEL_FACTOR = "factor"        # constant factor only, no texture
CHANNEL_TEXTURE = "texture"      # texture (times its factor)
CHANNEL_ABSENT = "absent"        # neither: the glTF default applies
CHANNEL_STATES = (CHANNEL_ABSENT, CHANNEL_FACTOR, CHANNEL_TEXTURE)


@dataclass(frozen=True)
class ContractSpec:
    """Everything a package must satisfy for one contract version."""

    contract_id: str
    name: str
    version: int
    package_suffix: str                       # suffix of the package directory
    glb_file: str
    manifest_file: str
    render_scene: str                         # name of the default scene (index 0)
    collision_scene: str                      # name of the collision-only scene (index 1)
    required_sockets: tuple[str, ...]
    socket_prefix: str
    collision_node: str
    collision_representations: tuple[str, ...]
    coordinates: Mapping[str, object]         # required coordinate values, exactly
    origin_socket: str                        # socket that must sit exactly at the origin
    material_model: str
    channels: tuple[str, ...]                 # material channels the contract supports
    lod_levels: tuple[int, ...]               # LOD levels a v1 package may declare
    manifest_sections: tuple[str, ...]        # exact top-level manifest keys
    package_hashes: Mapping[str, str]         # hash name -> what it covers (verifiable from the package)
    source_hash_prefix: str                   # provenance hashes: "source_<integrity key>"
    content_hash: str                         # the manifest's self-hash entry


CONTRACT_V1 = ContractSpec(
    contract_id=CONTRACT_ID,
    name=CONTRACT_NAME,
    version=1,
    package_suffix=".forgepkg",
    glb_file="asset.glb",
    manifest_file="manifest.json",
    render_scene="forge_render",
    collision_scene="forge_collision",
    required_sockets=("socket_grip", "socket_tip"),
    socket_prefix="socket_",
    collision_node="collision_hull",
    collision_representations=("convex_hull",),
    coordinates=MappingProxyType({
        "handedness": "right",
        "up_axis": "+Y",
        "units": "meters",
        "meters_per_unit": 1,
        "origin": "grip_center",
        "front_face_winding": "counter_clockwise",
    }),
    origin_socket="socket_grip",
    material_model="pbr_metallic_roughness",
    channels=("base_color", "metallic_roughness", "normal", "occlusion", "emissive"),
    lod_levels=(0,),
    manifest_sections=("asset", "collision", "contract", "coordinates", "hashes", "lods", "materials",
                       "package", "presentation", "sockets", "tags"),
    package_hashes=MappingProxyType({
        "glb_sha256": "every byte of asset.glb",
        "gltf_json_sha256": "the GLB JSON chunk data exactly as stored, including its trailing space padding",
        "gltf_bin_sha256": "the GLB BIN chunk data exactly as stored, including its trailing zero padding",
        "render_geometry_sha256": (
            "semantic, layout-independent: b'forge.engine.render-geometry.v1\\0' then, per LOD0 render node in "
            "manifest order: node name, NUL, material name, NUL, u32 vertex count, u32 index count, POSITION "
            "3xf32, NORMAL 3xf32, TEXCOORD_0 2xf32, indices as u32; little-endian"),
        "collision_sha256": (
            "semantic: b'forge.engine.collision.v1\\0', node name, NUL, u32 vertex count, u32 index count, "
            "POSITION 3xf32, indices as u32; little-endian"),
        "sockets_sha256": "canonical JSON of [{name, parent, translation, rotation}] for each socket node, in node order",
        "pbr_materials_sha256": "canonical JSON of the glTF materials array exactly as stored in the GLB",
        "semantic_sha256": (
            "canonical JSON of {contract: {id, version}, coordinates, lods, collision_sha256, "
            "pbr_materials_sha256, render_geometry_sha256, sockets_sha256}"),
    }),
    source_hash_prefix="source_",
    content_hash="manifest_content_sha256",
)

CONTRACTS: Mapping[int, ContractSpec] = MappingProxyType({CONTRACT_V1.version: CONTRACT_V1})
SUPPORTED_CONTRACT_VERSIONS: tuple[int, ...] = tuple(sorted(CONTRACTS))

CONTENT_HASH_COVERS = "canonical JSON of this manifest with hashes.manifest_content_sha256 removed"


def contract_spec(version: object) -> ContractSpec:
    """The contract at exactly this version, or EngineContractError."""
    if type(version) is not int or version not in CONTRACTS:
        raise EngineContractError(f"unsupported contract version {version!r}; supported: "
                                  f"{list(SUPPORTED_CONTRACT_VERSIONS)}")
    return CONTRACTS[version]
