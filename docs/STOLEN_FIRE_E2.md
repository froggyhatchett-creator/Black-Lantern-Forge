# Operation Stolen Fire E2: optional foot locks for the v3 walk and run (stopped for review)

Branch `experiment/stolen-fire-e2-footlocks`, from `0c90bee`, the current Character Forge development baseline. It
does not touch PR #1 (`experiment/hair-gradient-v1`) or merge anything.

## Result

**Ankle and foot are pinned while locked; nothing changes when the option is off. Both twins agree.**

| What | Result |
|---|---|
| Ankle drift while locked (3 characters, walk and run) | **0.0001 mm or less** (before: 69–111 mm) |
| Foot turn while locked | **0.0000°** (before: 43–52°) |
| Option off | Exports **byte-identical** to the baseline (3 of 3; the same sha256 as `0c90bee`) |
| Python vs browser | Agree to 3e-8 on the shared fixtures; to 4e-7 on the exported GLBs |
| GLB checks | Public validator 0 errors; independent checker OK; only the 12 leg rotation accessors of walk and run change |
| Studio checks | 16/16 |
| Regressions | Full suite 857 OK; v2 Studio smoke 23/23; v3 Studio check pending (environment-limited, see [Test results](#test-results)) |

**Not solved, and measured: the stance foot hovers.**
- Forge's clips hold the hips too high for the planted foot to reach the floor.
- With E2, the walk's locked foot is held at a steady **15–32 mm** above the floor. Before, it slid through the floor, from 26 mm below it to 38 mm above.
- The run's locked foot is held at **39–46 mm**. Before, the runner touched the floor (0.8–11.5 mm) and then rose. **Ground contact in the run is worse with locks on.**
- Lowering the hips changes the root (pelvis) channel. That is outside this experiment's scope (thigh and calf correction) and is the first item under [Remaining work](#remaining-work).

## Why the method differs from Effigy's foot lock

**Forge's walk and run are in-place loops.**
- The hips stay over the origin, and each foot swings forward and back under them.
- The root moves only up and down: walk ±22 mm, run 45 mm.

**Effigy's contact rule cannot be reused as-is.**
- Effigy (`ui/src/anim/clip.ts`, `contacts`) finds contacts where the foot is low and nearly still (below 15 % of the body height per second).
- In an in-place clip the stance foot travels backwards at the stride speed, about 1.5 m/s in the walk and 4.8 m/s in the run. So Effigy's rule finds no contact at all.

**E2 locks the foot in a ground frame instead.**
- The ground frame moves back at the clip's own stride speed (a treadmill belt).
- A game that moves the character forward at that speed sees the planted foot stand still.
- The speed is written into the GLB for that purpose.

**What is Effigy's:** the solver, the blend towards the target, the mid-stance target rule, and the slerp / shortest-turn arithmetic.

## Method (`forge_character_forge/v3/footlock.py`, twin `studio/footlock.js`)

For each character (its own rest skeleton, its own height-scaled hip motion) and for walk and run:

1. **Forward kinematics** of the clip, exactly as the Studio exports it.
2. **Stance per foot.** The longest cyclic run of frames where the ankle is in the lowest quarter of its height range and travels backwards.
3. **Ground speed `v`.** The mean over both feet of the ankle's travel across its stance, divided by the stance time.
4. **Locked span.** The middle 60 % of the stance (at least 3 frames): walk 9 and 8 frames, run 4 and 4.
5. **Plant point.** Effigy's rule: the source pose at mid-stance.
   - It uses that frame's ankle x and z and the foot's world rotation.
   - It then moves back at `v`.
   - Its height is as low as the leg allows. The lower of two sole support points (heel, toe tip, derived from the ankle and ball joints) goes on the floor, unless that is out of reach somewhere in the span with the knee bent at least 5°. In that case the plant uses the lowest height reachable over the whole span.
6. **Each frame of the window.** The window is the span plus 3 frames of position blend and 6 of rotation blend on each side, with smoothstep weights.
   - Two-bone IK of thigh > calf (Effigy `_two_bone`) puts the ankle at `source + (plant − source)·w`.
   - The knee turns about the source pose's own bend axis, so its bending direction cannot flip.
   - The knee is never straighter than 5°: a farther target is pulled in along the hip-to-ankle line.
   - The foot's world rotation blends towards the planted rotation and is held fixed while locked.
7. **Writes.** Only the thigh, calf and foot rotation channels of walk and run change. Channel sets, key times, the pelvis translation and every other clip stay as they were.

Everything is plain float64 arithmetic in a fixed order, so the same inputs give the same bytes.

### Approaches tried and rejected (measured)

| Tried | Result |
|---|---|
| Flat foot at rest ankle height (the sole on the floor, as in the rest pose) | Out of reach in every stance: the hips are too high |
| Plant at the mid-stance ankle height, span = longest reachable run | Locked fine, but the run's lowest point rose from 0.8 to 23 mm above the floor for the whole cycle |
| Longer position blends (4–6 frames) | Helped the walk, worsened the run (its stance is only 6 frames) |
| Unclamped knee (Effigy's limit, just short of straight) | Knees reached 0.2° (locked straight) in blend frames |

## The option in the Studio

- **Control.** A checkbox, `Foot locks (walk, run)`, in File › Export.
  - It is shown on generator v3 only and is unticked by default (`studio_export_panel.png`).
  - It is a Studio export setting, not a DNA trait. The DNA is unchanged by it (checked).
- **When ticked,** the preview plays the locked walk and run, and `Export GLB` writes them.
- **Metadata.** The GLB gains `asset.extras.forge.animation_corrections.foot_lock`. It records:
  - the version, the method and its source;
  - the blend lengths;
  - per clip, `ground_speed_m_s` and each foot's locked span.
- **When unticked,** nothing is added and the bytes are the baseline's.

## Files

| File | Change |
|---|---|
| `forge_character_forge/v3/footlock.py` | New: the Python reference |
| `studio/footlock.js` | New: the browser twin (no DOM, no three.js) |
| `studio/studio.js` | Option state, cached locked clips per character, preview, export |
| `studio/glb.js` | Writes `animation_corrections` only when present |
| `studio/index.html` | The checkbox and one note line |
| `tests/test_character_forge_v3_footlock.py` | New, 9 tests (below) |
| `tests/fixtures/footlock/{neutral,long_legs}.json` | New: the Studio's exact inputs plus the Python result (shared with the JS check) |
| `tools/footlock_parity.mjs` | New: JS against the fixtures in Node |
| `tools/studio_v3_footlock.mjs` | New: the Studio run, with the off/on exports and the UI and DNA checks |
| `tools/footlock_report.py` | New: measures off vs on GLBs, then writes plots and renders |
| `examples/character_forge_aaa/stolen_fire_e2/` | Evidence: report.json, plots, renders, screenshots, studio_checks.json, GLB sha256s |
| `THIRD_PARTY_NOTICES.md` | New: Effigy's MIT notice |
| `docs/STOLEN_FIRE_E2.md` | This report |

**Not changed:** the skeleton, Character DNA and its hashes, the v1/v2/v3 generators, the pack, the GLB contract version, the validator, the clips' source (`animation.py`), Myth, the Blender bridge and PR #1. The exported GLBs (12 MB each) are not committed; their sha256 values are in `glb_sha256.txt`.

## Attribution and licence

- Adapted from **Effigy** `steps/_anim.py`, © 2026 SifuInTheShell, MIT, read at `c62db21`. Adapted parts: `_two_bone`, `_lock`'s target rule, `_s`, `slerp`, `_between`, `_turn`.
- The full licence text is in `THIRD_PARTY_NOTICES.md`, and both source files carry the attribution in their headers.
- No Effigy model, asset, GPL `blender_ops` code or dependency is used.

## Measurements

The three characters are:
- **neutral:** 1.75 m;
- **ID-A:** `v3_identity_id_a.dna.json`, 1.66 m;
- **long legs:** neutral with `body.leg_length` at its maximum, 1.2.

Everything is read back from the exported GLBs by `tools/footlock_report.py`, independently of the Studio. "Before" is the option off (equal to the baseline); "after" is on. Drift and rotation are measured in the ground frame over the locked frames only. Blend frames are reported separately.

| Character | Clip | Foot | Locked (start, frames) | Ankle drift (mm) | Foot turn drift (°) | Sole height while locked (mm, min…max) | Knee flex min while locked |
|---|---|---|---|---|---|---|---|
| neutral | walk | left | 12, 9 | 105.2 → 0.0000 | 51.9 → 0.0000 | −21.9…24.4 → 28.4…28.4 | 5.0° |
| neutral | walk | right | 27, 8 | 105.4 → 0.0001 | 42.7 → 0.0000 | −21.1…36.4 → 18.3…18.3 | 5.0° |
| neutral | run | both | 8 / 18, 4 | 77.1 → 0.0000 | 51.6 → 0.0000 | 0.8…107.6 → 42.5…42.5 | 5.0° |
| ID-A | walk | left | 12, 9 | 97.8 → 0.0000 | 51.9 → 0.0000 | −9.2…22.7 → 27.7…27.7 | 5.0° |
| ID-A | walk | right | 27, 8 | 96.4 → 0.0000 | 42.7 → 0.0000 | −12.5…33.4 → 14.6…14.6 | 5.0° |
| ID-A | run | both | 8 / 18, 4 | 68.6 → 0.0000 | 51.6 → 0.0000 | 11.5…99.3 → 39.3…39.3 | 5.0° |
| long legs | walk | left | 12, 9 | 111.1 → 0.0000 | 51.9 → 0.0000 | −14.2…25.8 → 31.6…31.6 | 5.0° |
| long legs | walk | right | 27, 8 | 110.6 → 0.0001 | 42.7 → 0.0000 | −17.2…38.5 → 19.6…19.6 | 5.0° |
| long legs | run | both | 8 / 18, 4 | 80.3 → 0.0000 | 51.6 → 0.0000 | 6.9…111.0 → 45.5…45.5 | 5.0° |

| Character | Clip | Ground speed | Lowest body point over the cycle (mm) | Knee flex min, cycle | Thigh max world step (°/frame) | Ankle max acceleration (m/s²) |
|---|---|---|---|---|---|---|
| neutral | walk | 1.634 m/s | −25.9 → −15.1 | 14.7° → 5.0° | 5.6 → 8.7 | 34.2 → 36.6 |
| neutral | run | 4.825 m/s | 0.8 → 42.5 | 31.6° → 5.0° | 14.1 → 25.4 | 126.0 → 125.5 |
| ID-A | walk | 1.506 m/s | −13.1 → −3.2 | 15.4° → 5.0° | 5.6 → 8.9 | 31.8 → 33.8 |
| ID-A | run | 4.445 m/s | 11.5 → 39.3 | 32.2° → 5.0° | 14.1 → 24.4 | 116.7 → 115.6 |
| long legs | walk | 1.720 m/s | −18.0 → −9.5 | 14.5° → 5.0° | 5.6 → 9.1 | 36.1 → 38.3 |
| long legs | run | 5.083 m/s | 6.9 → 45.5 | 31.2° → 5.0° | 14.1 → 25.1 | 133.3 → 133.1 |

What else the measurements show:

- **Bone lengths** are kept to 5e-8 m in every frame (the source clip's own float32 level).
- **Knee bending direction** is the same as the source in every frame, for all 12 legs.
- **Quaternions** are unit to 3e-8, with no NaN and no hemisphere flips inside a clip.
- **Floor.**
  - Inside the lock windows no foot is below the floor. Before, the stance dipped to −26 mm.
  - The walk's remaining penetration (−15 mm on the right foot at frame 18, −2 mm on the left at frame 2) is the source's swing-phase toe scuff. It lies outside every window and is unchanged.
- **Continuity.**
  - The calves and feet move no faster in world space than before. Their peak steps are 14.6 / 16.5° per frame in the walk and 33.9 / 38.4° in the run, unchanged; ankle peak acceleration is within ±7 %.
  - **The thighs move faster around the transitions:** walk peak 5.6 → 8.7–9.1° per frame, run 14.1 → 24.4–25.4° per frame.
  - No loop-seam step exceeds the clip's own largest step. The seam step of the run's right calf grew by 0.8° (14.1 → 14.9), still below the clip's 33.9° peak.
  - The foot's local channel steps grow (walk 2.0 → 10.3°/frame). This is expected: the foot is now held while the leg moves above it.
- **Knee flex in stance** goes down: walk 14.5–15.4° → 5°, run 31–32° → 5°. Planting on these clips needs straighter stance knees. It is a visible style change.

**Plots and renders** (`examples/character_forge_aaa/stolen_fire_e2/`):

| File | What it shows |
|---|---|
| `trajectory_walk.png`, `trajectory_run.png` | One cycle of the ankle path in the ground frame. Grey is before, orange after, dots the locked frames |
| `trajectory_*_stance.png` | Zoomed on the lock and its blends: the grey 7–11 cm loop becomes one orange point |
| `floor_walk.png`, `floor_run.png` | The lowest skinned body vertex per frame |
| `renders_walk_left_foot.jpg` | Side views of the left leg (blend in, three locked frames, blend out) for each character, before and after. The body is shifted by the belt; the cube marks the ankle at the first locked frame. After, it stays hidden in the planted ankle; before, the foot slides away from it |
| `studio_walk_foot_locks_on.png`, `studio_export_panel.png` | The Studio with the option on |

## Test results

| Check | Result |
|---|---|
| `tests/test_character_forge_v3_footlock.py` (9: solver reach/lengths/foot turn over 200 random legs, knee direction, out-of-reach and straight legs, blend weights, fixture match and determinism, locked ankle/foot/knee/bone checks, only leg channels change, untouched clip without legs, metadata record) | 9/9 OK |
| `tools/footlock_parity.mjs` (JS vs Python, 2 characters × 2 clips) | 4/4 PASS, worst 2.96e-8 |
| `tools/studio_v3_footlock.mjs` (Studio: option hidden on v2, shown and unticked on v3; checkbox drives it; off → on → off gives the same off bytes; DNA unchanged; preview uses locked clips; no console errors) | 16/16 PASS |
| Option off vs baseline `0c90bee` | byte-identical, 3/3 |
| `tools/footlock_report.py` (validator public, independent check, contract diff) | 3/3 valid, contract equal apart from the 12 leg accessors and the added metadata |
| Full suite `python3 -m unittest discover -s tests` | **857 tests OK, 7 skipped** (848 before + 9 new; 2,200 s) |
| `tools/studio_smoke.mjs` (v2 Studio) | **23/23 PASS**, run with a 10-minute screenshot timeout as in Phase 4A.1 (SwiftShader here takes ~28 s per view screenshot, at the default 30 s limit; the default run timed out on a screenshot after 9 passes). Log: `v2_studio_smoke.txt` |
| `tools/studio_v3_check.mjs` (v3 Studio) | **Pending.** 4/4 checks before the first screenshot pass (boot, generator, all 53 controls, exact height); the run then stalls on SwiftShader screenshots. Two attempts were lost (a 30 s screenshot timeout under load, then a container restart). A frame-rate probe shows the same speed on the baseline and on E2 (2.5 vs 2.2 frames/s, a 27 vs 28 s screenshot), so this is the environment, not E2. Re-running |

## Pass/fail against the E2 proposal

| Criterion (proposal) | Verdict |
|---|---|
| Solver: ankle within 1e-6 m, lengths 1e-9, no NaN, foot keeps its world turn, smooth blends | **Pass** (lengths 1e-12 in synthetic tests; 5e-8 on the real float32 clips, as the source) |
| Contact detection repeatable | **Pass** (same spans in Python and JS; repeated exports identical) |
| Ankle drift ≤ 1 mm in each stance phase | **Pass for the locked span** (≤ 0.0001 mm). Only the middle 60 % of each stance is locked; the stance ends blend |
| Nothing goes into the floor | **Pass inside the lock windows.** The pre-existing swing-phase toe scuff remains outside them |
| Loop seam no worse; no knee flips | **Knee: pass.** **Seam: pass in intent** (no seam step exceeds the clip's peak); literally +0.8° on the run's right calf |
| Off = byte-identical; validator, independent checker and playback pass; only thigh/calf/foot values of walk and run differ | **Pass** |
| Python and JavaScript agree to 1e-5 | **Pass** (3e-8 / 4e-7) |
| Full suite, `studio_smoke`, `studio_v3_check` | **Suite and v2 smoke pass; v3 check pending** (see [Test results](#test-results)) |
| *(observed, not a proposal criterion)* ground contact | **Walk better** (no penetration while locked; the foot hovers 15–32 mm instead of sliding through the floor). **Run worse** (hovers 39–46 mm where it touched before) |

## Known limitations

1. **Hover.** The planted foot cannot reach the floor because the clips' hip height is fixed. Run locks raise the runner's lowest point by about 4 cm. Use run locks only with a game that grounds the character itself, or wait for E2.1.
2. **Straighter stance knees** (5°) and **faster thigh motion** at transitions: the run's thigh peaks about 80 % faster.
3. **Only part of each stance is locked** (the middle 60 %). The ends blend from the clip's own sliding motion.
4. **No toe roll:** the foot is held at its mid-stance turn. The ball (toe) joint is not animated.
5. **Support points from joints:** the heel and toe tip are estimated from the ankle and ball joints, with ratios measured on the neutral body. The measured sole heights above are from the skinned mesh.
6. **Walk and run only.** Turn and sudden_stop have no foot channel, and adding one would change the channel set. Idle, jump and wave are not locomotion loops.
7. **Pre-existing, not changed:** the walk's swing-phase toe scuff (−15 mm). Also, the Studio preview loops over `frames − 1` and GLB playback holds the last key, so neither interpolates the last-to-first key of a loop. That affects every clip.

## Remaining work

1. **E2.1, hip height** (needs approval: it changes pelvis translation values, not the channel set). Lower the pelvis per character by the reach shortfall during stance, so the locked foot can reach the floor. Measure contact, knee flex and the thigh speed-up again.
2. Toe roll at heel strike and toe off, from the ball joint.
3. Expose `ground_speed_m_s` in the Studio, and offer a root-motion variant of walk and run (a contract question).
4. Port the same lock to the v2 Python export if v2 remains in use.

## Reproduce

```
python3 -m forge_character_forge studio --port 8799 &
node tools/studio_v3_footlock.mjs http://127.0.0.1:8799/ /tmp/e2
python3 tools/footlock_report.py /tmp/e2/off /tmp/e2/on /tmp/e2/report
node tools/footlock_parity.mjs
python3 -m unittest tests.test_character_forge_v3_footlock
```
