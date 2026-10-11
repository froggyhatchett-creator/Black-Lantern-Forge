# Architecture: Explicit Versioned Registries (Step 2.5)

> Black Lantern Forge resolves asset generation, presentation, persistence,
> preview, and export behavior through explicit versioned registries while
> preserving the frozen short-sword outputs.

## Why registries exist

Before Step 2.5, the record loader and CLI *were* the short sword: they called
`generate_sword`, checked `asset_type == "short_sword"`, listed blade, guard,
grip and pommel, and defaulted to `LATEST_*` constants. A second asset family
would have meant editing every one of those places.

Now generic code asks the registry what to do. The short sword is one registered
asset type, and its frozen implementation is wrapped, not modified.

## Flow

```
             asset record (JSON)  ──or──  CLI: generate <asset_type> --generator-version V ...
                      │
                      ▼
        ┌──────────────────────────────┐
        │ record.py / cli.py (generic) │   no asset-family knowledge
        └──────────────┬───────────────┘
                       │ registry.asset(asset_type)             UnknownAssetTypeError (before any generation)
                       ▼
               AssetEntry ── descriptor: generator_id, presentation_id, export_formats,
                       │                 preview_id, record_versions, convention_id, components
                       │ registry.generator(generator_id, V)    UnknownGeneratorError / UnsupportedGeneratorVersionError
                       ▼
               frozen geometry  (forge.sword v1 → generate_sword(seed, 1))
                       │ registry.presentation(presentation_id, P)   UnknownPresentationError / UnsupportedVersionError
                       ▼                                             (pins normals/uv/material versions)
               presented asset  (forge.presentation v1 → derive_presentation)
                       │
        ┌──────────────┼───────────────────────────┬──────────────────────────────┐
        ▼              ▼                           ▼                              ▼
 registry.exporter   registry.preview         AssetEntry.integrity         record build / verify
 (format, version)   (preview_id, version)    (ordered hash functions)     (generic record v1 schema)
 obj:1  obj:2        forge.preview v1         geometry, obj_format1, ...
```

## The registries

There are five tables, built once in `forge/catalog.py` by
`forge.registry.build_registry`. Each one is a `MappingProxyType` inside a frozen
dataclass, so it's read-only after construction.

| Registry | Key | Value |
|---|---|---|
| assets | `asset_type` | `AssetEntry` = `AssetDescriptor` (routing data) + `integrity` hash functions + `summary_lines` |
| generators | `(generator_id, generator_version)` | `GeneratorEntry`: the exact generator callable |
| presentations | `(presentation_id, presentation_version)` | `PresentationEntry`: pinned normals/uv/material versions, compatible preview versions, `derive` |
| exporters | `(format_id, format_version)` | `ExportEntry`: extension, accepted presentations, `write` |
| previews | `(preview_id, preview_version)` | `PreviewEntry`: `render` |

`build_registry` refuses inconsistent tables with `RegistryConfigurationError`.
That covers duplicate keys, a descriptor pointing at an unregistered generator,
presentation, exporter, preview or convention, and duplicate or reserved
integrity keys.

### Registered identifiers (exact)

| Kind | Identifier | Versions | Implementation |
|---|---|---|---|
| asset type | `short_sword` | record v1 | `forge/assets/short_sword.py` |
| generator | `forge.sword` | 1 | `generate_sword(seed, 1)` (frozen Step 1) |
| presentation | `forge.presentation` | 1 → normals 1, uv 1, material 1; preview 1 | `derive_presentation` (frozen Step 2) |
| export | `obj` | 1 | `write_obj`: geometry only (frozen Step 1 bytes) |
| export | `obj` | 2 | `write_enriched_obj`: needs `forge.presentation` v1; writes `.obj` + `.mtl` |
| export | `glb` | 1 | Step 3: `forge.engine.package` via `catalog._write_glb_format1`. Needs `forge.presentation` v1. Writes a `.forgepkg` directory holding `asset.glb` + `manifest.json`. Declares `contract = ("forge.engine-contract", 1)`. |
| engine adapter | `short_sword` | (no version; it serves contract v1) | `ENGINE_ADAPTER` in `forge/assets/short_sword.py` (sockets, tags), listed in `catalog.ENGINE_ADAPTERS` |
| engine contract | `forge.engine-contract` | 1 | `forge/engine/contract.py`; see [FORGE_ENGINE_CONTRACT_V1.md](FORGE_ENGINE_CONTRACT_V1.md) |
| preview | `forge.preview` | 1 | `render_preview` (frozen Step 2) |
| convention | `forge.rh-y-up-meters.grip-origin.v1` | none (a changed convention gets a new id) | `forge/conventions.py` |
| record schema | `black-lantern-forge/asset-record` | 1 | `forge/record.py` (`_SCHEMAS`) |
| asset types (Step 5A) | `dagger`, `long_sword`, `curved_sword`, `great_sword` | record v1 | `forge/assets/blades.py` |
| generators (Step 5A) | `forge.dagger`, `forge.long_sword`, `forge.curved_sword`, `forge.great_sword` | 1 each | `forge/blades/<family>.py` |
| presentation (Step 5A) | `forge.blade-presentation` | 1 → normals 1, uv 1, material 1; preview 1 | `forge/blades/presentation.py` |
| preview (Step 5A) | `forge.preview.fit` | 1 | `forge/render/fit.py` (geometry-bound framing; frozen rasterizer) |
| engine adapters (Step 5A) | one per blade family | (serve contract v1) | `forge/assets/blades.py` |
| asset types (Step 5B) | `one_hand_axe`, `two_hand_axe`, `mace`, `war_hammer` | record v1 | `forge/assets/hafted.py` |
| generators (Step 5B) | `forge.one_hand_axe`, `forge.two_hand_axe`, `forge.mace`, `forge.war_hammer` | 1 each | `forge/hafted/<family>.py` |
| presentation (Step 5B) | `forge.hafted-presentation` | 1 → normals 1, uv 1, material 1; preview 1 | `forge/hafted/presentation.py` |
| preview (Step 5B) | `forge.preview.fit` (reused, unchanged) | 1 | `forge/render/fit.py` |
| engine adapters (Step 5B) | one per hafted family | (serve contract v1) | `forge/assets/hafted.py` |

These are the same identifiers Step 2 already persisted. **No record schema
change was needed**, so Step 2 records load unmodified.

### Asset descriptor

```python
AssetDescriptor(
    asset_type="short_sword",
    display_name="procedural short sword",
    generator_id="forge.sword",
    presentation_id="forge.presentation",
    export_formats=(("obj", 1), ("obj", 2)),
    preview_id="forge.preview",
    record_versions=(1,),
    convention_id="forge.rh-y-up-meters.grip-origin.v1",
    components=("blade", "guard", "grip", "pommel"),
)
```

It's pure routing data: strings and tuples only, hashable, with no callables,
no geometry and no state. The asset-specific *behavior* generic code needs lives
next to it in `AssetEntry`:

- `integrity`: the ordered hash functions
- `summary_lines`: the human-readable CLI summary

## Explicit version resolution (frozen rule)

- **Every lookup needs `(id, version)`.** Calling one without a version is a
  `TypeError`. A wrong type (`True`, `1.0`, `"1"`, `None`) or an unregistered
  version raises an error. Nothing upgrades or downgrades.
- **A presentation family version pins one implementation of each layer.**
  Presentation v1 means normals v1 + uv v1 + material v1, nothing else.
- **No "latest" anywhere in the registry layer.** Listings are sorted for
  messages only; dispatch never picks the highest version. A test registers a
  pretend `forge.sword` v2 and checks that v1 still resolves to v1.
- **Insertion order is irrelevant.** Lookups are keyed, listings are sorted,
  and integrity hashes follow the order the asset entry declares. A test
  rebuilds every table in reverse and gets identical behavior and hashes.

**CLI pinning.** The `sword` command is a pinned alias of
`generate short_sword`: generator 1, presentation 1, export `obj` at
`--obj-format` (default 1). It doesn't follow newer registrations; there's a
test for that too. The generic `generate` command has no version defaults:
`--generator-version` is required, and `--presentation-version` is required
whenever presentation is needed.

## Dispatch functions (`forge.registry`)

| Function | Resolves |
|---|---|
| `generate_asset(reg, asset_type, seed, generator_version)` | asset → generator → frozen generator. It validates the seed, checks the float environment, then checks the returned asset's identity. |
| `present_asset(reg, asset, versions)` | asset → presentation family; checks the pinned versions, then derives |
| `export_asset(reg, asset, presented, format_id, format_version, path)` | the asset must offer the format; checks presentation compatibility and extension, then writes |
| `render_asset_preview(reg, presented, settings)` | needs preview capability and a presentation that supports the preview version, then renders |
| `integrity_hashes(reg, presented)` | the asset entry's hash functions, in declared order |

Hash *meanings* are unchanged. Each hash function is the same Step 2 function,
registered under the same key.

## Adding a future asset family

This is how armor, for example, would be added:

1. **Generator.** Implement it, returning an asset object with `asset_type`,
   `generator`, `generator_version`, `seed`, `components` (`Mesh` tuple),
   `component_names` and `to_dict()`.
2. **Presentation adapter.** Implement one that returns the presentation data
   model.
3. **Registry entries.** Write an `AssetDescriptor`, `AssetEntry`,
   `GeneratorEntry` and `PresentationEntry` in `forge/assets/<family>.py`.
4. **Catalog.** Add them to the tuples in `forge/catalog.py`.
5. **Convention.** If the family needs a new coordinate convention, add it to
   `forge/conventions.py`.

No edits to `record.py`, `registry.py`, `hashing.py` or the CLI routing. The
test suite proves this with a **test-only** `test_tetra` family
(`tests/registry_fixtures.py`). It runs through generation, a record save/load
round trip, preview and the CLI against the unmodified generic code. It isn't
shipped, and the production catalog doesn't contain it.

## Remaining short-sword coupling

These live in frozen Step 1 / Step 2 modules, so Step 2.5 wraps them instead of
editing them:

- **OBJ format 1 exporter** (`export/obj.py`) only accepts a `SwordAsset`. A
  second family wanting `obj:1` would need that check widened to a mesh-asset
  protocol, keeping sword output byte-identical, or would need to register a
  different format identity.
- **Presentation v1** (`forge.presentation`) has normals, UV and material tables
  keyed by blade/guard/grip/pommel. A new family registers its own presentation
  entry; the test family does exactly that.
- **Presentation data model naming.** It's called `PresentedSword`, and its
  annotations say `SwordAsset`. Structurally it's generic, and the test family
  uses it, but the names are sword-specific.
- **Preview v1 camera framing** (fixed target and 0.84 m frame) is tuned to the
  v1 sword's size. Another family would likely want its own preview version.
- **The `sword` CLI command and the `--obj-format` flags** are kept for the
  Step 1 / Step 2 contract. `sword` is the one place the CLI names
  `short_sword`, and it does so as a pinned alias.

## Why this is not a plugin system

- No auto-discovery, directory scanning, entry points, `importlib`, `exec`,
  `eval` or network lookups. A source guard enforces this across the whole
  package.
- No import side effects. Asset modules define constants; `catalog.py` lists them.
- No runtime registration API. Registries are immutable after `build_registry`.
  Tests build *separate* registries by passing a `registry=` argument; nobody
  mutates the production one.
- No third-party code. Every entry ships in this repository.

## Error model

| Error | Raised for |
|---|---|
| `UnknownAssetTypeError` | an unknown `asset_type`. Also a `RecordFormatError`, for Step 2 compatibility. |
| `UnknownGeneratorError` | an unknown generator id, or one that doesn't produce the asset type. Also a `RecordFormatError`. |
| `UnsupportedGeneratorVersionError` | an unregistered generator version (existing Step 1 type) |
| `UnknownPresentationError` | an unknown presentation id |
| `UnsupportedVersionError` | an unregistered presentation, preview or record version, or a sub-version that doesn't match the family's pin |
| `UnknownExportFormatError` | an unknown export format, or one the asset doesn't offer |
| `UnsupportedExportVersionError` | a registered format at an unregistered version, or one the asset doesn't offer |
| `UnknownPreviewError` | an unknown preview renderer, or an asset with no preview capability |
| `RegistryConfigurationError` | inconsistent registry tables (a Forge bug) |

All dispatch errors except `RegistryConfigurationError` derive from
`RegistryError`, which is a `ForgeError` and a `ValueError`. The CLI maps them
to exit code 2.

## Step 3 addition: the engine contract exporter

Step 3 adds one exporter, `glb` 1, through the same registry, and changes no
routing rule.

**What changed in the registry layer** (all additive):

- `ExportEntry` gained an optional field, `contract: tuple[str, int] | None =
  None`. An exporter that declares a contract validates its output against it
  before writing.
- The short sword's descriptor now offers `("glb", 1)`. Its `export_formats`
  are listed sorted, like every registry listing.
- `catalog.py` lists `ENGINE_ADAPTERS` and `ASSET_ENTRIES` explicitly.

**Why the GUI and CLI never name GLB.** They see the format only as a registry
entry with a contract. The CLI imports `forge.engine.validate` for the generic
`validate-package` command only. Validation is defined by the contract, not by
the asset type.

## Step 5A addition: the first arsenal (blade families)

Step 5A put the "adding a family" recipe above to a real test. It added four production
families, and **no generic module changed**. Every file of records, registry, CLI, hashing,
exporters, engine contract, desktop and viewer is byte-identical to Step 4, and
`tests/test_arsenal_frozen.py` pins their hashes.

**What was added:**

- `forge/blades/`: shared geometry, the parameter model, the four generators, the blade
  presentation family and the bayonet-lineage schema
- `forge/assets/blades.py`: registry entries and engine adapters
- `forge/render/fit.py`: a new, generic preview renderer

**What changed in existing files:**

- `forge/catalog.py` lists the new entries, as data.
- The accept-lists of `obj:2` and `glb:1` now include `forge.blade-presentation` v1.

How the remaining coupling listed above was handled, without editing frozen code:

| Coupling | Step 5A handling |
|---|---|
| OBJ format 1 accepts only `SwordAsset` | blade families don't offer `obj:1`; they offer `obj:2` and `glb:1` |
| presentation v1 is sword-keyed | new family id `forge.blade-presentation`, which outputs the same `PresentedSword` container |
| preview v1 framing is sword-sized | new renderer id `forge.preview.fit`, which frames from the geometry. `PreviewSettings` stays at preview_version 1, so a new id fits the frozen schema. |
| `PresentedSword` naming | unchanged and reused; the name is historical |

See [ARSENAL_BLADES.md](ARSENAL_BLADES.md).

## Step 5B addition: hafted weapons

Step 5B repeated the recipe with a different construction: a haft with a head seated on it,
instead of a blade with a guard and grip. It added four production families, and **no generic
module changed**. The 57 generic sources pinned at Step 4 and the 13 Step 5A blade sources are
byte-identical; `tests/test_hafted_frozen.py` pins both sets.

**What was added:**

- `forge/hafted/`: shared haft, grip, butt-cap and head primitives, the parameter model with
  assembly joints and two-phase plausibility checks, the four generators, and the hafted
  presentation family
- `forge/assets/hafted.py`: registry entries and engine adapters

**What changed in existing files:**

- `forge/catalog.py` lists the new entries, as data.
- The accept-lists of `obj:2` and `glb:1` now include `forge.hafted-presentation` v1.
- The version is 0.6.0 (`forge/__init__.py`, `pyproject.toml`).

It reused, without edits, Step 5A's `sweep`, `Ring`, `compute_normals`, `compute_uvs` and
`forge.preview.fit` v1. Blade internals were not modified to make that possible.

| Coupling | Step 5B handling |
|---|---|
| Contract v1 requires `socket_tip` | for a hafted weapon, `socket_tip` is the distal end of the primary axis (the top of the head); `socket_head`, `socket_strike` and, for the war hammer, `socket_secondary_strike` are extra `socket_*` names Contract v1 already allows |
| socket rotations are identity in Forge's package builder | sockets are positions only, which is documented |
| `PresentedSword` naming, the OBJ 2 header comment, the convention field `blade_tip_axis` | unchanged and reused; the names are historical |
| `catalog.py` accept-lists name each presentation family | one line per list, as data |

See [HAFTED_WEAPONS.md](HAFTED_WEAPONS.md).

## Still deferred

- **Content:** spears, polearms, ranged and flexible weapons, armor, creatures.
- **Engines:** engine integration (importers, plugins, viewers), runtime
  sockets or physics.
- **Geometry and textures:** LOD1+, baked textures.
- **Platform:** plugins of any kind, networking and cloud registries.
- **Tools:** shader authoring, AI generation.
