# Blender Bridge, Phase 0: isolated experiment

An optional, external Blender job bridge for asset processing. Forge stays the engine and editor. Blender processes
files through explicit jobs, and is never required to run Forge.

Nothing here is imported by Forge or changes Forge, generators v1/v2/v3, Character DNA, the Character Studio, Myth
or the Rodin source. Delete this folder and nothing else changes.

Report: `docs/BLENDER_BRIDGE_PHASE0.md`.

**Status: Blender has NOT been run.** The development container has no Blender. The only install route, `pip bpy`,
is a 402 MB wheel and is waiting for approval. Everything that does not need Blender is implemented and tested here.
`job_blender.py` is written against the documented bpy API but is **unexecuted**.

## Files

| File | Runs in | What |
|---|---|---|
| `bridge.py` | Forge's Python (stdlib) | Job runner: version pin (fail closed), input checksum, fresh sandbox directory per run, read-only input copy, subprocess with timeout and log, stray-file check, output hashes, `result.json`. Never imports bpy |
| `job_blender.py` | **Blender** (app or pip bpy) | One operation per job: `inspect`, `simplify` (Decimate), `extract_region` (faces in operator boxes -> new object, source untouched, cut boundaries left open and reported) -> `output/report.json` + GLB |
| `verify.py` | Forge's Python + numpy | Independent check of a job's output. Forge reader and validator, node transforms applied, numpy reference of the same extraction (exact face count, every vertex must come from the source), simplification deviation |
| `test_bridge.py` | Forge's Python | 7 tests: job contract, checksum refusal, sandbox, failure/stray/timeout reporting, version pin; verifier self-test (a correct extraction passes; a moved vertex, a 1 % rescale or missing faces fail) |
| `board_select.py`, `board_grow.py` | Forge's Python + numpy | Board segmentation probes on the Rodin mesh (no Blender), evidence in `results/` |
| `jobspecs/` | — | Jobs for the Rodin GLB: inspect, simplify 10 %, extract the v0 board slab (+ its numpy reference numbers) |
| `run_on_windows.ps1` | Windows | Runs the three jobs plus verification against an installed Blender (`-BlenderExe`) or a local bpy venv (`-InstallBpy`), and zips the results |

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
