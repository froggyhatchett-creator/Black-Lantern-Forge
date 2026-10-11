"""The viewer's own reading of Forge -> Engine Asset Contract v1.

These constants are copied from the contract document
(docs/FORGE_ENGINE_CONTRACT_V1.md); none of them are imported from Forge. That
keeps the consumer independent: if Forge's own contract table changed, this
viewer would not quietly start accepting something different.
tests/test_viewer_independence.py compares this table with Forge's, so any
drift between the two shows up as a failing test.

Only what an ingesting engine needs is listed here. This is not a general glTF
profile.
"""

from __future__ import annotations

from types import MappingProxyType

CONTRACT_ID = "forge.engine-contract"
SUPPORTED_VERSIONS = (1,)

GLB_FILE = "asset.glb"
MANIFEST_FILE = "manifest.json"
PACKAGE_SUFFIX = ".forgepkg"

# GLB / glTF 2.0
GLB_MAGIC = 0x46546C67            # b"glTF"
GLB_VERSION = 2
CHUNK_JSON = 0x4E4F534A           # b"JSON"
CHUNK_BIN = 0x004E4942            # b"BIN\0"
GLTF_VERSION = "2.0"
FLOAT, UNSIGNED_SHORT, UNSIGNED_INT = 5126, 5123, 5125
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963
TRIANGLES = 4

# Scenes and nodes
RENDER_SCENE = "forge_render"           # default scene, index 0
COLLISION_SCENE = "forge_collision"     # index 1
REQUIRED_SOCKETS = ("socket_grip", "socket_tip")
SOCKET_PREFIX = "socket_"
ORIGIN_SOCKET = "socket_grip"
COLLISION_NODE = "collision_hull"
COLLISION_REPRESENTATIONS = ("convex_hull",)
RENDER_ATTRIBUTES = ("POSITION", "NORMAL", "TEXCOORD_0")
COLLISION_ATTRIBUTES = ("POSITION",)
LOD_LEVELS = (0,)

# Coordinates: canonical, required exactly
COORDINATES = MappingProxyType({
    "handedness": "right",
    "up_axis": "+Y",
    "units": "meters",
    "meters_per_unit": 1,
    "origin": "grip_center",
    "front_face_winding": "counter_clockwise",
})
KNOWN_ORIGINS = ("grip_center",)

MANIFEST_SECTIONS = ("asset", "collision", "contract", "coordinates", "hashes", "lods", "materials",
                     "package", "presentation", "sockets", "tags")
MATERIAL_MODEL = "pbr_metallic_roughness"
CHANNELS = ("base_color", "metallic_roughness", "normal", "occlusion", "emissive")

# Hashes the viewer recomputes from the package (names from contract section 13).
BYTE_HASHES = ("glb_sha256", "gltf_json_sha256", "gltf_bin_sha256")
SEMANTIC_HASHES = ("render_geometry_sha256", "collision_sha256", "sockets_sha256", "pbr_materials_sha256",
                   "semantic_sha256")
CONTENT_HASH = "manifest_content_sha256"
SOURCE_HASH_PREFIX = "source_"          # provenance only: not verifiable from a package
RENDER_GEOMETRY_TAG = b"forge.engine.render-geometry.v1\0"
COLLISION_TAG = b"forge.engine.collision.v1\0"
