# Character Forge — engineering handoff (keep updated)

## Where things are
- Worktree: `/home/user/forge-worktrees/aaa-oneshot`, local branch `experiment/character-forge-aaa-oneshot`,
  pushed to `origin/claude/gifted-galileo-pwlplk` (`git push -u origin experiment/character-forge-aaa-oneshot:claude/gifted-galileo-pwlplk`).
- Main checkout `/home/user/Black-Lantern-Forge` and `feature/character-studio-step6c` stay at `5329fb3` (never touch).
- Phase 1 commits: `d13894b`, `1c3ebe1`, `6840f25`. Baseline tests: 714 OK / 7 skip; after phase 1: 761 OK / 7 skip
  (`python3 -m unittest discover -s tests`, ~19 min). New-only suites: `python3 -m unittest tests.test_character_forge_core ...`.
- Env: Python 3.13 + numpy + Pillow, Node 22, Chromium via Playwright (`/opt/node-tools/node_modules/playwright`,
  browsers in `/opt/pw-browsers`). No Blender, no tkinter, CDN/npm blocked from the container (403). Do not download.

## Phase 1 engine (package `forge_character_forge/`)
params.py (Body/Face/Genital params, presets) · skeleton.py (joints, A-pose, identity rest rot) · anatomy.py (SDF field)
· mesher.py/template.py (fixed-topology template, cached in `.forge_cache/`, key = hash of sources) · body.py
(warp + face RBF prewarp + projection) · rig.py (weights, FK, LBS) · expressions.py · appearance.py · accessories.py ·
clothing.py · dev_anatomy.py · physics.py · gltf.py · validate.py · dna.py · reconstruct.py · pipeline.py · cli.py ·
render.py/preview.py (software rasterizer). Tools: `tools/run_demos.py`, `tools/write_report.py`,
`tools/glb_independent_check.mjs`, `tools/make_references.py`. Report: `examples/character_forge_aaa/REPORT.md`.
Any edit to template/mesher/anatomy/sdf/skeleton/params/rig invalidates the template cache (~60 s rebuild).

## Phase 2: interactive Character Studio
Decision: static single-page studio, **own WebGL2 renderer (no three.js)** so it runs offline, inside a claude.ai
artifact, and is testable locally with Playwright/Chromium. Real-time editing uses a **baked piecewise-linear morph
basis** over the fixed topology: for every studio parameter, exact Python builds at the studio low/high end give
per-part vertex deltas and joint deltas (int16, sparse/dense), plus exact preset residuals. The browser sums deltas on
the CPU and skins on the GPU. Exact geometry for any combination: export the DNA and run the Python engine
(`export`), or the optional local server (`studio` command, `POST /api/export`).

Files:
- `forge_character_forge/studio_bake.py` — `bake` (105 exact builds, ~28 min / 4 workers), `compact_pack` ("d1p":
  first differences + byte planes for every int16/uint32 array; exactly reversible), `pack_array` (Python decoder),
  `refresh_hair` (swap in head-space hair + re-write clips on an UNCOMPACTED pack without re-baking), `studio_meta`.
- `forge_character_forge/hair.py` — volumetric hairstyles (pixie, bob, bangs, long) as SDFs in unit head space over a
  cached skin-distance grid of the default body; meshed, cleaned, QEM-decimated, cached (`.forge_cache/hair_*`).
  Placed per character with `O + v*k` (head frame). The studio recovers O,k exactly from the head/jaw joints.
- `forge_character_forge/lod.py` — QEM decimation onto existing vertices; `character_lod`; CLI `export --lod 0.25,0.1`.
- `forge_character_forge/studio_server.py` + CLI `python3 -m forge_character_forge studio --port 8765`.
- `studio/index.html`, `studio/studio.js`, `studio/gl.js`, `studio/glb.js`, `studio/studio_meta.json`,
  `studio/studio_clips.json`; pack `examples/character_forge_aaa/studio/studio_pack.bin` (14.5 MB, < 15 MB artifact cap).
- `tools/build_studio.py` (bake+compact), `tools/studio_smoke.mjs` (23 Chromium checks), `tools/studio_shots.mjs`
  (review screenshots), `tests/test_character_forge_studio.py` (12 tests).
- Raw (uncompacted) pack copy for `refresh_hair`: scratchpad `pack_raw.bin` (not in git; re-bake if lost).

## Phase 2 status
- DONE + verified in Chromium (smoke 23/23): boot, render, presets, body/face sliders, undo, drag rotate, zoom,
  coverage rule, garment swap, look, clips (idle/walk/run/jump/turn/sudden_stop/wave), live physics, camera orbit gives
  zero secondary motion, character spin gives inertia + tissue motion + settling, browser GLB export (validate_glb +
  Node check pass), DNA export validates in Python, DNA reload exact, phone width, no console errors.
- DONE: hairstyles pixie/bob/bangs/long + highlight streaks (appearance-only); DNA layers (`layer_of`,
  `anatomy_hash`: styling + wardrobe edits never change anatomy hash); exact export + LOD1/LOD2 validated by both
  validators (bangs, 184k -> 48k -> 22k tris, 112 s, ~270 MB RSS).
- SwiftShader (software GL) runs the studio at ~1-2 fps; real GPUs are not measurable here.

## Phase 2 status update (rasterizer fix, versioning)
- Software rasterizer (`render.py`, preview images only): near-plane clipping, off-screen culling, viewport-clipped
  boxes, 64 px tiles for large triangles. Old code gave a 4096x4096 test grid to any triangle with a 257-4096 px box
  and dropped boxes over 4096 px. Demo F head close-ups: base 290.5 s -> 8.3 s, LOD1/LOD2 >300 s (killed) -> 8.6/7.1 s,
  peak RSS 2.24 GB -> 0.93 GB. Images bit-identical in all 6 cases the old code could finish. Tests:
  `tests/test_character_forge_render.py`. Baseline copy: scratchpad `render_baseline.py`.
- Generator version 2 (`character.GENERATOR_VERSION`, `GENERATOR_HISTORY`): face changes re-meshed the template
  62,639 -> 62,550 vertices. GLBs and the studio pack now record generator id/version; v1 = commit 8ecaaad.
- Phase 2 demos: `python3 tools/run_phase2_demos.py [studio,sheets,H,F,G,kit]` (stages merge into summary.json).
  First full run hit its 5000 s limit inside F (rasterizer); F, G and kit then ran on their own and passed.

## Project Humanity (governing acceptance criteria, adopted)
Priority P0 preservation -> P1 visual realism (face, eyes, skin, hair) -> P2 studio (Simple/Advanced creator) ->
P3 anatomy fidelity + Developer Anatomy Lab -> P4 variety/optimization -> P5 reconstruction. Prove ONE excellent
adult character in the real studio before expanding. Finite credits: short visual experiments before any bake
(a full bake is ~31 min, 4 workers); never rebuild unchanged assets.

## Open problems / next actions
1. Commit/push checkpoint; publish the studio artifact (multi-file; `downloads` capability; GLB offered zipped).
2. Face realism (lips/eyes/brows) and anatomy fixes (hands, knees, feet) need a re-bake (~28 min) to reach the studio.
3. Reconstruction: long-hair/skirt detection, uncertainty; reusable-kit note; Phase 2 demos A-H + report.

## Full Phase 2 requirements (user message, condensed)
Studio must: sliders for body (6), face structure + expressions (7), hair/skin/eye appearance (8), clothing +
accessories (9), animation preview incl. idle/walk/run/jump/turn/sudden stop (10), visible skeletal deformation +
secondary motion (11), save/reload DNA (12), export validated GLB (13). Dragging to rotate the CHARACTER must cause
inertial secondary motion (hair, cloth, soft tissue); camera orbit must NOT. Adjustable stiffness/damping/intensity.
Public stays clothed; dev anatomy safeguards preserved. Quality: eyes/lids, mouth corners, jaw, teeth, expressions,
shoulders, knees, hands, fingers, feet, chest, hips; hair: pixie/shag, layered bob, asymmetric bangs, long; hair
color/highlights + clothing appearance separate from anatomical DNA. LOD pipeline with independent verification.
Reconstruction improvements (completion, provenance, locks, wardrobe, uncertainty). Reusable components for future
asset types (no Blender/Unreal runtime dependency). Demos A-H; report files, launch, exercised controls, assets,
screenshots, test results, perf/memory, commits, limitations, classifications.

## Plan order
1 smoke-test current pack + publish/commit · 2 JS: character-spin inertia, new clips, intensity, hair sway ·
3 server export + DNA round trip tests · 4 LOD (template-level QEM subset -> fixed LOD topology) · 5 visual fixes +
hairstyles -> rebake · 6 reconstruction fixes · 7 reusable kit note/demo · 8 report, commit, push.
