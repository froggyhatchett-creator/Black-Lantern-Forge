# Blender Bridge Phase 0: assessment and isolated proof (stopped at the install gate)

## Recommendation: CONDITIONAL GO

**Blender as an optional, out-of-process job tool: yes.** Its value is real for generic glTF I/O, decimation,
remeshing, UV unwrapping, texture baking and data transfer. It is clean to isolate, provided Forge never imports it.

**Blender does not solve the hard part of the Rodin task.** Deciding where the board ends and the character begins
is the hard part. Blender gives an excellent operator UI and robust mesh operations for that, not an automatic answer.

**Conditions for the GO**
1. **Install approval.** Approve a 402 MB `bpy` install here, or run the prepared Windows job on your tower.
2. **Verification.** The three prepared jobs must pass Forge's independent verification (`verify.py`), not merely
   export a file.
3. **GPL boundary.** Blender stays a separate process exchanging files, and Forge never imports `bpy`.
4. **Optional.** Blender stays optional, with no Forge feature depending on it. Forge already has its own QEM
   decimation (`lod.py`).

**Not yet demonstrated: Blender itself.** No Blender ran. Success criteria 1, 2, 4, 5 and 6 are therefore **open**;
criterion 7 holds (production systems untouched). Everything that does not need Blender is built and tested.

Experiment: `experiments/blender_bridge/` (README there).

## 0A: Environment and architecture

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

### Prepared, NOT executed (needs Blender)

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

| Item | Recorded |
|---|---|
| Blender version | **not available here** (pin: 5.2.2) |
| Import / export success | **not executed** |
| Source counts (reference for the Blender import) | 500,000 triangles; 504,919 vertices as stored; 249,818 welded; 1 mesh, 1 material, 0 images, 0 skins/morphs/animations |
| Expected Blender `inspect` | 500,000 triangles in 1 mesh object; ~249.8k vertices with merge on, 504,919 with it off |
| Expected v0 board extraction | 54,228 triangles, 11 open boundary loops (numpy reference) |
| Scale and coordinates | Source in metres, +Y up, +Z front, feet at y = 0. Blender converts Y-up to Z-up on import and back on export; `verify.py` checks bounds after node transforms |
| Time and memory | Recorded per job by `bridge.py` (peak RSS on Linux/macOS). Forge-side probes: topology inspection 5.8 s; region growth 0.2 s plus rendering (selection not timed) |
| Visual defects | Board segmentation evidence in `results/` |
| Automation limits | Board separation is not automatable on this asset (above) |

## Effort

| Work | Estimate |
|---|---|
| Run the prepared Phase 0 jobs (after approval or on the tower) and fix what breaks | 0.5-1 day |
| Production-quality optional bridge (packaging, pin, CI with or without Blender, Windows paths, 3-4 more jobs) | 1-2 weeks |
| Operator-assisted prop extraction (Forge preview/volume editor + extract + cap + UV + verify) | 1-2 weeks; then per prop: hours of operator time |
| Character-level work (retopology, rig and weight transfer, garments) | Months, with artist supervision; not recommended now |

## Approval needed

1. **The install.** Either:
   - approve installing `bpy==5.2.2` (402 MB) in an isolated venv inside `experiments/blender_bridge/` here; or
   - run `run_on_windows.ps1` on your tower and send back `blender_bridge_results.zip`.
2. **Licensing of the Blender-side job scripts** if Forge ever distributes them (GPL-3.0-or-later recommended,
   kept separate).
