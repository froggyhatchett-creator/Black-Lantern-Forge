"""Deterministic generator for the Blender deformation script.

This module only produces Python source text. It does not invoke Blender and
has no Blender dependency. The emitted script is intended for a pinned Blender
to run later with ``--background --python``.
"""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from forge_character_studio.model import CharacterAsset

_TEMPLATE = """\
# Generated deformation script. Do not edit by hand.
SEED = {seed}
GENERATOR_VERSION = {generator_version}
BODY_PLAN_ID = {body_plan_id}
PARAMETERS = {parameters}
BASE_MESH_PATH = {base_mesh_path}
OUTPUT_GLB_PATH = {output_glb_path}
"""


def _posix_literal(path: Path) -> str:
    # PureWindowsPath treats backslashes as separators on every host OS, so the
    # emitted text is identical regardless of where the generator runs.
    return repr(PureWindowsPath(path).as_posix())


def generate_deform_script(asset: CharacterAsset, base_mesh_path: Path, output_glb_path: Path) -> str:
    """Return the Blender-side deformation script text for ``asset``.

    The output is a pure function of its inputs: the same asset and paths
    always yield a byte-identical string, and paths are rendered with
    ``as_posix()`` so the text does not depend on the host OS.
    """
    parameters = asset.parameters.to_dict()
    parameter_items = ", ".join(f"{name!r}: {parameters[name]!r}" for name in sorted(parameters))
    return _TEMPLATE.format(
        seed=repr(asset.seed),
        generator_version=repr(asset.generator_version),
        body_plan_id=repr(asset.body_plan_id),
        parameters="{" + parameter_items + "}",
        base_mesh_path=_posix_literal(base_mesh_path),
        output_glb_path=_posix_literal(output_glb_path),
    )
