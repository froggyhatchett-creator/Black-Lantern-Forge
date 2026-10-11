"""Black Lantern Forge - deterministic procedural asset generation.

Step 1 (frozen): procedural short sword + OBJ export.
Step 2: presentation (normals, UVs, materials), asset records, local preview.

    from forge import generate_sword, write_obj
    sword = generate_sword(seed=1337, generator_version=1)
    write_obj(sword, "output/sword_1337.obj")

Step 2 lives in forge.presentation, forge.record, forge.render, and
forge.export.obj_enriched (imported on demand; Step 1 imports are unchanged).

Step 2.5: generic infrastructure dispatches through explicit, versioned,
immutable registries (forge.registry); every registered entry is listed in
forge.catalog. The short sword is one registered asset type (forge.assets.short_sword).

Step 2.75: Forge Desktop, a Tkinter shell in the separate `forge_desktop` package
(python -m forge_desktop, or python -m forge.gui). The core never imports it.

Step 3: Forge -> Engine Asset Contract v1 (forge.engine). Export glb:1 writes a
package directory: asset.glb (binary glTF 2.0, written directly, byte-stable) and
manifest.json. forge.engine.validate checks a package without the generator.
"""

from forge.errors import (
    EnvironmentNotSupportedError,
    ExportError,
    ForgeError,
    GenerationError,
    GeometryError,
    InvalidSeedError,
    UnsupportedGeneratorVersionError,
)
from forge.export.obj import export_obj, obj_bytes, write_obj
from forge.sword import (
    LATEST_SWORD_VERSION,
    SUPPORTED_SWORD_VERSIONS,
    SwordAsset,
    generate_sword,
)

__version__ = "0.6.0"

__all__ = [
    "EnvironmentNotSupportedError",
    "ExportError",
    "ForgeError",
    "GenerationError",
    "GeometryError",
    "InvalidSeedError",
    "LATEST_SWORD_VERSION",
    "SUPPORTED_SWORD_VERSIONS",
    "SwordAsset",
    "UnsupportedGeneratorVersionError",
    "export_obj",
    "generate_sword",
    "obj_bytes",
    "write_obj",
]
