"""Future integration boundaries; no provider or Motion Studio implementation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class SourceReference:
    path: Path
    media_type: str
    incomplete: bool = False


@dataclass(frozen=True)
class CharacterDNA:
    """Thin reference to a forge.character-recipe v3 file (loaded via load_recipe_v3)."""

    contract_id: str
    contract_version: int
    recipe_path: Path


class ReconstructionProvider(Protocol):
    provider_id: str

    def reconstruct(self, references: tuple[SourceReference, ...], output: Path) -> CharacterDNA: ...


class RiggingProvider(Protocol):
    provider_id: str

    def rig(self, character_glb: Path, output: Path) -> Path: ...


class ClothingProvider(Protocol):
    provider_id: str

    def fit(self, character_glb: Path, garment_recipe: Path, output: Path) -> Path: ...


class MotionStudioBridge(Protocol):
    """Interface only. Claude's experimental Motion Studio remains external."""

    bridge_id: str

    def accept_character(self, character_glb: Path, character_recipe: Path) -> str: ...
