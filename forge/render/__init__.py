"""Local preview rendering (Step 2): deterministic software renderer, PNG output.

    from forge.render import DEFAULT_PREVIEW, render_preview, write_preview_png
    image = render_preview(presented, DEFAULT_PREVIEW)
    write_preview_png(image, "output/seed1337_three_quarter.png", presented)

No GPU, no OpenGL, no third-party packages.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from forge.errors import RenderError
from forge.hashing import canonical_json, pixels_sha256
from forge.presentation.model import PresentedSword
from forge.render.camera import Camera, camera_for
from forge.render.png import decode_png, encode_png
from forge.render.raster import render_pixels
from forge.render.settings import DEFAULT_PREVIEW, PREVIEW_VIEWS, SUPPORTED_PREVIEW_VERSIONS, PreviewSettings


@dataclass(frozen=True)
class PreviewImage:
    settings: PreviewSettings
    camera: Camera
    width: int
    height: int
    pixels: bytes  # RGB8, rows top to bottom

    @property
    def pixels_sha256(self) -> str:
        return pixels_sha256(self.width, self.height, self.pixels)


def render_preview(presented: PresentedSword, settings: PreviewSettings) -> PreviewImage:
    if not isinstance(presented, PresentedSword):
        raise RenderError(f"render_preview expects a PresentedSword; got {type(presented).__name__}")
    if not isinstance(settings, PreviewSettings):
        raise RenderError(f"render_preview expects PreviewSettings; got {type(settings).__name__}")
    camera = camera_for(settings.view, settings.width, settings.height)
    pixels = render_pixels(presented, camera, settings.ssaa)
    if len(pixels) != settings.width * settings.height * 3:
        raise RenderError("renderer produced a pixel buffer of the wrong size")
    return PreviewImage(settings, camera, settings.width, settings.height, pixels)


def preview_metadata(presented: PresentedSword, image: PreviewImage,
                     record_content_sha256: str | None = None) -> dict:
    """Deterministic description of a preview (embedded in the PNG). No timestamps."""
    meta = {
        "asset_type": presented.asset.asset_type,
        "seed": str(presented.asset.seed),
        "generator_version": presented.asset.generator_version,
        **presented.versions.to_dict(),
        "preview": image.settings.to_dict(),
        "camera": image.camera.to_dict(),
        "pixels_sha256": image.pixels_sha256,
    }
    if record_content_sha256 is not None:
        meta["record_content_sha256"] = record_content_sha256
    return meta


def encode_preview_png(image: PreviewImage, metadata: dict) -> bytes:
    text = {"Software": "Black Lantern Forge", "forge.preview": canonical_json(metadata).decode("ascii")}
    return encode_png(image.width, image.height, image.pixels, text)


def write_preview_png(image: PreviewImage, path: str | Path, presented: PresentedSword,
                      record_content_sha256: str | None = None) -> Path:
    path = Path(path)
    if path.suffix.lower() != ".png":
        raise RenderError(f"preview path must end in .png; got {str(path)!r}")
    data = encode_preview_png(image, preview_metadata(presented, image, record_content_sha256))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


__all__ = [
    "DEFAULT_PREVIEW",
    "PREVIEW_VIEWS",
    "SUPPORTED_PREVIEW_VERSIONS",
    "PreviewImage",
    "PreviewSettings",
    "decode_png",
    "encode_preview_png",
    "preview_metadata",
    "render_preview",
    "write_preview_png",
]
