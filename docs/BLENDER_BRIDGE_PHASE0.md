# Blender Bridge Phase 0: assessment, isolated proof and results (stopped for review)

## Recommendation: GO for an optional, out-of-process job tool; NO-GO for expecting Blender to separate parts by itself

Blender 5.2.2 now runs here, isolated in the experiment's own venv (approved install; `bpy` from PyPI, size and
sha256 verified).

**All seven success criteria are met:**
- headless invocation;
- the real Rodin GLB imported;
- useful mesh information extracted;
- geometry and scale preserved exactly on round trip;
- two processing operations demonstrated;
- every output independently verified by Forge-side code;
- production untouched.

**What Blender gave this experiment**
- **Exact glTF I/O.** All 500,000 triangles round-trip bit-identical in position and UV.
- **Correct, topology-preserving decimation**, but only after an explicit weld.
- **The idea that separated the board: UV islands.** Rodin's own UV charts follow the parts, and Blender exposes
  them through its standard "Select Linked, delimit UV".

**What it did not give:** a capability Forge couldn't reproduce. The same UV-island selection reimplemented in numpy
selects the *identical* 89,796 triangles. Blender's real long-term value is its tool library (remesh, UV unwrap,
bake, weight transfer) and its artist UI, not part separation.

**Conditions**
1. Blender stays a separate process exchanging files; Forge never imports `bpy` (GPL).
2. It is never bundled; the user installs it.
3. Every job's output is judged by Forge-side verification, never by Blender's own report. This phase showed why:
   a decimated mesh that **passed the GLB validator was cracked into 4,240 pieces** (below).

Experiment: `experiments/blender_bridge/` (README; dependencies and licences in `DEPENDENCIES.md`). Pre-install
assessment sections follow the results.

## Phase 0 results (Blender 5.2.2, 2026-10-17)

All jobs ran through `bridge.py` with launcher `bpy`. Each had its own sandbox directory, a checksum-verified
read-only input copy and a log. The source GLB's sha256 was unchanged after every job (`2f359f01…6e41f`).

### Timings and memory (4 CPUs)

| Job | Wall time | Blender op | Peak RSS | Output |
|---|---|---|---|---|
| Version probe | 0.76 s | — | — | `5.2.2` |
| Inspect | 5.1 s | import 2.3 s | 896 MB | report |
| Round trip | 6.4 s | — | 887 MB | 22.2 MB GLB |
| Simplify 10 % (welded) | 15.3 s | weld + decimate 7.9 s | 1,338 MB | 1.35 MB GLB |
| Board, slab v0 | 8.9 s | 1.8 s | 998 MB | 1.31 MB GLB |
| Board, UV islands v2 | 14.4 s | ~7.8 s (island labelling in Python inside Blender) | 1,100 MB | 2.11 MB GLB |

### 1-3. Import, unchanged round trip, validation (`results/roundtrip_vs_source.jpg`)

**Import (Blender's view)**
- 1 mesh object `model`, identity transform, 504,919 vertices, 500,000 triangles.
- 1 UV layer and material `model` (base colour 0.5 grey, metallic 0.05, roughness 0.4, no images).
- No armature, shape keys or vertex groups.

**Round trip vs source** (`verify.py`, Forge's reader, node transforms applied)

| Check | Result |
|---|---|
| Forge validator | 0 errors, 0 warnings |
| Triangles | 500,000 / 500,000, **every one matched exactly by position** (1 µm) |
| Bounding box | identical (0.000 mm) |
| Transform, scale, axes | identity node; Blender's Z-up conversion undone exactly |
| UVs | identical per corner (max difference 0.0) |
| Normals | re-encoded: 99th percentile 0.03°, max 0.17° |
| Material | name, base colour, metallic, roughness, double-sided: identical |
| Vertices | 505,450 vs 504,919 (+531 splits: an exporter re-indexing, not a geometry change) |
| Renders | max pixel difference 10/255; at most 2 pixels above 8 |

**Topology gotcha.** On import Blender shows **409,580 open edges**: glTF stores UV-seam vertices split, and the
importer keeps them split. The importer's own `merge_vertices` option barely helps (504,919 -> 487,197 vertices,
still 383,648 open edges). An explicit weld (`remove_doubles`, 1 µm) gives exactly Forge's count: **249,818
vertices, 0 open edges**.

### 4. Non-destructive processing: Decimate to 10 % (`results/simplify_10pct_vs_source.jpg`)

**First run: cracked.** Decimating the seam-split import exported a file the GLB validator accepts, but on welded
geometry it has **63,832 open edges in 4,240 pieces**: each side of every UV seam collapsed independently.
- `verify.py` did not catch this at first.
- It now fails any job that adds open edges.
- That run is recorded as failed.

**Fixed run (weld first)**
- 50,000 triangles (ratio 0.100), 24,818 vertices.
- **0 open edges, 1 piece.** The Euler characteristic is still -182 (genus 92): topology preserved.
- Bounding box within 0.6 mm; UVs kept; verifier passes.
- Deviation to the nearest source vertex (an upper bound on surface distance): median 1.5 mm, p99 4.5 mm,
  max 6.7 mm.
- Silhouette preserved. Fine facial detail is lost at this ratio, as expected.

### 5. Hoverboard selection

| Method | Where | Result |
|---|---|---|
| Separate by Loose Parts (welded) | Blender | **1 part.** Useless |
| Sharp-edge islands (30°) | Blender | One island holds **94 % of the mesh.** Useless (the same leak as Forge's crease growth) |
| Crease-bounded growth | Python | Leaks into pants, belt and chest at 25° and 45° (pre-install evidence) |
| Slab v0 (one oriented box) | Blender **and** numpy | Identical triangle sets (54,228). Includes thigh and pouch shreds, **misses** the front rails and lower turbine; 1,728 open edges in 11 loops (`board_extracted_slab_v0.jpg`) |
| **UV islands v2** (one generous box votes whole UV islands at >= 60 %; 6 exclude picks: two pant legs, glove cuff, wrist band, crotch fold, forearm sleeve; 2 include picks: lower turbine housing) | Blender **and** numpy | **Identical triangle sets (89,796)**; 68 of 460 islands; every vertex within 0.0009 mm of the source. A coherent board from the front: plate, both turbines, rails, handles, strap; hand, glove and pants excluded. 1,528 open edges in 13 loops (`board_extracted_uv_islands_v2.jpg`, `board_selection_uv_islands_v2.jpg`) |

**Remaining defects in v2 (needs an operator or artist)**
- Open holes on the back of the lower board, where Rodin fused it to the thigh and body. That surface was never
  generated.
- A few small detached fragments.
- One horizontal tube near the grip: either the board's handle or part of her forearm. Geometry alone can't settle
  it; check against the artwork.
- No capping, re-UV or texture (the source has none).

### 6. Did Blender improve on the Python-only methods?

**For this asset, the improvement came from a better signal (UV islands), not from Blender.**
- Blender surfaced that signal in minutes through a standard selection tool, and running the probe inside Blender is
  how it was found.
- Forge's numpy port selects exactly the same faces, so Forge does not need Blender to do it.
- The operator picks (8 points) are the real work. In Blender they would be clicks in the viewport, and that
  interactive UI is where Blender beats anything Forge has today.
- Where Blender clearly adds value: exact, robust glTF I/O; a decimation that, once welded, matches Forge's own
  topology analysis; and the tool library for the next steps (hole capping, UV unwrapping, baking, weight transfer).

## Limitations

**Of the asset**
- Hidden surfaces under the hands and against the thigh do not exist.
- No textures.
- Island ids are only meaningful for this checksum, so the picks are stored as surface points.

**Of the bridge**
- Confinement is by convention plus checks, not an OS sandbox.
- Only `bpy` 5.2.2 on Linux has run. The Windows runner and the Blender-application launcher are unexecuted.

**Of the jobs**
- UV-island labelling inside Blender is plain Python (~8 s); acceptable here, slow for very large meshes.
- Decimation deviation is measured vertex-to-vertex (an upper bound), not point-to-surface.

**Not attempted, as instructed:** retopology, rigging, clothing reconstruction, character conversion, capping or
texturing the board.

## Pre-install assessment

### 0A: Environment and architecture

### Environment (this container)

**Blender availability**
- **Blender is not installed.** There is no binary, no `bpy` module, and no apt candidate.
- `download.blender.org` is **blocked** by the network policy.

**Smallest install: `bpy` 5.2.2 from PyPI**
- Blender 5.2.2 as a Python module, released 2026-09-15.
- Wheel sizes: **401.7 MB** (Linux x86-64), 338 MB (Windows x64).
- Requires exactly Python 3.13 (this container has 3.13.16).
- Pulls in numpy, cython, cattrs, requests and zstandard.
- It would go in an isolated venv inside the experiment, never in Forge's environment.
- **Not installed: awaiting approval**, per the brief.

**Resources:** 4 CPUs, 15 GB RAM, about 29 GB free disk. Enough.

**Headless invocation:** `bpy` is headless by design. The Blender application runs headless with
`--background --factory-startup --python`. Both launchers are implemented; neither has been executed.

### Forge architecture (what the bridge must respect)

| Area | Finding |
|---|---|
| GLB contracts | `forge_character_forge/gltf.py` writes only Forge characters (profiles `public` / `developer`, `asset.extras.forge` metadata). `validate.py`'s `read_glb` is a generic GLB 2.0 reader. `validate_glb` checks structure generically, plus Forge rules when `extras.forge` is present. External GLBs validate as "no Forge profile" |
| GLB import | No import path in Forge or the Studio. The Studio only exports. Readers exist only in tools and experiments |
| Geometry tools | `lod.py` (QEM decimation on arbitrary triangle meshes), `mesher.py` (surface nets + manifold checks), `sdf.py`, `kit.py` (non-character assets, "no Blender/Unreal dependency"). Nothing for segmentation, UVs, baking or weight transfer |
| Jobs and services | No job system. `studio_server.py` is a localhost HTTP server with one locked export endpoint |
| Desktop | `forge_desktop/` Tk app; the Studio is a static web app. "Black Lantern OS" appears only as a non-goal |
| **Existing Blender stub** | `forge_character_studio/blender_bridge/`: a fail-closed version pin (`PINNED_BLENDER_VERSION = "4.2.0"`, a placeholder) and a deterministic script generator for the Step 6C base-mesh design. It never invokes Blender. **Not modified.** The experiment follows its fail-closed pinning philosophy, but uses its own pin (5.2.2) and a file-based job contract |
| Dependencies and policy | `pyproject.toml` has `dependencies = []` (stdlib only by intent). v3 asset provenance states "no GPL code". The repository has **no LICENSE file** |

### Licensing

**Blender and the `bpy` wheel are GPL-3.0.** The wheel ships 300+ third-party components, per its metadata.

| Use | Obligation |
|---|---|
| **Running Blender as a separate program on files** (this design) | None for Forge. Program outputs, such as GLBs, are not GPL |
| **Importing `bpy` inside Forge's own process** | Would make that program a GPL-covered combination. **Forbidden by this architecture** |
| **Job scripts that import `bpy` (`job_blender.py`)** | The Blender Foundation treats distributed scripts as GPL-covered. They stay a separate component that Forge never imports. If Forge ever ships them, licensing them GPL-3.0-or-later is **your decision** |
| **Redistributing Blender or `bpy`** with Forge (an installer) | Brings GPL source-offer duties. **Recommendation: never bundle;** use the user's own install |

This is not legal advice.

### Safest architecture

```
Forge (owns DNA, contracts, projects, editing)                Blender (optional, user-installed, pinned)
  bridge.py: job.json --(checksum, sandbox dir, timeout)-->  job_blender.py: one operation, files only
  verify.py: <-- output/*.glb + report.json ---------------  (never sees anything but its job directory)
  Forge validator + numpy reference decide success
```

- **One process per job**, no daemon, no network, no agent.
- **Explicit files:** an input (checksum-checked, copied read-only) and an output directory.
- **Pinned version**, recorded in every result.
- **Forge-side verification** decides success; Blender's own report is not trusted.

## 0B: Isolated proof

### Built and tested here (no Blender needed)

**`bridge.py` (stdlib runner).** For each run it:
- checks the version pin, failing closed;
- verifies the source checksum before anything runs;
- creates a fresh, uniquely named job directory;
- copies the input in read-only, applies a timeout and writes a log;
- detects files written outside `output/`;
- hashes the outputs and writes `result.json`, including peak memory on Linux/macOS.

**`verify.py` (Forge-side checks).** It covers:
- the validator;
- node transforms applied (scale and axes);
- for extraction, a numpy reference with the exact expected face count, and every output vertex required to come
  from the source within 0.01 mm;
- for simplification, the surface deviation;
- the GLB inspection itself.

**`test_bridge.py`: 7 tests, OK.**
- They found and fixed two runner bugs: a job-directory name collision within one second, and numpy booleans in
  JSON.
- The verifier self-test rejects a moved vertex (1 mm), a 1 % rescale and missing faces.

**Found in passing (production, not changed):** Forge's validator raises `KeyError` on a GLB mesh with no `name`
instead of reporting an error (`validate.py`, the "missing material" message). External tools can produce such
files.

### Prepared before the install (since executed: see Phase 0 results)

**`job_blender.py`**
- `inspect`: objects, transforms, counts, UVs, materials, images, armatures, shape keys, boundary and non-manifold
  edges.
- `simplify`: Decimate (collapse) per mesh, then export.
- `extract_region`: faces inside operator boxes copied to a new object; source unchanged; UV-seam duplicates welded
  on import so connectivity follows the surface; cut boundaries left open and reported.

**`jobspecs/`** holds three Rodin jobs:
- inspect;
- simplify to 10 %;
- extract the v0 board slab.

`run_on_windows.ps1` runs all three plus verification and zips the results. It uses either your installed Blender
(`-BlenderExe`) or an opt-in `bpy` venv (`-InstallBpy`), and downloads nothing otherwise.

### The board: can it be isolated? (measured on the mesh, Forge-side)

**Not automatically.** The Rodin export is one watertight shell (genus 92).

| Approach | Result | Evidence |
|---|---|---|
| Separate by Loose Parts | Impossible: 1 connected component | `rodin_reference/results/inspection.json` |
| Board-aligned slab (oriented box) | Captures the back plate **and the thigh and pouch behind it**, misses the front rails. Inside the box: 14 pieces, the largest 54,228 triangles, 11 open cut loops | `results/board_selection_slab_v0.jpg`, `jobspecs/extract_board_slab_v0.numpy_reference.json` |
| Crease-bounded region growing from a board seed | **Leaks** into the pants, belt and chest even at a 25° crease threshold (142,656 faces). Leak entries are spread over ~10 contact zones | `results/board_crease_growth_25deg.jpg`, `_45deg.jpg` |

**Why it fails**
- The ~6 mm remesh smoothed every contact into the surface.
- The lower two-thirds of the board share depth with the thigh, hand and pouches.
- The surfaces under her fingers and against her thigh **were never generated**. Any cut leaves holes that need
  capping or rebuilding.

**Repeatable operator-assisted workflow (proposed, unexecuted)**
1. An operator marks the board with a few oriented volumes in a preview. The probes here already render selections
   from 4 views.
2. The volumes are saved as a versioned job spec.
3. Blender `extract_region` copies the faces to a new object; the source is untouched.
4. `verify.py` checks the result: exact face set, nothing invented or moved, cut loops listed.
5. A separate, explicitly destructive job caps the holes (fill or voxel remesh, acceptable for a rigid prop) and
   re-UVs.
6. An artist checks the result.

Because steps 1-4 are deterministic given the spec, the workflow is reproducible. The v0 slab spec is **known
incorrect** and exists only to exercise the pipeline.

## 0C: Character Forge compatibility

| Need | A. Blender has it | B. Reliably automatable | C. Needs an artist | D. Needs new Forge algorithms |
|---|---|---|---|---|
| Retopology of external characters | QuadriFlow / Voxel remesh, Shrinkwrap, manual retopology tools | Props and rigid pieces (voxel + decimate) | Characters: edge flow for deformation | Fitting to Forge's fixed v3 topology (reference fitting; probe in `rodin_reference`) |
| Mesh repair and simplification | Merge by distance, Decimate, fill/grid fill, remesh | Yes, for geometric cleanup | Semantic fixes | Forge already has QEM (`lod.py`) |
| Reconstructing missing surfaces | Fill, grid fill, voxel remesh, sculpting | Hole capping only | Plausible hidden surfaces (under hands, against bodies) | Semantic completion |
| Clothing and equipment preparation | Separate selection, solidify, cloth tools | Extraction once the selection exists | **Deciding the selection** (shown above), garment shells | Operator-volume spec and preview in Forge |
| UVs and materials | Smart UV Project, packing, Cycles baking (selected-to-active), glTF materials | UV unwrap + texture transfer high-to-low poly | Seam placement for hero assets | — |
| Skeleton and skin-weight transfer | Data Transfer modifier, automatic (heat) weights, Armature | Transfer between aligned, similar, clean meshes | Fused or non-manifold meshes (heat weights fail), cleanup | Forge rig/DNA mapping |
| Rigging assistance | Rigify, armature tools | Template placement | Fitting and checking | Forge skeleton contract |
| Morph-target preparation | Shape keys, Surface/Mesh Deform transfer | Transfer onto matching topology | Sculpted correctives | Forge v3 already owns its morph system |
| Conversion to Forge's GLB contract | Generic glTF export | Geometry, UVs and materials out | — | Forge-side post-process: `extras.forge`, profiles, joint names, validation |

Column A is documented Blender functionality, **not verified here**.

## 0D: Minimal job interface (proposed for production)

`forge.blender-job` v1, as implemented in the experiment, would be called by Forge through one Python function
(`bridge.run`) or the command line.

| Job | Parameters | Output |
|---|---|---|
| `inspect` | — | `report.json` |
| `validate` | — | Forge-side only (`verify.py`); no Blender needed |
| `simplify` | `ratio` | GLB + report |
| `extract_region` | operator boxes, `keep_largest` | GLB + report |
| later: `cap_holes`, `uv_unwrap`, `bake_textures`, `transfer_weights` | explicit parameters | new files only |

**Rules**
- One job, one input, new outputs only, a fresh directory, a log, a timeout and a pinned version.
- No access beyond the job directory: the input is copied in and stray writes are flagged.
  - This is **not an OS sandbox.** Blender's Python can technically read other files.
  - Isolation is by convention plus checks; real confinement would need an OS-level sandbox or container (open item).
- No background service and no general automation agent.

## 0E: Validation record

See **Phase 0 results** above: version, import/export, counts, geometry and scale, materials, timings, memory, visual defects and automation limits, all measured.

## Effort

| Work | Estimate |
|---|---|
| Run the prepared Phase 0 jobs (after approval or on the tower) and fix what breaks | 0.5-1 day |
| Production-quality optional bridge (packaging, pin, CI with or without Blender, Windows paths, 3-4 more jobs) | 1-2 weeks |
| Operator-assisted prop extraction (Forge preview/volume editor + extract + cap + UV + verify) | 1-2 weeks; then per prop: hours of operator time |
| Character-level work (retopology, rig and weight transfer, garments) | Months, with artist supervision; not recommended now |

## Approvals and open decisions

- **Done:** the `bpy` 5.2.2 install was approved and performed (isolated; see `DEPENDENCIES.md`).
- **Open: licensing.** The Blender-side job scripts need a licence if Forge ever distributes them (GPL-3.0-or-later
  recommended, kept separate).
- **Open: next step.** Choose one:
  - an operator-assisted prop extraction milestone (capping, UVs, review); or
  - the Studio reference overlay from the external-reference report.
