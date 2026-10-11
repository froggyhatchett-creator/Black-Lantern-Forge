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


def mesh_sha256(asset: CharacterAsset) -> str:
    digest = hashlib.sha256()
    for p in asset.body.positions:
        digest.update(struct.pack("<3d", *p))
    for triangle in asset.body.triangles:
        digest.update(struct.pack("<3I", *triangle))
    return digest.hexdigest()


def recipe_data(asset: CharacterAsset) -> dict:
    return {
        "contract": {"id": RECIPE_CONTRACT_ID, "version": RECIPE_CONTRACT_VERSION},
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
    if data["contract"] != {"id": RECIPE_CONTRACT_ID, "version": RECIPE_CONTRACT_VERSION}:
        raise ValueError("unsupported character recipe contract")
    if data["generator"] != {"id": GENERATOR_ID, "version": 1}:
        raise ValueError("unsupported character generator")
    if data["body_plan_id"] != "humanoid.neutral.v1":
        raise ValueError("unsupported character body plan")
    try:
        seed = int(data["seed"])
    except (TypeError, ValueError) as exc:
        raise ValueError("recipe seed is not an integer string") from exc
    asset = generate_character(seed, CharacterParameters.from_dict(data["parameters"]), 1)
    if data["integrity"] != {"mesh_sha256": mesh_sha256(asset)}:
        raise ValueError("character recipe integrity check failed")
    return asset
