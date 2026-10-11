"""Wavefront OBJ export for SwordAsset.

Output contract (obj_format 1):
  * ASCII only, LF line endings, trailing newline, no timestamps or paths.
  * Header comments record asset type, generator, generator_version, seed,
    units and axis convention.
  * One `o <component>` block per component, in COMPONENT_ORDER:
      v lines (component's vertices, in mesh order), `s off`, f lines.
  * Coordinates are fixed-point with 6 decimals (1 micrometer resolution);
    "-0.000000" is normalized to "0.000000".
  * Faces are triangles with global 1-based indices, counter-clockwise = front.
  * No normals, UVs, or materials (no .mtl) in Step 1.

Same asset -> same bytes. Formatting relies on CPython's correctly rounded
float formatting, which is platform-independent for binary64.
"""

from __future__ import annotations

import math
from pathlib import Path

from forge.errors import ExportError
from forge.sword.asset import SwordAsset

OBJ_FORMAT_VERSION = 1
COORD_DECIMALS = 6
_NEG_ZERO = "-" + "0." + "0" * COORD_DECIMALS
_POS_ZERO = _NEG_ZERO[1:]


def format_coord(value: float) -> str:
    if type(value) is not float or not math.isfinite(value):
        raise ExportError(f"cannot export non-finite or non-float coordinate {value!r}")
    text = f"{value:.{COORD_DECIMALS}f}"
    return _POS_ZERO if text == _NEG_ZERO else text


def export_obj(asset: SwordAsset) -> str:
    """Return the OBJ document for `asset` as a str."""
    if not isinstance(asset, SwordAsset):
        raise ExportError(f"export_obj expects a SwordAsset; got {type(asset).__name__}")

    lines = [
        "# Black Lantern Forge OBJ export",
        f"# obj_format: {OBJ_FORMAT_VERSION}",
        f"# asset_type: {asset.asset_type}",
        f"# generator: {asset.generator}",
        f"# generator_version: {asset.generator_version}",
        f"# seed: {asset.seed}",
        "# units: meters",
        "# axes: right-handed, +Y up, blade tip +Y, blade edges +/-X, origin at grip center",
        "# winding: counter-clockwise front faces (outward normals)",
        f"# components: {' '.join(asset.component_names)}",
        f"# vertices: {asset.vertex_count}",
        f"# triangles: {asset.triangle_count}",
    ]
    offset = 1  # OBJ indices are 1-based and global across the file
    for mesh in asset.components:
        lines.append(f"o {mesh.name}")
        for x, y, z in mesh.positions:
            lines.append(f"v {format_coord(x)} {format_coord(y)} {format_coord(z)}")
        lines.append("s off")
        for a, b, c in mesh.triangles:
            lines.append(f"f {a + offset} {b + offset} {c + offset}")
        offset += mesh.vertex_count

    text = "\n".join(lines) + "\n"
    if not text.isascii():
        raise ExportError("OBJ output contains non-ASCII characters")
    return text


def obj_bytes(asset: SwordAsset) -> bytes:
    return export_obj(asset).encode("ascii")


def write_obj(asset: SwordAsset, path: str | Path) -> Path:
    """Write the OBJ file (bytes, so no platform newline translation). Creates parent dirs."""
    path = Path(path)
    if path.suffix.lower() != ".obj":
        raise ExportError(f"output path must end in .obj; got {str(path)!r}")
    data = obj_bytes(asset)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path
