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

## Project Humanity P1 eye experiment (commit 9706334)
- Per-pixel eye shading (studio/gl.js kind 3/4, uniform uEyeC); socket tint fixed in appearance.py, and only the
  pack's body colour array was regenerated. Evidence and captures: examples/character_forge_aaa/humanity/p1_eyes,
  reproduced with `node tools/studio_eye_shots.mjs <url> <out>`.
- Clear improvement in close-ups (no red ring, round natural iris, no cornea rim); subtle at full-face framing.
- Remaining ANATOMICAL defects: blink morph closes the lids only ~7.7 mm (eyes stay open); the polygonal lid
  aperture clips the iris; there are no visible lid-margin thickness or tear meniscus geometry; lashes are sparse cards.
  Remaining SHADING defects: no iris parallax or refraction; the browser GLB keeps the old UV iris.

## Reference benchmarks (registered 2026-10-15)
`examples/character_forge_aaa/benchmarks/benchmarks.json` lists byte-exact copies with SHA-256 hashes.
- REF-001 Mercy: ACTIVE reference for Project Humanity's first believable human. It is an anime-stylized
  illustration in a seated pose under purple lighting, so a realistic result is an interpretation; never claim likeness.
- REF-002 Gothic Centaur, REF-003 Tavern Cowgirl: future creature-system tests only, not authorized for current work.
- Numbering follows attachment order (renumbered the same day; commit ad589fc used the old IDs, and the registry
  records the old-to-new mapping).
- Not reconstructed yet. No generation or bake jobs launched for them.

## Post-baseline priority (REF-001 failed; P5 paused, kept long-term)
- REF-001 baseline is preserved as evidence (`humanity/ref001_baseline/`, commit ad4635c). Do not overwrite it.
- Back to P1. The foundation question (improve the SDF mesh, or adopt a licensed base mesh as generator v3) is in
  `docs/CHARACTER_FORGE_FOUNDATION_ASSESSMENT.md`, awaiting review. Open defects D-001..D-005 are in
  `docs/CHARACTER_FORGE_DEFECTS.md`.

## Generator v3 Phase 1 (authorized; milestone reached, stopped for review)
- Plan: `docs/CHARACTER_FORGE_V3_PLAN.md`; milestone report with numbers and limitations: `docs/CHARACTER_FORGE_V3_PHASE1.md`.
- Code `forge_character_forge/v3/` (CC0 MakeHuman hm08 assets + provenance, 62-joint rig mapping all 163 bones,
  53 labelled controls 36/16/1, fitted blink corrective with per-control correctives, plane-clipped basic garments,
  pack bake ~2 min). Pack `examples/character_forge_aaa/studio/studio_pack_v3.bin`, meta `studio/studio_meta_v3.json`.
- Studio: generator selector (`?gen=3` / `#v3`); v2 stays the default and unchanged (v2 smoke 23/23).
- Tests `tests/test_character_forge_v3.py` (17, ~2.5 min incl. a full re-bake); browser check
  `tools/studio_v3_check.mjs`; evidence `examples/character_forge_aaa/humanity/v3_phase1/`.
- Next (needs owner approval): brows/lashes/hair and skin maps on v3 (biggest realism gap), more expressions,
  draped garments, the Forge identity layer on v3, Python exact export for v3.

## Generator v3 Phase 2: visual quality (milestone reached, stopped for visual review)
- Report: `docs/CHARACTER_FORGE_V3_PHASE2.md`; evidence `examples/character_forge_aaa/humanity/v3_phase2/` (matched
  before/after from the Phase 1 build vs this build, blink, variations, motion, GLB).
- Forge-generated skin maps (`v3/textures.py`, cached in `.forge_cache/v3_textures_*`), MakeHuman CC0 eye texture,
  Forge strand grooming (`v3/grooming.py`: brows/lashes anchored in triangle frames, hair cage-bound to the skin).
- Studio: textures, normal map, textured eyes, strand shader with alpha-to-coverage, scalp tint, GLB images/strands.
- SwiftShader is slow with the hair (close-ups take 2-3 min per frame); tools use a 1000x700 viewport.
- MakeHuman's skins/brows/lashes/hair (repo `makehuman-assets`, LFS) are unreachable from this environment.

## Generator v3 Phase 3A/3B: identity foundation (stopped at the review gate)
- Report `docs/CHARACTER_FORGE_V3_PHASE3.md`; code `forge_character_forge/v3/identity.py` (32 linear regional
  parameters, smoothing, rigid ears, eyes follow lids); proof `tools/identity_proof.py`, `tools/identity_closeups.py`;
  evidence `examples/character_forge_aaa/humanity/v3_phase3/`; tests `tests/test_character_forge_v3_identity.py`.
- Not started (await approval): 3C Mercy-inspired stylisation, 3D animation/DNA, 3E studio integration.

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
