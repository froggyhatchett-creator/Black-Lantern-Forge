"""ForgeController: the only bridge between the desktop shell and the Forge core.

Every operation goes through the frozen, registry-driven pipeline:

  generate  registry.asset -> generate_asset (explicit generator version)
            -> registry.presentation(explicit version) -> present_asset
  preview   render_asset_preview (explicit preview version + view)
  save/load forge.record (the Step 2 record format, unchanged)
  export    export_asset (only formats the asset type's descriptor offers). An
            exporter that declares an engine contract (Step 3: glb:1) is shown
            as an engine package; the contract comes from the registry entry.

The controller never imports or names an asset family's implementation. It
holds no state of its own beyond the registry it was given and the default
preview size, and it never mutates either. No tkinter here, so it's fully
testable without a display.

Failures the user should see come back as ForgeActionError (title + plain
message). Anything else is a bug and propagates.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from forge.catalog import REGISTRY
from forge.errors import ForgeError, RecordIntegrityError
from forge.record import build_record, load_record, save_record
from forge.registry import (
    Registry,
    export_asset,
    generate_asset,
    integrity_hashes,
    present_asset,
    render_asset_preview,
)
from forge.render import write_preview_png
from forge.render.settings import DEFAULT_PREVIEW, PREVIEW_VIEWS, PreviewSettings
from forge.seed import parse_seed


class ForgeActionError(Exception):
    """A user-facing failure: a short title and a plain-language message."""

    def __init__(self, title: str, message: str):
        super().__init__(f"{title}: {message}")
        self.title = title
        self.message = message


@dataclass(frozen=True)
class ExportChoice:
    format_id: str
    format_version: int
    extension: str
    needs_presentation: bool
    extra_files: tuple[str, ...]
    contract: tuple[str, int] | None = None      # engine contract (id, version) the output conforms to

    @property
    def key(self) -> str:
        return f"{self.format_id}:{self.format_version}"

    @property
    def label(self) -> str:
        parts = [f"{self.format_id.upper()} format {self.format_version}",
                 "with presentation data" if self.needs_presentation else "geometry only"]
        parts += [f"+ {name} file" for name in self.extra_files]
        if self.contract is not None:
            parts.append(self.contract_label)
        return " · ".join(parts)

    @property
    def contract_label(self) -> str:
        return f"{self.contract[0]} v{self.contract[1]}" if self.contract else "none"

    @property
    def action_label(self) -> str:
        return "Export Engine Package…" if self.contract is not None else "Export…"


@dataclass(frozen=True)
class AssetOptions:
    """What the selectors may offer for one asset type. All of it comes from the registry."""
    asset_type: str
    display_name: str
    generator_id: str
    generator_versions: tuple[int, ...]
    presentation_id: str
    presentation_versions: tuple[int, ...]
    preview_id: str | None
    views: tuple[str, ...]
    exporters: tuple[ExportChoice, ...]
    convention_id: str

    def exporter(self, key: str) -> ExportChoice | None:
        for choice in self.exporters:
            if choice.key == key:
                return choice
        return None


@dataclass(frozen=True)
class AssetResult:
    """An immutable snapshot of one generated (or reloaded) asset and its presentation."""
    options: AssetOptions
    seed: int
    generator_version: int
    asset: object
    presented: object
    integrity: tuple[tuple[str, str], ...]   # registry-declared order
    summary: tuple[str, ...]
    source: str                              # "generated" or the record path it came from

    @property
    def asset_type(self) -> str:
        return self.options.asset_type

    @property
    def versions(self):
        return self.presented.versions


@dataclass(frozen=True)
class LoadedRecord:
    result: AssetResult
    path: Path
    record_content_sha256: str
    checks: tuple[str, ...]
    preview: PreviewSettings | None
    expected_pixels_sha256: str | None


def _view_label(view: str) -> str:
    return view.replace("_", "-").capitalize()


class ForgeController:
    def __init__(self, registry: Registry = REGISTRY, preview_size: tuple[int, int, int] | None = None):
        self._registry = registry
        self._preview_size = preview_size or (DEFAULT_PREVIEW.width, DEFAULT_PREVIEW.height, DEFAULT_PREVIEW.ssaa)

    @property
    def registry(self) -> Registry:
        return self._registry

    # ------------------------------------------------------------ choices (registry-driven)

    def asset_types(self) -> tuple[str, ...]:
        return self._registry.asset_types()

    def options(self, asset_type: str) -> AssetOptions:
        try:
            entry = self._registry.asset(asset_type)
        except ForgeError as exc:
            raise ForgeActionError("Unknown asset type", str(exc)) from exc
        d = entry.descriptor
        exporters = []
        for format_id, version in sorted(d.export_formats):
            exp = self._registry.exporter(format_id, version)
            exporters.append(ExportChoice(exp.format_id, exp.format_version, exp.extension,
                                          exp.needs_presentation, exp.extra_file_labels, exp.contract))
        return AssetOptions(
            asset_type=d.asset_type, display_name=d.display_name,
            generator_id=d.generator_id, generator_versions=self._registry.generator_versions(d.generator_id),
            presentation_id=d.presentation_id,
            presentation_versions=self._registry.presentation_versions(d.presentation_id),
            preview_id=d.preview_id, views=PREVIEW_VIEWS if d.preview_id is not None else (),
            exporters=tuple(exporters), convention_id=d.convention_id,
        )

    def preview_versions(self, asset_type: str, presentation_version: int | None) -> tuple[int, ...]:
        """Preview versions that are registered AND understood by this presentation version."""
        opts = self.options(asset_type)
        if opts.preview_id is None or presentation_version is None:
            return ()
        try:
            family = self._registry.presentation(opts.presentation_id, presentation_version)
        except ForgeError as exc:
            raise ForgeActionError("Unsupported presentation version", str(exc)) from exc
        registered = set(self._registry.preview_versions(opts.preview_id))
        return tuple(v for v in sorted(family.preview_versions) if v in registered)

    # ------------------------------------------------------------ generate

    def generate(self, asset_type: str, seed_text: str, generator_version: int | None,
                 presentation_version: int | None) -> AssetResult:
        opts = self.options(asset_type)
        if generator_version is None:
            raise ForgeActionError("Choose a generator version",
                                   f"Pick one of {list(opts.generator_versions)} for {opts.generator_id}.")
        if presentation_version is None:
            raise ForgeActionError("Choose a presentation version",
                                   f"Pick one of {list(opts.presentation_versions)} for {opts.presentation_id}.")
        try:
            seed = parse_seed(seed_text.strip() if isinstance(seed_text, str) else seed_text)
        except ForgeError as exc:
            raise ForgeActionError("Invalid seed", "Seeds are whole numbers from 0 to 18446744073709551615, "
                                   f"digits only. You entered {seed_text!r}.") from exc
        try:
            asset = generate_asset(self._registry, opts.asset_type, seed, generator_version)
            family = self._registry.presentation(opts.presentation_id, presentation_version)
            presented = present_asset(self._registry, asset, family.versions)
        except ForgeError as exc:
            raise ForgeActionError("Generate failed", str(exc)) from exc
        return self._result(opts, presented, "generated")

    def _result(self, opts: AssetOptions, presented, source: str) -> AssetResult:
        asset = presented.asset
        entry = self._registry.asset(opts.asset_type)
        integrity = tuple(integrity_hashes(self._registry, presented).items())
        summary = tuple(line.strip() for line in entry.summary_lines(asset))
        return AssetResult(opts, asset.seed, asset.generator_version, asset, presented, integrity, summary, source)

    # ------------------------------------------------------------ preview

    def preview_settings(self, preview_version: int | None, view: str,
                         base: PreviewSettings | None = None) -> PreviewSettings:
        if preview_version is None:
            raise ForgeActionError("Choose a preview version", "No preview version is selected.")
        width, height, ssaa = (base.width, base.height, base.ssaa) if base else self._preview_size
        try:
            return PreviewSettings(preview_version, view, width, height, ssaa)
        except ForgeError as exc:
            raise ForgeActionError("Invalid preview settings", str(exc)) from exc

    def render(self, result: AssetResult, settings: PreviewSettings):
        try:
            return render_asset_preview(self._registry, result.presented, settings)
        except ForgeError as exc:
            raise ForgeActionError("Preview failed", str(exc)) from exc

    # ------------------------------------------------------------ persistence

    def save_record(self, result: AssetResult, path, preview_image=None) -> tuple[Path, str]:
        """Write a Step 2 asset record. Returns (path, record_content_sha256)."""
        try:
            record = build_record(result.presented, preview_image, registry=self._registry)
            written = save_record(record, path, registry=self._registry)
        except (ForgeError, OSError) as exc:
            raise ForgeActionError("Save failed", str(exc)) from exc
        return written, record["integrity"]["record_content_sha256"]

    def load_record(self, path) -> LoadedRecord:
        try:
            loaded = load_record(path, registry=self._registry)
        except RecordIntegrityError as exc:
            raise ForgeActionError("Record failed verification", str(exc)) from exc
        except (ForgeError, OSError) as exc:
            raise ForgeActionError("Could not load record", str(exc)) from exc
        opts = self.options(loaded.spec.asset_type)
        result = self._result(opts, loaded.presented, str(path))
        return LoadedRecord(result, Path(path), loaded.record_content_sha256, loaded.verified,
                            loaded.spec.preview, loaded.spec.expected_pixels_sha256)

    # ------------------------------------------------------------ export

    def export(self, result: AssetResult, export_key: str, path) -> tuple[Path, ...]:
        choice = result.options.exporter(export_key)
        if choice is None:
            raise ForgeActionError("Export not available",
                                   f"{export_key!r} is not offered for {result.asset_type}; "
                                   f"available: {[c.key for c in result.options.exporters]}")
        try:
            return export_asset(self._registry, result.asset, result.presented,
                                choice.format_id, choice.format_version, path)
        except (ForgeError, OSError) as exc:
            raise ForgeActionError("Export failed", str(exc)) from exc

    def save_preview(self, result: AssetResult, image, path, record_content_sha256: str | None = None) -> Path:
        try:
            return write_preview_png(image, path, result.presented, record_content_sha256)
        except (ForgeError, OSError) as exc:
            raise ForgeActionError("Save preview failed", str(exc)) from exc

    # ------------------------------------------------------------ details

    def details(self, result: AssetResult, *, export_key: str | None = None, image=None,
                record_path=None, record_content_sha256: str | None = None,
                preview_note: str | None = None, last_export=None) -> tuple[tuple[str, str], ...]:
        o, v = result.options, result.versions
        choice = o.exporter(export_key) if export_key else None
        rows = [
            ("Asset type", f"{o.asset_type} ({o.display_name})"),
            ("Seed", str(result.seed)),
            ("Generator", f"{o.generator_id} v{result.generator_version}"),
            ("Presentation", f"{o.presentation_id} v{v.presentation_version} (normals v{v.normals_version}, "
                             f"uv v{v.uv_version}, material v{v.material_version})"),
            ("Export format", choice.label if choice else "not selected"),
        ]
        if choice is not None and choice.contract is not None:
            rows.append(("Engine contract", choice.contract_label))
        if last_export is not None:                  # (export key, written paths) from this session
            key, written = last_export
            done = o.exporter(key)
            rows.append(("Last export", f"{key} → {written[0]}"))
            labels = done.extra_files if done else ()
            for label, path in zip(labels, written[1:]):
                rows.append((f"Last export · {label}", str(path)))
            if done is not None and done.contract is not None:
                rows.append(("Last export · status", f"validated against {done.contract_label} before writing"))
        rows.append(("Coordinate convention", o.convention_id))
        for key, value in result.integrity:          # exact record field names, registry order
            rows.append((key, value))
        rows.append(("record_content_sha256", record_content_sha256 or "not saved yet"))
        rows.append(("Record file", str(record_path) if record_path else "none"))
        if image is not None:
            s = image.settings
            rows.append(("Preview", f"{_view_label(s.view)} · {s.width}x{s.height} · ssaa {s.ssaa} · "
                                    f"{o.preview_id} v{s.preview_version}"))
            rows.append(("pixels_sha256", image.pixels_sha256 + (f" ({preview_note})" if preview_note else "")))
        rows.append(("Materials", ", ".join(f"{c.name}={c.material.preset}" for c in result.presented.components)))
        for i, line in enumerate(result.summary):
            rows.append(("Parameters" if i == 0 else "", line))
        return tuple(rows)
