"""Deterministic software preview for generated characters."""

from __future__ import annotations

from pathlib import Path

from forge.render import encode_preview_png, preview_metadata
from forge.render.fit import render_fit_preview
from forge.render.settings import PreviewSettings
from forge_character_studio.model import CharacterAsset
from forge_character_studio.presentation import present_character


def character_preview(asset: CharacterAsset, view: str = "three_quarter", width: int = 384,
                      height: int = 640, ssaa: int = 1):
    render_view = "front" if view == "back" else view
    if view == "back":
        body = asset.body.mapped(lambda p: (-p[0], p[1], -p[2]))
        asset = CharacterAsset(asset.seed, asset.generator_version, asset.parameters, asset.body_plan_id, body)
    settings = PreviewSettings(1, render_view, width, height, ssaa)
    presented = present_character(asset)
    return presented, render_fit_preview(presented, settings)


def write_character_preview(asset: CharacterAsset, path: str | Path, view: str = "three_quarter") -> Path:
    path = Path(path)
    presented, image = character_preview(asset, view)
    metadata = preview_metadata(presented, image)
    metadata["character_contract"] = {"id": "forge.character-preview", "version": 1}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_preview_png(image, metadata))
    return path


def write_character_preview_set(asset: CharacterAsset, directory: str | Path) -> tuple[Path, ...]:
    directory = Path(directory)
    return tuple(write_character_preview(asset, directory / f"character.{view}.png", view)
                 for view in ("front", "side", "back", "three_quarter"))
