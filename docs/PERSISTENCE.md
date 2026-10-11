# Asset Records, Versions, and Hashing (Step 2)

An asset record is a **recipe**, not a dump. It stores what's needed to
reproduce an asset, plus hashes of what reproduction must yield. It never
stores geometry: the frozen generator is the geometry authority.

Example: [`examples/asset_record_seed1337.json`](../examples/asset_record_seed1337.json).

## Usage

```bash
python -m forge sword --seed 1337 --save output/seed1337.json [--preview output/seed1337.png]
python -m forge load output/seed1337.json            # validate + regenerate + verify
python -m forge preview output/seed1337.json         # re-render + verify pixels
```

```python
from forge.record import build_record, save_record, load_record
save_record(build_record(presented, image_or_settings_or_None), "r.json")
loaded = load_record("r.json")   # .asset, .presented, .verified, .spec
```

## Schema (record_version 1)

Every key is required unless marked optional. Unknown keys are rejected at
every level.

| Key | Type / allowed values |
|---|---|
| `record_format` | `"black-lantern-forge/asset-record"` |
| `record_version` | `1` |
| `asset_type` | `"short_sword"` |
| `generator` | `"forge.sword"` |
| `generator_version` | `1` |
| `seed` | decimal **string**, `"0"` … `"18446744073709551615"` |
| `conventions` | exactly the `forge.rh-y-up-meters.grip-origin.v1` object (handedness, up axis, units, origin, blade tip axis, winding) |
| `presentation.presentation_version` | `1` |
| `presentation.normals_version` | `1` |
| `presentation.uv_version` | `1` |
| `presentation.material_version` | `1` |
| `presentation.materials` | `{blade, guard, grip, pommel}`: each the full material object (preset, base_color, metallic, roughness, pattern) |
| `preview` *(optional)* | `{preview_version, view, width, height, ssaa}` plus optional `pixels_sha256` |
| `integrity` *(optional)* | any subset of the hash keys below, each 64 lowercase hex characters |
| `info` *(optional)* | free-form object. **Non-authoritative:** ignored on load and excluded from every hash. Forge writes `forge_version` and a note. |

Version fields must be plain JSON integers: `true`, `1.0`, and `"1"` are all
rejected.

**No timestamps.** The frozen Step 1 tests forbid clock access anywhere in the
package. It's also useful: saving the same asset twice produces byte-identical
files.

## Reload procedure

1. **Parse** strict JSON. Duplicate keys, `NaN`/`Infinity`, non-UTF-8 input,
   files over 1 MB, and non-object top levels are rejected.
2. **Validate** structure: required and unknown keys, identity fields, seed,
   conventions, every version, preview settings, hash formats.
3. **Check content.** If `integrity.record_content_sha256` is present, the
   record content must hash to it. This catches any edit to the recipe.
4. **Regenerate** with `generate_sword(seed, generator_version)`, then
   `derive_presentation(asset, versions)`.
5. **Verify materials.** The regenerated materials must equal
   `presentation.materials` exactly: same keys, values, and JSON types. The
   error names the first differing path.
6. **Verify hashes.** Every hash present in `integrity` must equal its
   regenerated value.
7. **Verify preview** (in `preview` only). If `preview.pixels_sha256` is present
   and the settings aren't overridden, the re-rendered pixels must match.

| Error | Exit code | Meaning |
|---|---|---|
| `RecordFormatError` | 2 | malformed |
| `InvalidSeedError` | 2 | bad seed |
| `UnsupportedVersionError`, `UnsupportedGeneratorVersionError` | 2 | unknown version. **Never upgraded, never defaulted.** |
| `RecordIntegrityError` | 3 | parsed fine but doesn't reproduce |

A record without `integrity` (a hand-written recipe) still loads. Only the
material comparison runs.

## Hashes: exactly what each covers

All are SHA-256, lowercase hex. Binary encodings are little-endian with IEEE-754
binary64 floats, and each starts with an ASCII tag naming the encoding version.

| Hash | Covers |
|---|---|
| `geometry_sha256` | `"forge.geometry.v1\0"`, then per component in order: name + NUL, u32 vertex count, u32 triangle count, positions (3×f64), triangles (3×u32). Full precision frozen geometry. |
| `obj_format1_sha256` | The exact bytes of the Step 1 OBJ (obj_format 1). |
| `normals_sha256` | `"forge.normals.v1\0"`, then per component: name + NUL, u32 normal count, u32 triangle count, normals (3×f64), normal index triples (3×u32). |
| `uvs_sha256` | `"forge.uvs.v1\0"`, then per component: name + NUL, u32 uv count, u32 triangle count, uvs (2×f64), uv index triples (3×u32). |
| `materials_sha256` | Canonical JSON of `{component: material}`. |
| `record_content_sha256` | Canonical JSON of the whole record **minus** `info` and minus `integrity.record_content_sha256` itself. It includes `preview` and the other integrity hashes. |
| `preview.pixels_sha256` | `"forge.pixels.rgb8\0"`, u32 width, u32 height, RGB8 rows top to bottom. Pixels, not PNG bytes (see PREVIEW.md). |

**Canonical JSON:** `json.dumps(obj, sort_keys=True, separators=(",", ":"),
ensure_ascii=True, allow_nan=False)`. Floats serialize with `repr()`, the
shortest form that round-trips, so a parsed and re-serialized record hashes
identically. Key order, whitespace, and `info` don't affect the content hash.

**Saved file layout:** `json.dumps(record, indent=2, sort_keys=True,
ensure_ascii=True)` + newline, written as bytes.

## Compatibility guarantees

- **Frozen Step 1.** `generate_sword(seed, 1)` and obj_format 1 output are
  unchanged byte for byte. Seed 1337 OBJ SHA-256 was
  `7d9c4ad5…ffd08a` before Step 2 and is the same after; the Step 1 golden
  tests still pass unmodified. Default `python -m forge sword --seed N`
  behavior is unchanged.
- **Version pinning.** A record pins every version that shapes its output.
  Released versions are never edited. New behavior ships as a new number, and old
  numbers stay loadable, so a v1 record keeps reproducing.
- **No silent repair or upgrade.** Unknown keys, unknown versions, altered
  conventions, and mismatched hashes are refused, never fixed.
- **Enriched export is opt-in.** obj_format 2 has its own format number. Its `v`
  lines and position indices are identical to obj_format 1.
- **Not covered:** the `info` block, PNG file bytes across zlib builds, and
  platforms other than CPython on IEEE-754 binary64.

## Step 2.5: registry-driven loading

The record schema is unchanged: record_version 1, the same keys, the same
hashes. What changed is *how* it's loaded. Each asset-specific step now comes
from the registry:

- `asset_type` resolves to an asset entry (before any generation)
- the descriptor's `generator_id` and `generator_version` resolve to a generator
  entry
- `presentation_version` resolves to a presentation family, whose pinned
  normals/uv/material versions must match
- material keys come from the descriptor's `components`
- the coordinate convention comes from the descriptor's `convention_id`
- allowed integrity keys come from the asset entry's `integrity` list

Step 2 records, including `examples/asset_record_seed1337.json`, load without
modification. See [ARCHITECTURE.md](ARCHITECTURE.md).
