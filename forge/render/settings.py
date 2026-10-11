"""Preview settings (part of the persisted presentation state)."""

from __future__ import annotations

from dataclasses import dataclass

from forge.errors import RenderError
from forge.versioning import require_version

SUPPORTED_PREVIEW_VERSIONS = (1,)
PREVIEW_VIEWS = ("three_quarter", "front", "side")
SIZE_RANGE = (16, 4096)
SSAA_RANGE = (1, 4)


@dataclass(frozen=True)
class PreviewSettings:
    preview_version: int
    view: str
    width: int
    height: int
    ssaa: int  # supersampling factor per axis (ssaa x ssaa samples per pixel)

    def __post_init__(self) -> None:
        require_version("preview_version", self.preview_version, SUPPORTED_PREVIEW_VERSIONS)
        if self.view not in PREVIEW_VIEWS:
            raise RenderError(f"unknown preview view {self.view!r}; known: {list(PREVIEW_VIEWS)}")
        for name, value, (lo, hi) in (("width", self.width, SIZE_RANGE), ("height", self.height, SIZE_RANGE),
                                      ("ssaa", self.ssaa, SSAA_RANGE)):
            if type(value) is not int or not lo <= value <= hi:
                raise RenderError(f"preview {name} must be an int in [{lo}, {hi}]; got {value!r}")

    def to_dict(self) -> dict:
        return {"preview_version": self.preview_version, "view": self.view,
                "width": self.width, "height": self.height, "ssaa": self.ssaa}


DEFAULT_PREVIEW = PreviewSettings(preview_version=1, view="three_quarter", width=480, height=960, ssaa=2)
