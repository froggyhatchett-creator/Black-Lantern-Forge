# External 3D reference experiment (Rodin GLB, Static Lullaby character)

Isolated experiment. Nothing here is imported by Forge, changes Forge, or touches any character, preset or DNA.
Delete this folder and nothing else changes. Report: `docs/CHARACTER_FORGE_EXTERNAL_3D_REFERENCE.md`.

## Sources (git-ignored, never modified)

Place these in `source/`; they are kept read-only and not committed.

| File | What | sha256 |
|---|---|---|
| `source/base.glb` | Rodin export supplied by the project owner (authoritative; the OBJ export was not supplied) | `2f359f01…6e41f` (full value in `glb_mesh.py`) |
| `source/artwork.webp` | original Static Lullaby character artwork, 1152 x 1536 | `c320bed4…158bc9` |

The scripts assert the GLB checksum before use.

## Scripts (run from the repository root or here; Forge's Python, plus Node for the native character)

| Script | Output in `results/` |
|---|---|
| `inspect_glb.py` | `inspection.json`: structure, materials, skin/morph/animation counts, Forge validator, welded topology (boundary / non-manifold / orientation / components / genus), normals, edge lengths, bounds |
| `views.py` | `rodin_four_views.jpg`, `artwork_vs_rodin.jpg`, `artwork_vs_rodin_head.jpg`, `lineup_true_scale.jpg` (beside native v3 ID-A, 10 cm grid), `rodin_head_grid.jpg` (1 cm grid) |
| `facefit_probe.py landmarks\|free` | `facefit_<mode>.json/.jpg`: the v3 identity basis fitted to the Rodin face (probe only; nothing saved as a preset) |
