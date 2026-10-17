# Myth v0.3.0 proof of concept (isolated)

An experiment, not part of Forge. It renders one existing Character Forge v3 GLB with
[Myth](https://github.com/panxinmiao/myth) (Rust/wgpu engine, MIT OR Apache-2.0) through its Python wheel `myth-py`.
It checks the result against our own independent GLB player.

Isolation rules:
- No Forge package imports Myth, and Myth is not in `pyproject.toml`.
- Nothing here changes Forge, Character Forge, Black Lantern OS or the GLB.
- Delete this folder and nothing else changes.

| File | Runs where | What |
|---|---|---|
| `make_reference.py` | here (Forge's Python + Node) | our side: `tools/glb_playback.mjs` (independent glTF reader) + `render.py` (CPU) -> `reference/` |
| `reference/` | committed | `cameras.json` (shared cameras and frames), masks, shaded images, `metrics.json` |
| `myth_poc.py` | any machine with a GPU | Myth side: loads the GLB, validates it, renders the same frames -> `myth_out/` |
| `compare.py` | anywhere (stdlib only) | silhouette IoU, blink closure, clothing coverage, side-by-side images -> `myth_out/compare_report.json` |
| `run_on_windows.ps1` | your Windows tower | venv + `pip install myth-py==0.3.0` + `myth_poc.py` + `compare.py` + zip of results |

## Run it on the Windows tower

```
cd <repo>\experiments\myth_poc
powershell -ExecutionPolicy Bypass -File .\run_on_windows.ps1            # headless test + comparison
powershell -ExecutionPolicy Bypass -File .\run_on_windows.ps1 -Window    # then the interactive viewer
```

It needs Python 3.10+ and a current GPU driver (DX12 or Vulkan); it downloads one ~8 MB wheel and nothing else.
Send back `myth_poc_results.zip`.

**Not executed by me:**
- The PowerShell script itself: this container has no PowerShell.
- The `--window` mode: it has no display or GPU.
- Any Myth rendering at all.

## Frames and checks

The input is `examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.glb` (committed, unchanged):
- 10 meshes on one 62-joint skin, and 7 clips;
- blink as sparse morph targets `blink_l` / `blink_r` (no bufferView, zero base, u32 indices) on the body, brows,
  lashes and hair;
- plain metallic-roughness materials with PNG textures, MASK strand cards and a BLEND cornea.

Frames, at 640x480 and a vertical field of view of 26°:
- full body, front and three-quarter, rest pose;
- face close-ups, front and three-quarter, at blink 0, 0.5 and 1;
- walk clip frame 10 (t = 10/30 s, stepped with a fixed dt), three-quarter, full body.

Each frame is measured the same way on both sides:
1. Render the frame.
2. Render it again without the meshes in question.
3. The pixels that changed are those meshes' visible area.

Strand cards (brows, lashes, hair) are hidden in the measured passes on both sides. Our CPU reference rasterizer
ignores alpha masks, so including them would compare renderers instead of geometry. They are present in Myth's
beauty frames.

**Criteria (fixed before any Myth result existed):**

| Check | Pass if |
|---|---|
| Validation | 10 mesh nodes; 2 morph targets each on body, brows, lashes and hair; the 7 clips; weights read back as set |
| Skinning and pose | silhouette IoU >= 0.95 on rest frames, >= 0.92 on the walk frame |
| Sparse blink morphs | visible eyeball at blink 0 within 25 % of ours; blink 0.5 / 0 within 0.15 of our ratio; blink 1 / 0 <= 0.02 |
| Clothing | garment pixels on full-body frames within 15 % of ours, and > 0 |

`compare.py` was itself tested here. Our reference against itself passes everything. A sabotaged copy fails exactly
the four planted defects: clothing 0 px, walk silhouette shifted (IoU 0.36), and eyes that never close (front and
three-quarter).

## Results so far

See `RESULTS.md`.
