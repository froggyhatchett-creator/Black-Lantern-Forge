# Generator v3, Phase 4A.1: facial stabilization and regression hardening (stopped for review)

Status: **corrective milestone; stopped for review. Phase 4B (expressions) not started.** No new sliders,
expressions, FACS, lip-sync, identity parameters, hair, wardrobe, reconstruction or creature work. The 36 identity
parameters, 53 controls and identity basis v1 (and its recorded fingerprints) are unchanged.

Evidence: `examples/character_forge_aaa/humanity/v3_phase4a1/`. Before = the Phase 4A build (commit 7fb0cd3), after =
this build, same cameras and states in the real studio.

## 1. Small-eye / large-eye intersections (Priority 1)

**A correction to the brief first:** both named defects are at eye size **0.8, the slider's minimum** (the studio
range is 0.8-1.25; `params.py`'s 0.7-1.4 is the v1/v2 engine's range). So they are small-eye defects; the large end
(1.25) had the opposite problem, below. Phase 4A tested the true slider ends.

**Root cause (measured, not guessed).** MakeHuman's CC0 `eyes/{l,r}-eye-scale-{incr,decr}` targets move 386 of the
414 lid-region vertices and **none of the 80 eye-helper vertices that place the eyeball** (the `eye-trans` targets
move all 80). The eyeball's fitted radius is identical at 0.8, 1.0 and 1.25 (15.913 mm). So the "Eye size" control
resizes the opening around a fixed eyeball and pulls the lid skin radially: up to 2.25 mm *into* the eyeball at 0.8,
up to 1.9 mm *off* it at 1.25.
- ID-A at 0.8: the lower lid sinks into the eyeball, which shows through it (ID-A's own shape adds to it: brow ridge,
  eye size and spacing, cheekbone height and fullness, and the female body's femininity each move the lids toward the
  eyeball by 0.1-1.4 mm; no single term is the culprit, they add up).
- Mercy-inspired at 0.8: the same pull puts the *closed* upper lid inside the cornea bulge; the clear cornea and its
  highlight then render over the closed lid (the ghost visible in the Phase 4A sheets). Not a shader problem: the
  geometry is inside.
- At 1.25 the lids float up to 1.9 mm off the eyeball: a dark hollow at the outer corner.
- Not the cause: lid thickness (unchanged), eyeball placement or scale (unchanged and correct), blink correctives
  (the defect is in the open pose).

**Fix: eyelid fit 2** (`v3/eyelid_fit.py`). For every shape term (each control side and each identity parameter), the
skin near the eyeball loses the part of its motion that changes its distance from the eyeball surface, measured
against the eyeball's own (least-squares affine) motion under that term. Fully applied within 3 mm of the eyeball
sphere (the lids drape on it), fading to nothing at 8 mm (crease, brow, cheek; about 495 vertices per eye). Motion
along the eyeball surface is untouched: the opening's size, shape, tilt and position change exactly as before; only
the depth is corrected. The correction is linear (checked: K(-d) = -K(d), K(d/2) = K(d)/2, zero away from the eyes),
so it is one more sparse morph term per shape term and composes like everything else in the studio. The eye-size
slider still changes the eye opening; it does not shrink or hide the eyeball.

**Versioning (historical characters stay reproducible).** Eyelid fit is recorded in Character DNA as an optional
group `face_deformation: {schema: "forge.v3-face-deformation", version: 1, eyelid_fit: 1|2}`.
- DNA without it (everything saved before this phase, v1/v2 DNA included) is **fit 1** and loads exactly as before:
  the Phase 4A DNA of ID-A loads to the same geometry in the Phase 4A studio and in this one (section 6).
- New characters, presets and resets are fit 2. A legacy character shows a note and a "Use corrected eyelids"
  button in the DNA panel (an undoable edit; saving then records fit 2). Not a facial control.
- DNA hashes of files without the group are unchanged; an unknown schema, version or fit is refused, never guessed.
- The pack carries both: fit-1 data untouched, plus per term a sparse `lidfit` delta and blink correctives refitted on
  the corrected shape (`expr2`, `residual2`). Identity basis v1 and its fingerprints are unchanged (the correction
  is a separate layer). Python: `evaluate.EYELID_FIT` / `with evaluate.fit(1)`.
- The blink of every character changes slightly (corner limits, section 2), as Phase 4A's did. Stated, not silent.

**Result.** Eyeball through the open lid (18 cases, both eyes): 1,095 -> 716 skin vertices. The two named cases:
ID-A at eye size 0.8 228 -> 46 vertices (2.42 -> 1.31 mm deepest), Mercy-inspired at 0.8 127 -> 38 (1.72 -> 1.34 mm),
both now at the bare neutral's own level. In the studio (sheets `eyelids_named_before_after_yaw10/50.jpg`): ID-A's
grey eyeball patch below the lower lid, open and at half blink, is gone; Mercy-inspired's cornea and highlight no
longer show through the closed lid. Lid-inside-eye mid-blink: worst 0.87 -> 0.61 mm (ID-A eye 0.8 0.72 -> 0, Mercy
male body 0.85 -> 0).

## 2. Eyelid corners (Priority 2)

**Mechanism.** The folds sit in the outer canthus seam, where upper- and lower-lid skin meet (x 11-15 mm from the
eye centre). Blink model 2 turns lid skin about the eyeball centre by its lid-bone weight relative to the margin's
weight in its column. Near the corners the margin vertices carrying little weight are excluded from the margin
profile, so skin just above the corner turned further than the corner margin under it, and the lower lid's skin rose
past the skin above it: it overtook and folded. The folds already exist in the raw rotation (21 on Mercy-inspired at
eye size 0.8) before any relaxation; the existing untangling removed some and stalled.

**Fix (blink model 2, Phase 4A.1 limits, `v3/model.py`).**
1. *No overtaking:* along every outer-skin edge running mostly along the arc, the closed angles keep at least 40 % of
   their open spacing; violations are split between the two ends (margins stay on the closure line).
2. *Angle-space untangling:* where a turned triangle would still flip, the turn angle (not the displacement) is
   averaged over its vertices' neighbours, so the lid keeps its distance from the eyeball while it untangles.

Tried and rejected (measured on six stress shapes, exact refits): a smooth taper toward the canthus (2-5 mm bands;
no better or worse), more displacement-untangling rounds (no change), a no-overtake limit above 0.4 or one weighted
toward the moving vertex (corners stop closing: exposure 0.001-0.011). Exact refits on the six shapes: visible folds
32 -> 16 (Mercy-inspired on the male body 6 -> 0, ID-A eye 0.8 10 -> 3), every eye still closes.

**Result (studio blink, all 18 cases):** folded lid triangles at full closure 193 -> 168 (visible 138 -> 125); ID-A
improves most (eye size 0.8: 42 -> 14, female body 14 -> 10). **Not uniformly better:** 7 of 18 cases fold more than in
Phase 4A, by 1-6 triangles: five Mercy-inspired cases (e.g. eye size 0.8: 20 -> 25), ID-B on the male body (4 -> 10)
and the ID-A stress combination (13 -> 14). Two causes, both measured (exact per-character refit vs the studio's summed
correctives):
- Mercy-inspired: the exact refit itself folds more under eyelid fit 2 (neutral body 3 -> 6 per eye): with its lids
  no longer pulled into the eye, its outer canthus seam is a harder shape for the closure. The folds sit inside the
  corner crease; in the yaw-50 close-ups they are not visible as folds, but the small notch at the outer corner is
  still there (before and after).
- ID-B on the male body: the exact refit has 0 folds; the studio's sum of per-term correctives has 5 per eye. That is
  the linear corrective model's summation error, not the blink model (Phase 4A had the same kind on other cases).
Closure: every case closes except ID-B on the female body, which leaves a sliver at the outer canthus (exposure
0.0019; a few pixels in a front close-up, visible as a speck in a 3/4 close-up). The no-overtake limit causes it
(without the limit it closes); I kept the limit because it removes far more folds than this costs. Stated, not hidden.

## 3. Eyelashes (Priority 3)

**Scatter (fixed).** A lash turns with the surface normal at its root. Phase 4A used the root triangle's own corner
normals; neighbouring lashes on differently sheared triangles turned by different amounts and scattered. Now the root
normals are averaged over neighbouring strands of the same lid (Gaussian, sigma 1.5 mm, within 4 mm; the weights are
baked into the pack and the studio uses the same ones). Closed-lash scatter (95th percentile elevation difference to
neighbours within 2 mm) about halves in every case; penetration is unchanged at every weight (section 4 table).

**Upright corner lashes (not fixed; root cause found).** At full closure about 40 % of the upper lashes, the ones
within 3-4 mm of each canthus, keep their open, curled-up angle while their neighbours drape. Cause: blink model 2
barely turns the canthus skin (the corner stays put), so the surface under those lashes does not rotate. Three
direct fixes were built, measured and rejected:
- turning closed upper lashes down to at most 20 or 10 degrees above horizontal: no upright lashes left, but at the
  canthi the turned lash's base enters the lid margin under its root, from blink weight 0.25 on: penetrating strands
  per eye rose from 3 to 10-11 (ID-A, Mercy-inspired);
- the same, turned only as far as every lash point stays clear of the skin (closed and along the morph path): upright
  strands fell only ~13 % and half-turned strands made neighbours scatter again (p95 9.6 -> 13.3 deg);
- tipping blocked lashes sideways (outward) instead: blocked by the same skin, no change.
The proportionate fix is in the blink model, not the lashes: let the tarsus turn at the canthi (next recommendation).

**Result:** closed-lash scatter falls in all 18 cases, by 5 % (ID-A on the female body, whose scatter is mostly the
corner/middle jump of the upright corner lashes) to 62 % (Mercy-inspired on the neutral body); isolated on the same
fit-2 shapes. Lash penetration: worst case 4 strands before and after; in single cases the smoothed turn moves the
count by -1 to +2 (Mercy-inspired on the female body: 0 -> 2 strands more than 0.15 mm behind the skin, at the
closed end only). Upright closed upper lashes: about 77 of ~203 per character before and after (unchanged, as
explained). The studio and GLB use the same smoothed lashes (section 5).

## 4. Measurements: 18-case stress matrix, both eyes, blink 0 / 0.25 / 0.5 / 0.75 / 1

`tools/v3_phase4a1.py` (`matrix_before.json` = every Phase 4A.1 switch off, i.e. Phase 4A; `matrix_after.json`).
Cases: the four identities on the female, male and neutral body presets, ID-A and Mercy-inspired at the eye-size
slider ends (0.8, 1.25), and two identity/control stress combinations. Every case is the studio's linear blink
(summed correctives + preset residual), reproduced in Python; section 5 repeats it on the studio's own geometry.

New metrics (`v3/blink_quality.py`): *eyeball through the open lid* = outer lid-skin vertices inside the eyeball or
cornea meshes in the open pose (exact distance to the eye's own triangles), both eyes. The bare neutral itself has
46 (23 per eye: 10 upper, 13 lower; up to 1.15 mm): its lid margins rest on the cornea. Fit 2 brings every character
to about that baseline, so a character whose lids floated off the eyeball (ID-B, eye size 1.25) now *rises* to it;
that is the lids touching the eye again, not a new intersection. *Closed lash scatter* and *upright closed upper lashes* (> 20 degrees) as above.

| Case | Eyeball through open lid (vertices / deepest mm) | Folded lid triangles closed (visible + hidden) | Visible folds, worst weight (per eye) | Exposure closed | Lid inside eye mid-blink (mm) | Lash strands through skin, worst weight | Closed lash scatter p95 (deg) | Upright closed upper lashes | Smoothness p99 |
|---|---|---|---|---|---|---|---|---|---|
| neutral / female body | 56 / 1.02 → **46 / 0.76** | 2 + 0 → **0 + 0** | 1 → **0** | 0.0000 → 0.0000 | 0.46 → **0.36** | 2 → **2** | 13.1 → **7.7** | 79 → 81 | 2.44 → 2.13 |
| ID-A / female body | 118 / 1.57 → **44 / 1.00** | 5 + 9 → **0 + 10** | 3 → **0** | 0.0000 → 0.0000 | 0.46 → **0.53** | 3 → **2** | 14.6 → **11.7** | 77 → 75 | 2.42 → 1.87 |
| ID-B / female body | 26 / 0.84 → **48 / 0.78** | 2 + 0 → **1 + 0** | 1 → **1** | 0.0000 → 0.0019 | 0.00 → **0.47** | 1 → **1** | 12.7 → **8.8** | 77 → 82 | 2.21 → 2.39 |
| MERCY-INSPIRED / female body | 30 / 0.93 → **36 / 0.82** | 9 + 0 → **10 + 0** | 5 → **5** | 0.0000 → 0.0000 | 0.00 → **0.00** | 2 → **2** | 13.5 → **6.7** | 93 → 91 | 2.23 → 2.30 |
| neutral / male body | 42 / 1.63 → **40 / 1.47** | 2 + 2 → **4 + 0** | 1 → **2** | 0.0000 → 0.0000 | 0.29 → **0.61** | 2 → **3** | 12.5 → **6.2** | 78 → 66 | 1.58 → 1.83 |
| ID-A / male body | 80 / 2.08 → **36 / 1.58** | 4 + 8 → **4 + 6** | 2 → **2** | 0.0000 → 0.0000 | 0.81 → **0.60** | 3 → **2** | 11.7 → **8.4** | 54 → 52 | 1.73 → 1.72 |
| ID-B / male body | 32 / 1.31 → **46 / 1.34** | 4 + 0 → **10 + 0** | 2 → **5** | 0.0000 → 0.0000 | 0.00 → **0.00** | 3 → **3** | 11.7 → **7.1** | 78 → 68 | 1.60 → 1.98 |
| MERCY-INSPIRED / male body | 30 / 1.61 → **40 / 1.56** | 10 + 0 → **12 + 0** | 5 → **6** | 0.0000 → 0.0000 | 0.85 → **0.00** | 4 → **3** | 11.5 → **8.4** | 79 → 73 | 1.42 → 2.01 |
| neutral / neutral body | 46 / 1.15 → **46 / 1.15** | 2 + 0 → **0 + 0** | 1 → **0** | 0.0000 → 0.0000 | 0.00 → **0.00** | 0 → **1** | 12.8 → **5.3** | 70 → 74 | 2.11 → 2.15 |
| ID-A / neutral body | 120 / 1.68 → **42 / 1.35** | 4 + 10 → **2 + 10** | 2 → **1** | 0.0000 → 0.0000 | 0.10 → **0.00** | 1 → **1** | 10.4 → **6.8** | 70 → 74 | 2.13 → 1.84 |
| ID-B / neutral body | 26 / 0.81 → **52 / 0.99** | 4 + 0 → **0 + 0** | 2 → **0** | 0.0000 → 0.0000 | 0.00 → **0.00** | 2 → **1** | 11.0 → **5.2** | 71 → 72 | 2.02 → 2.26 |
| MERCY-INSPIRED / neutral body | 18 / 1.17 → **38 / 1.28** | 8 + 0 → **12 + 0** | 4 → **6** | 0.0000 → 0.0000 | 0.00 → **0.00** | 3 → **2** | 12.5 → **5.7** | 77 → 80 | 1.87 → 1.96 |
| ID-A / female body / eye size 0.8 | 228 / 2.42 → **46 / 1.31** | 26 + 16 → **10 + 4** | 13 → **5** | 0.0000 → 0.0000 | 0.72 → **0.00** | 1 → **1** | 20.5 → **12.6** | 82 → 85 | 2.16 → 1.62 |
| ID-A / female body / eye size 1.25 | 40 / 1.04 → **30 / 0.70** | 12 + 4 → **6 + 7** | 7 → **3** | 0.0000 → 0.0000 | 0.87 → **0.61** | 3 → **4** | 12.2 → **9.1** | 77 → 79 | 2.37 → 2.06 |
| MERCY-INSPIRED / female body / eye size 0.8 | 127 / 1.72 → **38 / 1.34** | 20 + 0 → **25 + 0** | 10 → **13** | 0.0000 → 0.0000 | 0.23 → **0.00** | 1 → **2** | 19.0 → **11.1** | 91 → 87 | 1.84 → 1.92 |
| MERCY-INSPIRED / female body / eye size 1.25 | 8 / 0.44 → **16 / 0.67** | 9 + 0 → **13 + 0** | 6 → **8** | 0.0000 → 0.0000 | 0.00 → **0.00** | 3 → **3** | 12.8 → **6.3** | 93 → 94 | 2.02 → 2.36 |
| ID-A / male, head 1.15, jaw 1.3 | 32 / 1.92 → **44 / 1.57** | 7 + 6 → **8 + 6** | 4 → **4** | 0.0000 → 0.0000 | 0.39 → **0.61** | 1 → **3** | 12.9 → **6.9** | 67 → 67 | 1.83 → 1.70 |
| Mercy / small head 0.9, face length 1.2 | 36 / 0.86 → **28 / 0.63** | 8 + 0 → **8 + 0** | 5 → **4** | 0.0000 → 0.0000 | 0.00 → **0.00** | 2 → **2** | 15.7 → **8.1** | 89 → 90 | 2.12 → 2.15 |
| **All 18 cases** | 1095 → **716** vertices | 193 → **168** (visible 138 → 125) | | | | | | | |

Reading the table honestly:
- **Fixed:** eyeball through the open lid on the cases that had it (ID-A on all three bodies and at both eye-size ends:
  80-228 -> 30-46 vertices; Mercy-inspired at eye size 0.8: 127 -> 38);
  lid inside the eye mid-blink (worst 0.87 -> 0.61 mm); lash scatter in every case; folds on the ID-A cases.
- **Rises that are not defects:** "eyeball through open lid" rises toward ~40-50 on cases that were below the
  neutral's own baseline (ID-B, Mercy-inspired at 1.25): their lids had floated off the eyeball and now rest on it
  like the neutral's (also the ID-A stress combination, 32 -> 44). Deepest stays within the neutral's range on each
  body (up to 1.58 mm on the male body, whose own neutral is 1.47-1.63).
- **Real regressions (small):** more folds on 7 cases (1-6 triangles; Mercy-inspired and ID-B on the male body, see
  section 2), ID-B female closure 0 -> 0.0019, mid-blink lid-in-eye up to 0.61 mm on three cases that had 0-0.39,
  lash penetration +1 or +2 strands on three cases (worst case still 4). Smoothness p99 worst 2.44 -> 2.39, mixed per
  case. Symmetry: L/R exposure difference at most 0.001.
- **Unchanged:** upright corner lashes (section 3).
- Return to neutral in the studio: blink 1 then 0 restores body and lashes exactly (0 m), before and after.

## 5. Studio and GLB

Studio geometry dumped at blink 0 / 0.25 / 0.5 / 0.75 / 1 for seven characters (`tools/studio_v3_eyelid.mjs --dump`,
`phase4a1_evidence.json`):
- **Studio vs independent Python reference:** body at most 0.22 mm at every weight (float32 pack and quantised
  deltas). Lashes at most 3.9 mm at strand tips at full blink (see remaining defects 5).
- **Quality on the studio's own geometry** (not the Python reproduction): every character closes (ID-B 0.0019,
  above); visible folds closed: Neutral 0, ID-A 2, ID-B 0, Mercy-inspired 10, ID-A eye 0.8 12, Mercy-inspired eye 0.8 20,
  ID-A stress 10; lid inside eye mid-blink at most 0.60 mm; lash strands through skin at most 2.
- **Return to neutral:** blink 1 then 0 restores body and lashes exactly (0 m).
- **Exported GLBs** (this build, presets ID-A, ID-B, Mercy-inspired, eyelid fit 2; `regression/glb_manifest.json`,
  `regression/phase3d_report.json`; the GLBs are not committed): 12,186,772 / 12,186,728 / 12,187,104 bytes (Phase
  4A: 12,186,404 / 12,186,380 / 12,186,532: +0.0003 %, no size increase that matters). Valid glTF, 62 joints, 8 morph
  targets, 7 clips; independent skinning check passes. **GLB vs studio: 0.0001 mm.** GLB vs Python reference: at most
  0.22 mm at blink 0 / 0.5 / 1. Played by the independent loader through the walk clip with the blink morph: frames
  finite, head moves (y 1.518 -> 1.483 -> 1.498 m at frames 0 / 10 / 20), lids close on the moving head
  (`glb_walk_blink_before_after.jpg`, Phase 4A export vs this one; clothed, rendered from the files only).
- **Responsiveness (software rendering, not representative):** first blink after a shape change 0.3 s in the studio
  page, then 0.01-0.06 s per blink-slider evaluation; boot about 1-2.6 s from a warm server.
- Sheets: `eyelids_named_before_after_yaw10/50.jpg` (the two eye-size-0.8 defects and the stress combination: open,
  half and full blink, before and after), `eyelids_presets_before_after_yaw10/50.jpg` (Neutral, ID-A, ID-B,
  Mercy-inspired). Hair is bald in the close-ups (styling only; it does not touch the lids).

## 6. Historical DNA and regression

**Historical DNA** (`phase4a1_evidence.json`, the Phase 4A ID-A DNA, saved before this phase):
- loads as eyelid fit 1, with the note "Saved before the eyelid fit: shown exactly as saved";
- **identical geometry to the Phase 4A studio: 0.0 m** (max body vertex difference);
- "Use corrected eyelids" changes it by up to 1.78 mm (the lids), then matches the Python fit-2 reference to 0.17 mm;
  undo restores fit 1, redo fit 2; the saved DNA carries `face_deformation.eyelid_fit = 2`, and save -> reload keeps
  fit 2 with identical geometry (0.0 mm).
- Python: fit 1 reproduces the Phase 4A shape for every identity preset to 1e-12 m (test); DNA hashes of files
  without the group are unchanged; unknown schema, version or fit is refused.

**Studio regression** (`tools/studio_v3_identity.mjs` against this build, legacy comparison against the Phase 4A
build; `regression/studio_checks.json`): **20/20 pass**: boot, Identity tab with 36 sliders, four presets editable,
strand roots on the skin for every identity, lashes ride the blink (4.3-5.1 mm), DNA identity group, save -> reload
-> load (4.99e-5 m, 4-decimal DNA precision), re-save identical, v3 DNA without identity loads neutral, invalid
identity refused, **legacy v3 DNA identical to the older studio (0.0 m)**, legacy character offers and applies the
corrected eyelids, three GLB exports, no page errors. (A first run reported the legacy check as failing at 1.2 mm:
the test built its "legacy" file from a new save, which now carries the fit-2 group. A real legacy file has no group;
the test now strips it. Recorded here because it was a test bug, not a pass by redefinition.)

**v2 Character Studio smoke test** (`tools/studio_smoke.mjs`, the check Phase 4A skipped; run with a 10-minute
screenshot timeout under SwiftShader): **23/23 pass** (boot and render, male preset, shoulder,
height and face sliders, undo, orbit drag and zoom, public coverage enforced and garment swap, animation clip time,
live secondary physics (none from camera orbit, motion from spin, inertia, damping), GLB export (8.3 MB), DNA export
(76 traits) and exact reload, no horizontal scroll at phone width, no console errors; `v2_studio_smoke.txt`). The v2 studio shares `studio.js`; the v3-only paths (eyelid fit, lash smoothing) are
inactive on the v2 pack, as intended.

**Unit tests, whole repository** (`python3 -m unittest discover -s tests`, v1/v2/v3 character forge, arsenal,
hafted, viewer, engine and the rest): **844 tests, 840 passed, 7 skipped, and 4 failures, all four in this phase's new
test file**: two DNA tests fed a v3 DNA to the v2 validator (garment names), one lid-on-eyeball check had a 1 nm
tolerance against a 1 um least-squares residue, and the lash test asserted "no extra penetration", which is false
(Mercy-inspired: +2 strands; now stated in section 3 and asserted as the Phase 4A worst-case bound of 4). Fixed;
the file then passed 11/11, and the v3, studio and DNA suites (blink, eyelid fit, identity, identity DNA, v3, studio, DNA/physics: 88 tests) were re-run after the fixes: **OK**. Every pre-existing test passed in
the full run. 53 controls and 36 identity parameters: covered by the v3 pack tests (every control end's blink
corrective closes, fit 1 and fit 2) and the identity tests.

## 7. Hardware verification

**Not verified on hardware.** This environment has no GPU (no `/dev/dri`, no `nvidia-smi`); every studio run here
is Chromium with SwiftShader (software WebGL). Nothing in this report is a hardware result. To test on your tower:

1. `git fetch origin claude/gifted-galileo-pwlplk && git checkout claude/gifted-galileo-pwlplk`
2. `python3 -m forge_character_forge studio --port 8799`, then open `http://127.0.0.1:8799/?gen=3` in Chrome or Edge.
   In the address bar `chrome://gpu` should show "WebGL2: Hardware accelerated".
3. Manual pass (two minutes): orbit with the mouse, drag an Identity slider (e.g. Nose length), move Expressions >
   blink, play Walk with blink, set Hair to "shoulder", Export GLB. All of it should feel immediate; note anything
   that stutters.
4. Measured pass (needs Node and `npm i playwright` once; no browser download if you pass `--channel chrome`):
   `node tools/studio_v3_gpu_bench.mjs http://127.0.0.1:8799/ gpu_bench --channel chrome --headed`
   It prints the WebGL renderer string first (if it says SwiftShader, llvmpipe or Software, the run is not a hardware
   result) and writes `gpu_bench/gpu_bench.json`: load time, orbit frame times, identity-slider latency, the first
   blink after a shape change (it builds the lash contact) and steady blink/walk frame times, shoulder-hair frame
   times, and GLB export time and size. Send me that file.

For scale, the same script here under SwiftShader: renderer "ANGLE (... SwiftShader driver)", flagged as software; orbit / identity slider / blink / walk + blink / shoulder
hair all about 0.85-0.95 s per frame (median, 4 shared CPU cores, another browser test running), first blink after a
shape change 1.4 s, GLB export 24 s, 12.2 MB (`gpu_bench_swiftshader.json`). These prove the script, not performance.

## 8. Repository size and evidence storage

**What the branch carries now** (every blob reachable from `claude/gifted-galileo-pwlplk`, uncompressed): 290 MB in
1,003 blobs, of which **GLB 115 MB** (23 files; the character milestones alone: Phase 2, 3D and 4A exports at
12.2 MB each, plus three 8-10 MB v2 demo GLBs), **PNG 86 MB** (248 versions, mostly evidence sheets and per-shot
screenshots), **studio packs 74 MB** (9 versions: the v2 pack 3 x 14.5 MB, the v3 pack 6 x 1.3-7.0 MB, one per
re-bake that was committed). Source, tests and docs are under 5 MB. GLBs and PNGs barely compress, so a clone pays for
nearly all of it, forever: deleting a file later does not shrink history.

**This phase (applied):** no GLB committed. The three regression GLBs are built and checked locally, and only their
sha256, size and validation results are committed (`regression/glb_manifest.json`). Per-shot PNGs, geometry dumps and
playback frames are git-ignored (`v3_phase4a1/.gitignore`); the before/after sheets are committed as JPEG (about a
tenth of the PNG size). The v3 pack is committed once, with the final commit (it is what the studio runs from a
checkout), not at every checkpoint. Nothing historical was deleted and history was not rewritten.

**Recommendation for future phases:**
1. Keep in git: source, tests, reports, metric JSON, provenance, GLB/pack manifests (sha256), JPEG sheets, and the
   studio packs at milestone commits only.
2. Put large regenerable evidence (exported GLBs, full-resolution sheets, per-shot screenshots, dumps) in a
   **GitHub Release per milestone** (e.g. `forge-v3-phase4a1-evidence`), zipped, with the sha256 manifest in the
   repo pointing at it. Free, versioned, outside the clone, and anyone can re-download exactly what a report cites.
3. Git LFS is the other option (`*.glb`, `*.bin`), but LFS storage and bandwidth beyond the account's free quota
   are billed (check the current quota on your plan; this project adds roughly 40-50 MB per phase if every GLB and
   pack is kept), and every clone then needs LFS. Not set up: it may incur charges, so it is your call.
4. Shrinking the existing history (e.g. `git filter-repo` to drop the old GLBs) needs a force-push and your explicit
   approval; not done.

## 9. Remaining defects

1. **Upright corner lashes** at full closure (~40 % of upper lashes, those within 3-4 mm of the canthi). Root cause
   identified (the canthus skin does not turn in blink model 2); three lash-side fixes measured and rejected.
2. **Corner folds:** 168 folded lid triangles remain over 18 cases (125 visible, 1-13 per eye at the worst weight),
   mostly in the outer canthus crease; 7 cases fold slightly more than in Phase 4A (Mercy-inspired; ID-B male).
3. **Summed correctives:** the studio's linear blink (per-term correctives summed) differs from an exact refit for
   combined body + identity shapes (ID-B male: 5 folds per eye summed, 0 exact).
4. **ID-B on the female body:** a 0.0019 exposure sliver at the outer canthus when fully closed.
5. **Lash parity, Python vs studio:** up to 3.9 mm at strand tips at full blink (body 0.22 mm). Two independent
   implementations (JS and Python) of the lash turn and contact on bodies that differ by 0.2 mm; the amplification
   along a 10 mm strand is the cause. The studio and the GLB agree to 0.0001 mm, so preview = export.
6. **Legacy characters in a session:** a character loaded from old DNA keeps eyelid fit 1 through later edits and
   preset changes in that session until "Use corrected eyelids" is pressed (the note stays visible). By design (no
   silent change), but easy to miss.
7. **No hardware GPU verification** (section 7).
8. Every character's blink changed slightly (corner limits, lash smoothing); open geometry of saved characters did
   not.

## 10. Next milestone recommendation

**Phase 4A.2 (recommended before 4B; bounded, no new controls): canthus closure.**
1. Let the tarsus turn at the canthi in blink model 2: the lid skin at the corners turns about the margin tangent as
   the eye closes, instead of staying put. This is the root cause of both the upright corner lashes and most of the
   remaining corner folds, and it should let the no-overtake limit (and its ID-B sliver) go.
2. Body-preset blink residuals (like the identity-preset residuals): fit the studio's summed blink to an exact refit
   for each body preset x identity preset, removing the summation folds (ID-B male).
3. Run `tools/studio_v3_gpu_bench.mjs` on your tower first, so 4A.2 and 4B start from real hardware numbers.

Only then 4B (expressions): every expression will reuse this lid closure and the lash path, so their defects would
multiply.

## Reproduce
```
python3 -c "from forge_character_forge.v3.bake import bake; bake('examples/character_forge_aaa/studio/studio_pack_v3.bin')"
python3 tools/v3_phase4a1.py before && python3 tools/v3_phase4a1.py after && python3 tools/v3_phase4a1_table.py
python3 -m forge_character_forge studio --port 8799 &        # and the Phase 4A build (7fb0cd3) on 8798
L=examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.dna.json
node tools/studio_v3_eyelid.mjs http://127.0.0.1:8798/ /tmp/before before --dump --legacy-dna $L   # then copy /tmp/before/shots
node tools/studio_v3_eyelid.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_phase4a1 after --dump --legacy-dna $L
node tools/studio_v3_identity.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_phase4a1/regression --legacy-url http://127.0.0.1:8798/
python3 tools/v3_phase3d.py examples/character_forge_aaa/humanity/v3_phase4a1/regression
python3 tools/v3_phase4a1_evidence.py /tmp/before/dumps
node tools/studio_smoke.mjs http://127.0.0.1:8799/ /tmp/v2_smoke                                     # v2 studio
python3 -m unittest discover -s tests
```
