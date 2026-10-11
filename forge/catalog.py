"""The registry catalog: every registered entry, listed explicitly.

This is the one place that knows which asset families, generators,
presentation pipelines, exporters, and preview renderers exist. Adding a family
means implementing its entries and adding them here. Generic code (record.py,
cli.py, registry.py) doesn't change.

REGISTRY is built once, at import, from these literal tuples, and is read-only.

Step 3 adds one exporter, glb format 1: a Forge -> Engine contract v1 package
(asset.glb + manifest.json in a .forgepkg directory). ENGINE_ADAPTERS lists,
explicitly, which asset types can be mapped onto the contract.

Step 5A adds:
  * four blade families (forge/assets/blades.py): dagger, long_sword, curved_sword, great_sword
  * their presentation family, forge.blade-presentation v1
  * the geometry-bound preview renderer, forge.preview.fit v1
The generic exporters obj:2 and glb:1 now also accept forge.blade-presentation v1. short_sword
stays first in ASSETS and keeps every entry it had.

Step 5B adds:
  * four hafted families (forge/assets/hafted.py): one_hand_axe, two_hand_axe, mace, war_hammer
  * their presentation family, forge.hafted-presentation v1
obj:2 and glb:1 also accept forge.hafted-presentation v1. They use the existing forge.preview.fit v1.
The Step 5A entries come next in ASSETS, unchanged.
"""

from __future__ import annotations

from types import MappingProxyType

from forge.assets import blades, hafted, short_sword
from forge.engine.contract import CONTRACT_ID, contract_spec
from forge.engine.package import build_engine_package, write_engine_package
from forge.errors import ExportError
from forge.export.obj import write_obj
from forge.export.obj_enriched import write_enriched_obj
from forge.registry import ExportEntry, PreviewEntry, build_registry
from forge.render import render_preview
from forge.render.fit import FIT_PREVIEW_ID, render_fit_preview


def _write_obj_format1(asset, presented, path):
    return (write_obj(asset, path),)


def _write_obj_format2(asset, presented, path):
    return write_enriched_obj(presented, path)


GLB_FORMAT1_CONTRACT_VERSION = 1


def _write_glb_format1(asset, presented, path):
    """Forge -> Engine contract v1 package. Validated before any file is written."""
    adapter = ENGINE_ADAPTERS.get(asset.asset_type)
    entry = ASSET_ENTRIES.get(asset.asset_type)
    if adapter is None or entry is None:
        raise ExportError(f"asset_type {asset.asset_type!r} has no engine contract adapter")
    spec = contract_spec(GLB_FORMAT1_CONTRACT_VERSION)
    package = build_engine_package(
        asset, presented, entry.descriptor, adapter,
        source_hashes=tuple((key, fn(asset, presented)) for key, fn in entry.integrity),
        exporter=("glb", 1), contract_version=spec.version)
    return write_engine_package(package, path, spec)


EXPORTERS = (
    ExportEntry(format_id="obj", format_version=1, extension=".obj", presentations=(),
                extra_file_labels=(), write=_write_obj_format1),
    ExportEntry(format_id="obj", format_version=2, extension=".obj",
                presentations=(("forge.presentation", 1), ("forge.blade-presentation", 1),
                               ("forge.hafted-presentation", 1)),
                extra_file_labels=("materials",), write=_write_obj_format2),
    ExportEntry(format_id="glb", format_version=1, extension=".forgepkg",
                presentations=(("forge.presentation", 1), ("forge.blade-presentation", 1),
                               ("forge.hafted-presentation", 1)),
                extra_file_labels=("manifest",), write=_write_glb_format1,
                contract=(CONTRACT_ID, GLB_FORMAT1_CONTRACT_VERSION)),
)

PREVIEWS = (
    PreviewEntry(preview_id="forge.preview", preview_version=1, render=render_preview),
    PreviewEntry(preview_id=FIT_PREVIEW_ID, preview_version=1, render=render_fit_preview),
)

ASSETS = (short_sword.ASSET,) + blades.ASSETS + hafted.ASSETS
GENERATORS = short_sword.GENERATORS + blades.GENERATORS + hafted.GENERATORS
PRESENTATIONS = short_sword.PRESENTATIONS + blades.PRESENTATIONS + hafted.PRESENTATIONS
ASSET_ENTRIES = MappingProxyType({entry.descriptor.asset_type: entry for entry in ASSETS})
ENGINE_ADAPTERS = MappingProxyType({
    adapter.asset_type: adapter
    for adapter in (short_sword.ENGINE_ADAPTER,) + blades.ENGINE_ADAPTERS + hafted.ENGINE_ADAPTERS
})

REGISTRY = build_registry(
    assets=ASSETS,
    generators=GENERATORS,
    presentations=PRESENTATIONS,
    exporters=EXPORTERS,
    previews=PREVIEWS,
)
