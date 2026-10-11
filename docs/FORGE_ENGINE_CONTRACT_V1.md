# Forge → Engine Asset Contract v1 (Step 3)

> Black Lantern Forge can deterministically export a supported asset as a GLTF 2.0
> binary package conforming to Forge → Engine Asset Contract v1 without changing
> frozen asset-generation behavior.

That claim covers less than it might sound like:

- **What it covers:** a **package format**, a **writer**, and an **independent
  validator**.
- **What it doesn't cover:**
  - No engine plugin. Nothing here has been imported into Unreal, Unity or Godot.
  - No runtime sockets, physics, or production LODs.
  - No production textures.

## 1. Purpose

The contract is the hand-off point between Forge and any game engine. Forge
promises a package that is:

- **Self-describing.** Asset identity, versions, coordinates, sockets, collision,
  LODs, materials and hashes are all in `manifest.json`.
- **Standard.** `asset.glb` is plain glTF 2.0: no extensions, no custom chunks.
- **Byte-stable.** The same inputs always give the same bytes, on every machine.
- **Checkable without Forge's generator.** `forge.engine.validate` checks a
  package from its bytes alone.

Everything engine-specific stays engine-side (§14).

## 2. Versioning

| Identifier | Value | Where it appears |
|---|---|---|
| Contract id | `forge.engine-contract` | `manifest.contract.id`, `asset.extras.forge_contract.id` |
| Contract name | `Forge -> Engine Asset Contract` | `manifest.contract.name` |
| Contract version | `1` | `manifest.contract.version`, `asset.extras.forge_contract.version` |
| Exporter | `glb` format `1` | export registry, `manifest.package.exporter`, `asset.extras.forge_exporter` |

- **Every version is explicit.** There is no implicit "latest". A manifest
  without `contract.version`, or with any value other than the integer `1`
  (`"1"`, `1.0`, `true`, `2`), is refused.
- **v1 is frozen.** A changed rule means contract v2. v1 packages keep
  validating under v1.
- **The exporter and the contract are versioned separately.** A future `glb:2`
  might still emit contract v1, for example once it bakes textures. Each
  exporter declares the contract it targets: `ExportEntry.contract =
  ("forge.engine-contract", 1)`.
- **The contract is a data table.** Its definition lives in
  `forge/engine/contract.py` (`CONTRACT_V1`), and this document is its prose form.

## 3. Package layout

```
short_sword_seed1337_v1.forgepkg/      ← a directory (no ZIP)
├── asset.glb                          ← binary glTF 2.0
└── manifest.json                      ← canonical JSON
```

- **Exact contents.** The directory holds exactly these two files. Anything else
  is refused by the validator, and by the writer if it's already there.
- **Naming.** The `.forgepkg` suffix is the exporter's naming convention. It's
  also the "extension" the export registry checks. The validator checks
  contents, not the directory name.
- **Paths are relative.** The manifest refers to the files by fixed relative
  names only, never by paths.

## 4. GLB (glTF 2.0 binary)

Written directly by `forge/engine/glb.py`: standard library only, no Blender, no DCC.

| Part | v1 rule |
|---|---|
| Header | magic `glTF` (0x46546C67), container version **2**, total length = file size |
| Chunk 0 | `JSON` (0x4E4F534A): canonical JSON (sorted keys, compact, ASCII), padded with spaces to 4 bytes |
| Chunk 1 | `BIN\0` (0x004E4942): one buffer, padded with zeros to 4 bytes |
| Other chunks | none (refused) |
| `asset` | `version` "2.0". `generator` "Black Lantern Forge glb exporter format 1" (no package version, no date). `extras` = identity. |
| Extensions | none. `extensionsUsed` / `extensionsRequired` are absent, and their presence is refused. |
| Buffer | exactly one, no `uri` (GLB-embedded) |
| bufferViews | one per accessor, 4-byte aligned, in order, no `byteStride`. `target` is 34962 for attributes and 34963 for indices. |
| Accessors | FLOAT for attributes. UNSIGNED_SHORT for indices when the vertex count is ≤ 65535, else UNSIGNED_INT. `POSITION` declares exact `min`/`max`. No sparse accessors. |
| Primitives | one per mesh. `mode` is 4 (triangles), stated explicitly, and every primitive is indexed. |
| Floats | binary32, rounded to nearest-even (`struct.pack`). JSON numbers are the shortest repr of the stored value. |

## 5. Coordinates, units, origin

| Property | v1 value |
|---|---|
| Handedness | right-handed |
| Up | +Y |
| Units | meters: `units: "meters"`, `meters_per_unit: 1` |
| Origin | `grip_center`: the center of the grip, on the weapon's centerline |
| Winding | counter-clockwise front faces, outward normals |
| Asset axes (short sword) | +Y blade toward tip · ±X cutting edges · ±Z blade flats |
| Conversion | **none**. This is glTF's native frame. Forge never converts to Z-up, left-handed or centimeters. |

- **The root node carries no transform.** Every position in the BIN chunk is
  already in the frame above.
- **The origin is enforced.** `socket_grip` must sit exactly at `[0, 0, 0]`.

## 6. Node hierarchy

| Index | Name | Role (`extras.forge_role`) | Contents |
|---|---|---|---|
| 0 | `short_sword` (the asset type) | `asset_root` | children 1–6, no mesh, no transform |
| 1–4 | `blade`, `guard`, `grip`, `pommel` | `render` | one mesh each, `forge_lod: 0` |
| 5 | `socket_grip` | `socket` | empty node: translation + rotation |
| 6 | `socket_tip` | `socket` | empty node: translation + rotation |
| 7 | `collision_hull` | `collision` | convex hull mesh |

| Scene | Name | Roots |
|---|---|---|
| 0 (default) | `forge_render` | `[0]`: everything a viewer should draw |
| 1 | `forge_collision` | `[7]`: collision only |

- **Node names are unique.** They are identifiers (`[A-Za-z][A-Za-z0-9_]*`).
- **Every node is in exactly one scene.**
- **Node matrices and scale are not used in v1.** Translation and rotation are
  allowed.

## 7. Render geometry

- **One mesh per frozen component.** Component order is the frozen order.
- **Corners are unwelded.** Forge's face-varying presentation (separate
  position, normal and UV indices) becomes unique `(position, normal, uv)`
  vertices, in first-seen (triangle, corner) order.
- **Triangles are untouched.** Count, order and winding are exactly the frozen
  mesh's. Positions are the frozen float64 values rounded to binary32.
  A triangle that collapses under rounding is refused; it never happens for
  generator v1 (2,250 seeds swept).
- **Attributes:** `POSITION`, `NORMAL` (unit length) and `TEXCOORD_0`. No
  others in v1.
- **`TEXCOORD_0 = (u, 1 − v)`** of Forge uv v1. glTF puts the UV origin at the
  image's top-left; Forge (like OBJ) puts it at the bottom-left.

## 8. Sockets

| Socket | Translation | Rotation | Derivation |
|---|---|---|---|
| `socket_grip` | `[0, 0, 0]` | identity `[0, 0, 0, 1]` | the asset origin, which the convention defines as the grip center. The exporter checks that the grip's bounding-box center is within 1e-9 m of the origin. |
| `socket_tip` | the blade apex, rounded to binary32 | identity | the unique blade vertex with the greatest y (the top point of the blade loft). It coincides exactly with the render apex vertex. |

- **Frame:** a socket's local axes are the asset axes. +Y points along the
  blade toward the tip, +X toward the cutting edges, +Z out of the blade flats.
- **Placement:** sockets are direct children of the root, with no mesh and no
  children.
- **Naming:** names start with `socket_`. Contract v1 requires `socket_grip`
  and `socket_tip`.
- **Manifest:** `sockets` lists every socket node, in node order, with its
  transform, frame and derivation. These must match the GLB exactly.
- **Derivation only reads.** Deriving sockets reads the frozen asset and
  changes nothing (`geometry_sha256` and OBJ hashes are checked before and
  after).

| Seed 1337 (golden) | translation |
|---|---|
| `socket_grip` | `[0.0, 0.0, 0.0]` |
| `socket_tip` | `[0.0, 0.60488361120224, 0.0]` |

## 9. Collision: `collision_hull`

**Representation: `convex_hull`.** It's built from every LOD0 render vertex
position, after binary32 rounding, as an exact convex hull (`forge/engine/hull.py`):

- **Exact arithmetic.** Coordinates become integers over a shared power-of-two
  denominator, and every orientation test is an exact integer determinant.
  There are no epsilons.
- **Algorithm.** It's an incremental hull. It is rebuilt once from its extreme
  points only, so its vertices are *exactly* the extreme points. A flat facet
  with more than three corners is still split into coplanar triangles.
- **Verified before it's written.** The hull must be closed and 2-manifold,
  with Euler characteristic 2. No face may be degenerate. Every input point
  must lie on or inside every face, which makes it convex, outward-facing and
  containing.
- **Canonical form.** Vertices are sorted by value. Each triangle is rotated so
  its smallest index comes first, keeping its winding. Triangles are sorted.
  `-0.0` is written as `0.0`.

**glTF representation.** Core glTF has no collision concept and no
universally supported visibility flag, so v1 marks collision by structure. That
keeps the hull clearly separate from render geometry:

- a mesh with `POSITION` and indices only (no normals, UVs or material),
  `mode` 4
- node `collision_hull`, `extras.forge_role: "collision"`
- the only root of the non-default scene 1, `forge_collision`. Viewers that
  show the default scene never draw it, and it isn't part of the render
  hierarchy.
- The collision scene's frame is the asset frame, because the asset root has
  no transform.

Seed 1337 golden: 49 vertices, 94 triangles,
`collision_sha256 = 4f0616a358c4c24bd4047425f3f838e4515c64a73b3599927088db2b2f93a9a2` (see
`examples/engine_package_seed1337.golden.json`).

## 10. Materials and textures

**Model:** `pbr_metallic_roughness`, one material per component, named
`forge_<component>`. All materials are `OPAQUE` and single-sided.

| glTF | Source (frozen material v1) |
|---|---|
| `baseColorFactor` | `base_color + [1.0]`, exact float64 values, no rounding or color conversion. Treated as linear, which is how glTF defines it. |
| `metallicFactor` | `metallic` (0.0 or 1.0) |
| `roughnessFactor` | `roughness` |
| `extras` | `forge_component`, `forge_preset`, `forge_procedural_pattern` (parameters), `forge_pattern_baked: false` |

**Supported vs populated channels.** This distinction is explicit in the
manifest, in `materials.channels`:

| Channel | Supported by contract v1 | Populated by glb:1 |
|---|---|---|
| base_color | ✓ (factor and/or texture) | **factor** |
| metallic_roughness | ✓ (factor and/or texture) | **factor** |
| normal | ✓ (texture) | absent |
| occlusion | ✓ (texture) | absent |
| emissive | ✓ (factor and/or texture) | absent |

**Texture rules (contract v1).** The validator enforces these, and a synthetic
textured package in the test suite exercises them:

- **Embedded PNG only.** Images are 8-bit RGB or RGBA, stored in a bufferView
  with no `target`, `mimeType: image/png`, no `uri`.
- **One UV set.** Every texture reference uses `texCoord` 0.
- **Every texture is declared.** `materials.textures[]` lists each one: channel,
  material, texture and image index, width, height, `pixel_format` (rgb8 or
  rgba8), `color_space` and `mime_type`.
- **Color space is fixed by channel.** `srgb` for base_color and emissive,
  `linear` for metallic_roughness, normal and occlusion.
- **Declarations must match the GLB.** The declared channel states and texture
  entries must match the GLB's actual texture references exactly.

**Why glb:1 writes no textures.**

- **No byte-stable encoder.** The procedural patterns need a PNG encoder whose
  bytes don't depend on the zlib build. Python's `zlib` output can differ
  between zlib and zlib-ng.
- **No fake texture data.** glb:1 ships no placeholder images.
- **Patterns travel as data.** Their parameters go along as data in `extras` and
  `manifest.materials.components[].procedural_pattern`. They are informational
  and not rendered by engines.
- **Baking is deferred.** It belongs in a future exporter version, at a
  documented resolution, up to 4K.

## 11. LOD

- **LOD0 only.** `manifest.lods = {count: 1, levels: [{level: 0, nodes: [...],
  vertices, triangles}]}`.
- **Tagged in the GLB.** Every render node carries `extras.forge_lod: 0`.
- **No reduced levels.** None are generated, and none are declared. A manifest
  that declares levels other than `[0]` is refused.
- **No LOD extension.** `MSFT_lod` is not used.

## 12. `manifest.json` schema

**Canonical bytes.** The file is
`json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False,
separators=(",", ": ")) + "\n"`: ASCII, with LF line endings. The validator
re-serializes the manifest and refuses any byte difference.

**Exact top-level sections:**

| Section | Fields |
|---|---|
| `contract` | `id`, `name`, `version` |
| `asset` | `asset_type`, `display_name`, `generator_id`, `generator_version`, `seed` (a decimal string, exact up to 2⁶⁴−1) |
| `presentation` | `presentation_id`, `presentation_version`, `normals_version`, `uv_version`, `material_version`, `texcoord_0` (note) |
| `coordinates` | `handedness`, `up_axis`, `units`, `meters_per_unit`, `origin`, `front_face_winding` (all required exactly), `convention_id`, `conversion`, plus convention extras (`blade_tip_axis`) |
| `package` | `layout` "directory", `glb`, `manifest`, `exporter` {`format_id`, `format_version`}, `root_node`, `render_scene`, `render_scene_index` |
| `sockets` | `[{name, node_index, parent, translation, rotation, frame, derivation}]`, in node order |
| `collision` | `node`, `node_index`, `representation`, `gltf_representation`, `derivation`, `scene`, `scene_index`, `vertices`, `triangles` |
| `lods` | `count`, `levels[]`, `note` |
| `materials` | `model`, `base_color_space`, `channels` {`supported`, `populated`}, `components[]` (component → node → material mapping with factors, preset, procedural pattern), `textures[]`, `procedural_patterns` (note) |
| `hashes` | name → {`sha256`, `covers`, `verifiable_from_package`} (§13) |
| `tags` | sorted, unique `key:value` strings, e.g. `category:weapon`, `blade.point:ogive`, `material.grip:black_leather` |

**Strict schema.** Unknown or missing fields are refused at every level.

**No environment data.** No timestamps, absolute paths, process ids, host or
user names, or UUIDs. The validator scans every key and string in both the
manifest and the glTF JSON for these. There's no Forge package version either,
so a release bump can't change package bytes; tests check that.

## 13. Hashing

All hashes are SHA-256, written as lowercase hex. Every entry states what it
covers in `covers`. The validator requires those texts to match the contract
word for word.

| Name | Covers | Verifiable from package |
|---|---|---|
| `glb_sha256` | every byte of `asset.glb` | ✓ |
| `gltf_json_sha256` | the JSON chunk data as stored (with padding) | ✓ |
| `gltf_bin_sha256` | the BIN chunk data as stored (with padding) | ✓ |
| `render_geometry_sha256` | semantic: tag `forge.engine.render-geometry.v1\0`, then per LOD0 node: name, material name, counts, POSITION/NORMAL/TEXCOORD_0 as f32, indices as u32. Independent of buffer layout and index width. | ✓ |
| `collision_sha256` | semantic: tag `forge.engine.collision.v1\0`, name, counts, POSITION f32, indices u32 | ✓ |
| `sockets_sha256` | canonical JSON of `[{name, parent, translation, rotation}]` | ✓ |
| `pbr_materials_sha256` | canonical JSON of the glTF `materials` array | ✓ |
| `semantic_sha256` | canonical JSON of {contract, coordinates, lods, and the four semantic digests}: "what the engine gets", independent of byte layout | ✓ |
| `manifest_content_sha256` | canonical JSON of the manifest with this one entry removed | ✓ |
| `source_*` | provenance: the Step 2 integrity hashes of the source asset (`geometry`, `obj_format1`, `normals`, `uvs`, `materials`). Reproducible with Forge, not from the package. | ✗ |

**Not in the manifest:** the SHA-256 of the manifest file itself (it can't
contain itself). The CLI, the GUI, and the golden record report it.

## 14. Validation

`forge/engine/validate.py`: `validate_package(dir)` and
`validate_package_bytes(glb, manifest)`.

**Independent.**

- **No shared code with the writer.** It doesn't import the writer
  (`glb.py`, `package.py`, `hull.py`) or `forge.hashing`.
- **Its own parsing and recomputation.** It has its own `struct` GLB parser,
  its own exact-integer hull check, and its own hash encoders.
- **Shared input: the contract table only.** That's `contract.py`.
- **It never runs the generator.**

**Fail closed.**

- **First violation stops it.** The first violation raises
  `EngineContractError`.
- **No repairs.** Nothing is repaired or defaulted.
- **No silent skips.** Unknown fields, extra chunks and extensions are
  refused, not skipped.

Check order (each name is reported when it passes):

```
manifest.json, manifest.contract, glb.header, glb.chunks, gltf.json, gltf.buffers,
gltf.buffer_views, gltf.accessors, gltf.materials, gltf.meshes, gltf.nodes, gltf.scenes,
manifest.canonical, manifest.schema, manifest.identity, manifest.coordinates,
manifest.package, contract.sockets, contract.collision, manifest.lods,
manifest.materials, manifest.tags, hygiene, hashes
```

What each stage checks:

- **Container.** Header: magic, version 2, exact length. Chunk structure and
  padding. Strict JSON: UTF-8, no BOM, no duplicate keys, no NaN.
- **Buffers and accessors.**
  - Buffer and bufferView bounds and alignment.
  - Accessor bounds, alignment and allowed types.
  - Finite floats, and exact `min`/`max`.
- **Meshes.**
  - The required attributes.
  - Unit normals.
  - Indices in range, never the restart value.
  - No repeated-index or zero-area triangles (exact).
  - Triangle mode.
  - Material references.
- **Nodes and scenes.** A tree with no cycles, every node in exactly one scene,
  unique names.
- **Contract rules.**
  - Required sockets, with the grip socket exactly at the origin.
  - `collision_hull`: separate scene, no material, closed, Euler 2, extreme
    points only, convex, outward, containing every render vertex (exact).
  - LOD0 counts.
  - Material mapping and factors.
  - Texture declarations.
  - Identity in `asset.extras` matches the manifest.
  - Coordinates and units.
  - Identifier formats.
- **Hygiene.** No timestamps, paths, PIDs or UUIDs.
- **Hashes.** Every package-verifiable hash.

**At write time.** The writer runs the same validator on the in-memory bytes
*before* writing anything. A package Forge would refuse is never written.

**Reproduction.** `python -m forge validate-package PKG --reproduce` regenerates
the asset from the manifest's identity through the registry. It requires
byte-identical `asset.glb` and `manifest.json`. This step uses the generator by
design. Plain validation does not.

**External checks (supplementary only, never a dependency).** These ran during
development and are not part of the test suite:

- **Khronos glTF-Validator** 2.0.0-dev.3.10 (npm `gltf-validator`): **0
  errors, 0 warnings** across 16 seeds. It reports 4 infos, `UNUSED_OBJECT` on
  `TEXCOORD_0`, because no texture uses the UVs yet.
- **trimesh** 5.1.1 loads it. The default-scene graph holds the 4 render nodes
  only. `collision_hull` is watertight with positive volume.

## 15. Determinism

- **Byte-identical output** for the same (asset type, seed, generator,
  presentation, exporter, contract) across:
  - Python 3.10–3.13
  - Tk/no-Tk interpreters
  - `PYTHONHASHSEED` values
  - processes
  - output directories
- **What makes it deterministic:**
  - IEEE binary32 rounding via `struct`
  - canonical JSON
  - explicit ordering everywhere (components, nodes, accessors, sockets by
    name, sorted tags, canonical hull)
  - exact integer geometry
  - no environment data in either file
- **Tests:** 3, 3b, 39–42, golden fixture, CLI subprocess.

## 16. Engine-side responsibilities (documented, not implemented)

These are the importer's job. Forge doesn't do any of them:

- **Frame conversion.** For Unreal, see the note below. Unity is left-handed, Y-up,
  meters; its glTF importers convert handedness.
- **Collision.** Read scene 1 / node `collision_hull` and cook it as a convex
  collider. It must not be imported as visible geometry.
- **Sockets.** Map `socket_*` empty nodes to engine sockets or attach points.
- **Materials.** Map the PBR factors to engine materials.
  `forge_procedural_pattern` is informational; recreating it in a shader is
  optional and engine-specific.
- **LODs and import settings.** Generate LOD1+ if wanted. Set up streaming,
  physics materials and import settings.
- **Verify first.** Check `glb_sha256` and `semantic_sha256`, or run the
  validator, before ingestion.

**Unreal note:** Unreal is left-handed, Z-up, in centimeters. An ingestion step
must apply the axis change and ×100 scale. The details depend on the importer
(Interchange / glTF importer settings). Forge applies **no** such conversion,
and nothing in this step has been verified inside Unreal. "Unreal-ready" is not
claimed.

## 17. Minimal package example (seed 1337, golden)

```
examples/short_sword_seed1337_v1.forgepkg/
  asset.glb      21640 bytes  sha256 b91900f7a1fc95f3ec6678e3dc8fa875b91bcce115c3231bd14dc5d0e2828bc3
  manifest.json  10488 bytes  sha256 4a4d552e82a2ff2caf9c55420488005240ece4879db1d191ec725a2acffc7aaf
```

```bash
python -m forge generate short_sword --seed 1337 --generator-version 1 \
    --presentation-version 1 --export glb:1            # → output/short_sword_seed1337_v1.forgepkg/
python -m forge export examples/asset_record_seed1337.json --format glb:1 --out pkg.forgepkg
python -m forge validate-package pkg.forgepkg --reproduce
```

`--presentation-version` is required. glb:1 needs presentation data, and the
`generate` command never picks a version for you.

Abridged `manifest.json`:

```json
{
  "asset": {"asset_type": "short_sword", "display_name": "procedural short sword",
            "generator_id": "forge.sword", "generator_version": 1, "seed": "1337"},
  "collision": {"node": "collision_hull", "node_index": 7, "representation": "convex_hull",
                "scene": "forge_collision", "scene_index": 1, "triangles": 94, "vertices": 49, "...": "..."},
  "contract": {"id": "forge.engine-contract", "name": "Forge -> Engine Asset Contract", "version": 1},
  "coordinates": {"handedness": "right", "up_axis": "+Y", "units": "meters", "meters_per_unit": 1,
                  "origin": "grip_center", "front_face_winding": "counter_clockwise", "...": "..."},
  "hashes": {"glb_sha256": {"covers": "every byte of asset.glb", "sha256": "b919…8bc3",
                            "verifiable_from_package": true}, "...": "..."},
  "lods": {"count": 1, "levels": [{"level": 0, "nodes": ["blade", "guard", "grip", "pommel"],
                                    "triangles": 280, "vertices": 379}], "note": "..."},
  "materials": {"model": "pbr_metallic_roughness",
                "channels": {"populated": {"base_color": "factor", "metallic_roughness": "factor",
                                           "normal": "absent", "occlusion": "absent", "emissive": "absent"},
                             "supported": ["base_color", "metallic_roughness", "normal", "occlusion", "emissive"]},
                "components": ["..."], "textures": [], "...": "..."},
  "package": {"layout": "directory", "glb": "asset.glb", "manifest": "manifest.json",
              "exporter": {"format_id": "glb", "format_version": 1}, "root_node": "short_sword", "...": "..."},
  "presentation": {"presentation_id": "forge.presentation", "presentation_version": 1, "...": "..."},
  "sockets": [{"name": "socket_grip", "translation": [0.0, 0.0, 0.0], "rotation": [0.0, 0.0, 0.0, 1.0], "...": "..."},
              {"name": "socket_tip", "translation": [0.0, 0.60488361120224, 0.0], "...": "..."}],
  "tags": ["asset_type:short_sword", "blade.point:ogive", "category:weapon", "..."]
}
```

## 18. Deferred

- **Textures:** baked textures (base color from the procedural patterns,
  normal, AO), a byte-stable PNG encoder, 4K output.
- **Geometry:** LOD1+ generation, convex decomposition (multi-hull) collision.
- **Sockets:** profiles for other asset families (armor, creatures, buildings).
  Contract v1 is defined for the handheld-weapon family it ships with.
- **Packaging:** ZIP packaging, KTX2/Basis, Draco/meshopt compression.
- **Engine side:** importers, plugins or viewers for Unreal, Unity or Godot.
  Runtime sockets or physics.
- **Not planned for any contract:** animation, rigging, skins, morph targets.
