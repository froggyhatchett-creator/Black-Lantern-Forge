"""Canonical save/reload contract for deterministic character regeneration."""

from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

from forge.hashing import canonical_json
from forge_character_studio.generate import generate_character
from forge_character_studio.model import (
    CharacterAsset,
    CharacterParameters,
    GENERATOR_ID,
    RECIPE_CONTRACT_ID,
    RECIPE_CONTRACT_VERSION,
)
from forge_character_studio.provenance import BaseMeshRef

RECIPE_CONTRACT_VERSION_V3 = 3  # deliberately decoupled from generator_version (v1/v2 used it)


def mesh_sha256(asset: CharacterAsset) -> str:
    digest = hashlib.sha256()
    for p in asset.body.positions:
        digest.update(struct.pack("<3d", *p))
    for triangle in asset.body.triangles:
        digest.update(struct.pack("<3I", *triangle))
    return digest.hexdigest()


def recipe_data(asset: CharacterAsset) -> dict:
    return {
        "contract": {"id": RECIPE_CONTRACT_ID, "version": asset.generator_version},
        "generator": {"id": GENERATOR_ID, "version": asset.generator_version},
        "body_plan_id": asset.body_plan_id,
        "seed": str(asset.seed),
        "parameters": asset.parameters.to_dict(),
        "integrity": {"mesh_sha256": mesh_sha256(asset)},
    }


def save_recipe(asset: CharacterAsset, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise ValueError("character recipe path must end in .json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(recipe_data(asset)) + b"\n")
    return path


def load_recipe(path: str | Path) -> CharacterAsset:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read character recipe: {exc}") from exc
    if set(data) != {"contract", "generator", "body_plan_id", "seed", "parameters", "integrity"}:
        raise ValueError("character recipe has missing or unknown sections")
    contract = data["contract"]
    if contract not in ({"id": RECIPE_CONTRACT_ID, "version": 1},
                        {"id": RECIPE_CONTRACT_ID, "version": 2}):
        raise ValueError("unsupported character recipe contract")
    generator = data["generator"]
    if generator not in ({"id": GENERATOR_ID, "version": 1}, {"id": GENERATOR_ID, "version": 2}):
        raise ValueError("unsupported character generator")
    if data["body_plan_id"] not in ("humanoid.neutral.v1", "humanoid.neutral.v2"):
        raise ValueError("unsupported character body plan")
    try:
        seed = int(data["seed"])
    except (TypeError, ValueError) as exc:
        raise ValueError("recipe seed is not an integer string") from exc
    asset = generate_character(seed, CharacterParameters.from_dict(data["parameters"]), generator["version"])
    if data["integrity"] != {"mesh_sha256": mesh_sha256(asset)}:
        raise ValueError("character recipe integrity check failed")
    return asset


def _require_build(value: object) -> None:
    if type(value) is not str or not value.strip():
        raise ValueError(f"blender_build must be a non-empty string; got {value!r}")


def recipe_data_v3(asset: CharacterAsset, base_mesh: BaseMeshRef, blender_build: str) -> dict:
    _require_build(blender_build)
    data = recipe_data(asset)
    data["contract"] = {"id": RECIPE_CONTRACT_ID, "version": RECIPE_CONTRACT_VERSION_V3}
    data["pipeline"] = {
        "base_mesh": {
            "source_name": base_mesh.source_name,
            "version": base_mesh.version,
            "archive_sha256": base_mesh.archive_sha256,
        },
        "blender_build": blender_build,
    }
    return data


def save_recipe_v3(asset: CharacterAsset, base_mesh: BaseMeshRef, blender_build: str, path: str | Path) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".json":
        raise ValueError("character recipe path must end in .json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json(recipe_data_v3(asset, base_mesh, blender_build)) + b"\n")
    return path


def load_recipe_v3(path: str | Path) -> tuple[CharacterAsset, BaseMeshRef, str]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read character recipe: {exc}") from exc
    if not isinstance(data, dict) or set(data) != {"contract", "generator", "body_plan_id", "seed",
                                                    "parameters", "integrity", "pipeline"}:
        raise ValueError("character recipe has missing or unknown sections")
    if data["contract"] != {"id": RECIPE_CONTRACT_ID, "version": RECIPE_CONTRACT_VERSION_V3}:
        raise ValueError("unsupported character recipe contract")
    generator = data["generator"]
    if generator not in ({"id": GENERATOR_ID, "version": 1}, {"id": GENERATOR_ID, "version": 2}):
        raise ValueError("unsupported character generator")
    if data["body_plan_id"] not in ("humanoid.neutral.v1", "humanoid.neutral.v2"):
        raise ValueError("unsupported character body plan")
    try:
        seed = int(data["seed"])
    except (TypeError, ValueError) as exc:
        raise ValueError("recipe seed is not an integer string") from exc
    asset = generate_character(seed, CharacterParameters.from_dict(data["parameters"]), generator["version"])
    if data["integrity"] != {"mesh_sha256": mesh_sha256(asset)}:
        raise ValueError("character recipe integrity check failed")
    pipeline = data["pipeline"]
    if not isinstance(pipeline, dict) or set(pipeline) != {"base_mesh", "blender_build"}:
        raise ValueError("character recipe pipeline section is missing or malformed")
    base = pipeline["base_mesh"]
    if not isinstance(base, dict) or set(base) != {"source_name", "version", "archive_sha256"}:
        raise ValueError("character recipe base_mesh section is missing or malformed")
    base_mesh = BaseMeshRef(source_name=base["source_name"], version=base["version"],
                            archive_sha256=base["archive_sha256"])
    _require_build(pipeline["blender_build"])
    return asset, base_mesh, pipeline["blender_build"]
