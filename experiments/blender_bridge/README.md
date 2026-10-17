# Blender Bridge, Phase 0: isolated experiment

An optional, external Blender job bridge for asset processing. Forge stays the engine and editor. Blender processes
files through explicit jobs, and is never required to run Forge.

Nothing here is imported by Forge or changes Forge, generators v1/v2/v3, Character DNA, the Character Studio, Myth
or the Rodin source. Delete this folder and nothing else changes.

Reports: `docs/BLENDER_BRIDGE_PHASE0.md` (static assets), `docs/BLENDER_BRIDGE_PHASE1.md` (rigged v3 character round trip).

**Status (2026-10-17): run with Blender 5.2.2 (`bpy`, isolated venv, approved).**
- Done: inspect, unchanged round trip, simplification, and three board extractions.
- Every job's output was checked by `verify.py`.
- Results: `docs/BLENDER_BRIDGE_PHASE0.md` ("Phase 0 results") and `results/`.
- Dependencies and licences: `DEPENDENCIES.md`.

Set up the environment (Linux, Python 3.13; about 1.4 GB):

```
python3 -m venv .bpy-venv
.bpy-venv/bin/python -m pip download --no-deps "bpy==5.2.2" -d .wheels   # check its sha256 against PyPI
.bpy-venv/bin/python -m pip install .wheels/bpy-5.2.2-*.whl
python3 bridge.py run jobspecs/<job>.json --launcher bpy --exe .bpy-venv/bin/python
python3 verify.py jobs/<run dir>
python3 render_results.py roundtrip|simplify|board jobs/<run dir> [tag]
```

## Files

| File | Runs in | What |
|---|---|---|
| `bridge.py` | Forge's Python (stdlib) | Job runner: version pin (fail closed), input checksum, fresh sandbox directory per run, read-only input copy, subprocess with timeout and log, stray-file check, output hashes, `result.json`. Never imports bpy |
| `job_blender.py` | **Blender** (app or pip bpy) | One operation per job: `inspect`, `roundtrip` (no edits), `rig_roundtrip` (skinned and animated character; scene fps pinned), `weights_smooth_copy` (smooth one bone's weights on a copy; optional weld first), `simplify` (weld + Decimate), `extract_region` (faces in operator boxes, or whole UV islands voted by boxes and edited by operator picks -> new object; source untouched; cut boundaries left open and reported) -> `output/report.json` + GLB |
| `verify.py` | Forge's Python + numpy | Independent check of a job's output: Forge reader and validator, node transforms applied. Round trip: every triangle matched by position, per-corner normals and UVs, materials. Extraction: numpy reference of the same selection (including its own UV-island labelling) with an exact triangle-set comparison, every vertex from the source. Simplification: deviation, and no new open edges on welded geometry |
| `test_bridge.py` | Forge's Python | 7 tests: job contract, checksum refusal, sandbox, failure/stray/timeout reporting, version pin; verifier self-test (a correct extraction passes; a moved vertex, a 1 % rescale or missing faces fail) |
| `board_select.py`, `board_grow.py` | Forge's Python + numpy | Board segmentation probes on the Rodin mesh (no Blender), evidence in `results/` |
| `probe_blender_selection.py` | **Blender** | Blender's own part finders on the welded mesh: loose parts, UV islands, sharp-edge islands |
| `render_results.py` | Forge's Python | Evidence sheets of job outputs with Forge's renderer (round trip with pixel difference, simplification, board) |
| `rig_compare.py` | Forge's Python + numpy + Node | Phase 1: independent comparison of a rigged GLB and its Blender round trip (validator, metadata, skin, meshes matched per vertex, weights by joint name, morphs, materials and image pixels, animation values at the source key times, playback through `tools/glb_playback.mjs`) |
| `render_rig.py`, `render_weights.py` | Forge's Python + Node | Phase 1 renders: rest, walk, blink and pixel difference (colours from each file's own textures); weight heat maps and posed knee for the weight edit |
| `DEPENDENCIES.md` | — | Installed packages, versions, licences, checksum, licensing concerns |
| `jobspecs/` | — | Jobs for the Rodin GLB: inspect, round trip, simplify 10 %, board extraction (slab v0; UV islands v1 and v2 with operator picks) |
| `run_on_windows.ps1` | Windows (not executed: no Windows here) | Runs the jobs plus verification against an installed Blender (`-BlenderExe`) or a local bpy venv (`-InstallBpy`), and zips the results |

## Job contract (`forge.blender-job` v1)

```json
{"schema": "forge.blender-job", "schema_version": 1, "operation": "extract_region",
 "input": "../../rodin_reference/source/base.glb", "input_sha256": "2f359f01...",
 "output": "board_slab_v0.glb", "params": {"boxes": [{"centre": [..], "axes": [[..],[..],[..]], "half": [..]}]}}
```

**What the runner does with a job**
- `input` is resolved relative to the job file and must match `input_sha256`.
- `output` must be a bare `.glb` name, written only inside the run's `output/` directory.
- Each run gets a new directory under `jobs/` (git-ignored) containing:
  - `job.json`
  - `input.*` (a read-only copy)
  - `blender.log`
  - `output/`
  - `result.json`
  - `verify.json`
- The source file is never opened for writing.

**Licensing**
- Blender and `bpy` are GPL-3.0. Forge never links or imports them.
- `job_blender.py` imports `bpy`. If it is ever *distributed*, the Blender Foundation treats such scripts as GPL
  covered, so it is kept as a separate component.
- Licensing it (GPL-3.0-or-later) is the project owner's decision, not made here.
