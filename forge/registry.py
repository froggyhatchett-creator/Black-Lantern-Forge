"""Explicit, versioned, immutable registries (Step 2.5).

Generic Forge infrastructure (record loading, CLI routing, export, preview,
integrity hashing) asks a Registry which implementation to use instead of
knowing about any particular asset family.

Rules (frozen architecture):
  * Every key is an explicit, stable identifier: (id, version). There's no
    implicit "latest", and no lookup works without a version.
  * Registries are built once from explicit entry tuples (see forge/catalog.py)
    and are read-only afterwards: frozen dataclasses over MappingProxyType.
  * No auto-discovery, directory scanning, import side effects, entry points,
    or runtime code loading. This is not a plugin system.
  * Behavior never depends on insertion order: lookups are keyed, and every
    listing is sorted.

This module holds the mechanics only. It contains no asset-family knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping

from forge.conventions import CONVENTIONS
from forge.determinism import require_supported_float_environment
from forge.errors import (
    ExportError,
    GenerationError,
    RegistryConfigurationError,
    UnknownAssetTypeError,
    UnknownExportFormatError,
    UnknownGeneratorError,
    UnknownPresentationError,
    UnknownPreviewError,
    UnsupportedExportVersionError,
    UnsupportedGeneratorVersionError,
    UnsupportedVersionError,
)
from forge.presentation.model import PresentationVersions
from forge.seed import validate_seed
from forge.versioning import require_version


# ------------------------------------------------------------------ entries

@dataclass(frozen=True)
class AssetDescriptor:
    """Routing data for one asset type. Pure data: no callables, no geometry, no state."""

    asset_type: str
    display_name: str
    generator_id: str
    presentation_id: str
    export_formats: tuple[tuple[str, int], ...]   # (format_id, format_version) this asset offers
    preview_id: str | None                         # None = no preview capability
    record_versions: tuple[int, ...]               # asset record schema versions it can be stored in
    convention_id: str                             # key into forge.conventions.CONVENTIONS
    components: tuple[str, ...]                    # component names, in canonical order


@dataclass(frozen=True)
class AssetEntry:
    """An asset type: its descriptor plus the asset-specific hooks generic code calls."""

    descriptor: AssetDescriptor
    # (hash key, fn(asset, presented) -> hex). Order is the verification order.
    integrity: tuple[tuple[str, Callable[[Any, Any], str]], ...]
    # Human-readable parameter lines for CLI summaries.
    summary_lines: Callable[[Any], tuple[str, ...]]


@dataclass(frozen=True)
class GeneratorEntry:
    generator_id: str
    generator_version: int
    asset_type: str
    generate: Callable[[int], Any]  # validated seed -> asset


@dataclass(frozen=True)
class PresentationEntry:
    """One presentation family version pins one implementation of each layer."""

    presentation_id: str
    presentation_version: int
    normals_version: int
    uv_version: int
    material_version: int
    preview_versions: tuple[int, ...]   # preview renderer versions that understand this presentation
    derive: Callable[[Any, PresentationVersions], Any]

    @property
    def versions(self) -> PresentationVersions:
        return PresentationVersions(self.presentation_version, self.normals_version,
                                    self.uv_version, self.material_version)


@dataclass(frozen=True)
class ExportEntry:
    format_id: str
    format_version: int
    extension: str                                  # required output path suffix: ".obj", or a package directory suffix
    presentations: tuple[tuple[str, int], ...]      # accepted (presentation_id, version); () = geometry only
    extra_file_labels: tuple[str, ...]              # labels for files written besides the primary one
    write: Callable[[Any, Any, Path], tuple[Path, ...]]  # (asset, presented|None, path) -> written paths
    # Step 3 (additive): the engine contract (contract_id, version) the output conforms to, or None.
    # An exporter that declares one validates its output against it before writing, and refuses otherwise.
    contract: tuple[str, int] | None = None

    @property
    def needs_presentation(self) -> bool:
        return bool(self.presentations)


@dataclass(frozen=True)
class PreviewEntry:
    preview_id: str
    preview_version: int
    render: Callable[[Any, Any], Any]  # (presented, PreviewSettings) -> PreviewImage


# ------------------------------------------------------------------ registry

def _versions(keys, ident: str) -> tuple[int, ...]:
    return tuple(sorted(v for i, v in keys if i == ident))


def _require_id(value: object, error: type, what: str, known: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in known:
        raise error(f"unknown {what} {value!r}; registered: {list(known)}")
    return value


def _require_int_version(value: object, error: type, field: str, ident: str, supported: tuple[int, ...]) -> int:
    if type(value) is not int or value not in supported:
        raise error(f"unsupported {field} {value!r} for {ident!r}; supported: {list(supported)}")
    return value


@dataclass(frozen=True)
class Registry:
    assets: Mapping[str, AssetEntry]
    generators: Mapping[tuple[str, int], GeneratorEntry]
    presentations: Mapping[tuple[str, int], PresentationEntry]
    exporters: Mapping[tuple[str, int], ExportEntry]
    previews: Mapping[tuple[str, int], PreviewEntry]

    # ---- listings (always sorted; never insertion order)
    def asset_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.assets))

    def generator_ids(self) -> tuple[str, ...]:
        return tuple(sorted({i for i, _ in self.generators}))

    def generator_versions(self, generator_id: str) -> tuple[int, ...]:
        return _versions(self.generators, generator_id)

    def presentation_ids(self) -> tuple[str, ...]:
        return tuple(sorted({i for i, _ in self.presentations}))

    def presentation_versions(self, presentation_id: str) -> tuple[int, ...]:
        return _versions(self.presentations, presentation_id)

    def export_format_ids(self) -> tuple[str, ...]:
        return tuple(sorted({i for i, _ in self.exporters}))

    def export_versions(self, format_id: str) -> tuple[int, ...]:
        return _versions(self.exporters, format_id)

    def preview_ids(self) -> tuple[str, ...]:
        return tuple(sorted({i for i, _ in self.previews}))

    def preview_versions(self, preview_id: str) -> tuple[int, ...]:
        return _versions(self.previews, preview_id)

    # ---- exact lookups: an id AND a version, or failure
    def asset(self, asset_type: object) -> AssetEntry:
        return self.assets[_require_id(asset_type, UnknownAssetTypeError, "asset_type", self.asset_types())]

    def generator(self, generator_id: object, generator_version: object) -> GeneratorEntry:
        gid = _require_id(generator_id, UnknownGeneratorError, "generator", self.generator_ids())
        v = _require_int_version(generator_version, UnsupportedGeneratorVersionError, "generator_version",
                                 gid, self.generator_versions(gid))
        return self.generators[(gid, v)]

    def presentation(self, presentation_id: object, presentation_version: object) -> PresentationEntry:
        pid = _require_id(presentation_id, UnknownPresentationError, "presentation", self.presentation_ids())
        v = _require_int_version(presentation_version, UnsupportedVersionError, "presentation_version",
                                 pid, self.presentation_versions(pid))
        return self.presentations[(pid, v)]

    def exporter(self, format_id: object, format_version: object) -> ExportEntry:
        fid = _require_id(format_id, UnknownExportFormatError, "export format", self.export_format_ids())
        v = _require_int_version(format_version, UnsupportedExportVersionError, "export version",
                                 fid, self.export_versions(fid))
        return self.exporters[(fid, v)]

    def preview(self, preview_id: object, preview_version: object) -> PreviewEntry:
        pid = _require_id(preview_id, UnknownPreviewError, "preview renderer", self.preview_ids())
        v = _require_int_version(preview_version, UnsupportedVersionError, "preview_version",
                                 pid, self.preview_versions(pid))
        return self.previews[(pid, v)]


def _index(entries, key, what: str) -> Mapping:
    table: dict = {}
    for entry in entries:
        k = key(entry)
        if k in table:
            raise RegistryConfigurationError(f"duplicate {what} registration {k!r}")
        table[k] = entry
    return MappingProxyType(table)


def build_registry(*, assets, generators, presentations, exporters, previews) -> Registry:
    """Build an immutable Registry from explicit entry tuples and check every cross-reference."""
    reg = Registry(
        assets=_index(assets, lambda e: e.descriptor.asset_type, "asset type"),
        generators=_index(generators, lambda e: (e.generator_id, e.generator_version), "generator"),
        presentations=_index(presentations, lambda e: (e.presentation_id, e.presentation_version), "presentation"),
        exporters=_index(exporters, lambda e: (e.format_id, e.format_version), "exporter"),
        previews=_index(previews, lambda e: (e.preview_id, e.preview_version), "preview"),
    )
    for entry in reg.assets.values():
        d = entry.descriptor
        where = f"asset type {d.asset_type!r}"
        gens = [g for g in reg.generators.values() if g.generator_id == d.generator_id]
        if not gens or any(g.asset_type != d.asset_type for g in gens):
            raise RegistryConfigurationError(f"{where}: generator {d.generator_id!r} missing or bound to another asset type")
        if not reg.presentation_versions(d.presentation_id):
            raise RegistryConfigurationError(f"{where}: presentation {d.presentation_id!r} not registered")
        for fmt in d.export_formats:
            if fmt not in reg.exporters:
                raise RegistryConfigurationError(f"{where}: export format {fmt!r} not registered")
        if d.preview_id is not None and not reg.preview_versions(d.preview_id):
            raise RegistryConfigurationError(f"{where}: preview renderer {d.preview_id!r} not registered")
        if d.convention_id not in CONVENTIONS:
            raise RegistryConfigurationError(f"{where}: unknown coordinate convention {d.convention_id!r}")
        keys = [k for k, _ in entry.integrity]
        if len(set(keys)) != len(keys) or "record_content_sha256" in keys:
            raise RegistryConfigurationError(f"{where}: integrity hash keys must be unique and not record_content_sha256")
    return reg


# ------------------------------------------------------------------ generic dispatch

def generate_asset(registry: Registry, asset_type: str, seed: int, generator_version: int):
    """asset_type -> descriptor -> (generator_id, generator_version) -> frozen generator."""
    entry = registry.asset(asset_type)
    gen = registry.generator(entry.descriptor.generator_id, generator_version)
    seed = validate_seed(seed)
    require_supported_float_environment()
    asset = gen.generate(seed)
    if (asset.asset_type, asset.generator, asset.generator_version, asset.seed) != (
            entry.descriptor.asset_type, gen.generator_id, gen.generator_version, seed):
        raise GenerationError(f"generator {gen.generator_id!r} v{gen.generator_version} returned a mismatched asset")
    return asset


def presentation_for(registry: Registry, asset, presentation_version: int) -> PresentationEntry:
    entry = registry.asset(asset.asset_type)
    return registry.presentation(entry.descriptor.presentation_id, presentation_version)


def check_presentation_versions(pres: PresentationEntry, versions: PresentationVersions) -> None:
    """The family version pins exactly one normals/uv/material version each."""
    require_version("presentation_version", versions.presentation_version, (pres.presentation_version,))
    require_version("normals_version", versions.normals_version, (pres.normals_version,))
    require_version("uv_version", versions.uv_version, (pres.uv_version,))
    require_version("material_version", versions.material_version, (pres.material_version,))


def present_asset(registry: Registry, asset, versions: PresentationVersions):
    """asset_type -> presentation_id + presentation_version -> pinned layer versions -> derive."""
    if not isinstance(versions, PresentationVersions):
        raise UnsupportedVersionError(f"presentation versions must be PresentationVersions; got {versions!r}")
    pres = presentation_for(registry, asset, versions.presentation_version)
    check_presentation_versions(pres, versions)
    return pres.derive(asset, versions)


def _check_presented(registry: Registry, asset, presented, accepted: tuple[tuple[str, int], ...], what: str):
    if presented is None:
        raise UnsupportedVersionError(f"{what} needs presentation data; none was derived")
    if presented.asset is not asset:
        raise ExportError(f"{what}: presentation belongs to a different asset")
    pres = presentation_for(registry, asset, presented.versions.presentation_version)
    check_presentation_versions(pres, presented.versions)
    key = (pres.presentation_id, pres.presentation_version)
    if key not in accepted:
        raise UnsupportedVersionError(f"{what} does not accept presentation {key!r}; accepts {list(accepted)}")
    return pres


def exporter_for(registry: Registry, asset_type: str, format_id: str, format_version: int) -> ExportEntry:
    """Resolve an exporter AND check that the asset type offers it."""
    d = registry.asset(asset_type).descriptor
    exp = registry.exporter(format_id, format_version)
    if (exp.format_id, exp.format_version) not in d.export_formats:
        offered = sorted(v for f, v in d.export_formats if f == exp.format_id)
        if offered:
            raise UnsupportedExportVersionError(
                f"asset_type {asset_type!r} offers export {format_id!r} at versions {offered}, not {format_version}")
        raise UnknownExportFormatError(f"asset_type {asset_type!r} does not offer export format {format_id!r}")
    return exp


def export_asset(registry: Registry, asset, presented, format_id: str, format_version: int, path) -> tuple[Path, ...]:
    exp = exporter_for(registry, asset.asset_type, format_id, format_version)
    if exp.needs_presentation:
        _check_presented(registry, asset, presented, exp.presentations, f"export {format_id}:{format_version}")
    path = Path(path)
    if path.suffix.lower() != exp.extension:
        raise ExportError(f"output path must end in {exp.extension}; got {str(path)!r}")
    return exp.write(asset, presented if exp.needs_presentation else None, path)


def preview_for(registry: Registry, asset_type: str, presentation_version: int, preview_version: int) -> PreviewEntry:
    """Resolve the preview renderer an asset type + presentation version can use at this preview version."""
    d = registry.asset(asset_type).descriptor
    if d.preview_id is None:
        raise UnknownPreviewError(f"asset_type {asset_type!r} has no preview capability")
    renderer = registry.preview(d.preview_id, preview_version)
    pres = registry.presentation(d.presentation_id, presentation_version)
    require_version("preview_version", preview_version, pres.preview_versions)
    return renderer


def render_asset_preview(registry: Registry, presented, settings):
    asset = presented.asset
    renderer = preview_for(registry, asset.asset_type, presented.versions.presentation_version,
                           settings.preview_version)
    pres = presentation_for(registry, asset, presented.versions.presentation_version)
    check_presentation_versions(pres, presented.versions)
    return renderer.render(presented, settings)


def integrity_hashes(registry: Registry, presented) -> dict:
    """The asset type's integrity hashes, keyed and ordered as the asset entry declares."""
    entry = registry.asset(presented.asset.asset_type)
    return {key: fn(presented.asset, presented) for key, fn in entry.integrity}
