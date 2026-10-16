# Generator v3, Phase 4A: facial deformation and blink quality (stopped for visual review)

Status: **corrective milestone complete; stopped for review.** No new features: no new sliders, expressions, hair,
wardrobe, reconstruction or creature work. The 36 identity parameters, 53 controls, Character DNA semantics and
v1/v2 are unchanged. What changed is how the eyelids close (blink model 2), how lashes behave when they meet the
lid (lash contact), and two studio/GLB mismatches found on the way.

Evidence: `examples/character_forge_aaa/humanity/v3_phase4a/`.

## 1. What was actually wrong (investigated before fixing)
Measured on the worst case first (ID-A on the female body preset, 75 folded lid triangles at full blink):

1. **One global closing angle cannot close an almond opening.** The Phase 1-3 blink rotated each lid by a single
   factor on MakeHuman's pose unit, picked from a coarse grid (1.0-1.5 x, lower-lid raise 0 or 0.5) by front-view
   exposure. The middle of the opening closes first; to close the corners the grid picked a bigger factor, so the
   middle overshot past the lower lid and folded it. On ID-A + female the raw rotation at the chosen factor drooped
   the upper lid far below the lower lid, and the relaxation passes then pulled it back, leaving a gap (exposure
   plateaued while the factor rose).
2. **The correctives summed badly.** The studio's blink is linear: neutral blink + one corrective per changed
   control and identity parameter (+ a preset residual). Each corrective was the difference between two separately
   *grid-fitted* blinks, so it carried jumps in the closing factor; summing ~30 of them compounded the overshoot.
   Even an exact refit of the full character folded 51 triangles; the summed blink folded 75.
3. **The hidden lining was dragged along.** hm08's skin is closed: past the lid margins it wraps back over the
   eyeball (the fornix). On combined shapes (ID-A + female body) that lining is thin and tightly packed, and
   MakeHuman's lower-lid weights turned neighbouring lining vertices by different amounts, so they sheared and
   flipped (most of ID-A's 45 hidden folds).
4. **The margin data was noisy.** The lid-margin vertex lists (shared with the lash generator) contained two
   zero-weight strays (at -6 and -41 degrees) and meaningless corner angles; interpolating through them made the
   closure line zigzag (Mercy-inspired's step and 50 folds).
5. **Morph targets move in straight lines, lids turn on arcs.** At half blink the straight path of the lid edge
   cut up to 1.4 mm into the cornea bulge, so the eye showed through the lid edge mid-blink (the grey sliver at
   ID-A's outer corner).
6. **Lashes are rigid in their root triangle's frame.** Closing turned the upper lashes into the lower lid
   (up to ~1.7 mm deep), and mid-blink a few cut through the lid (the reported ID-A defect).
7. **Two studio/GLB mismatches.** (a) The studio re-anchored lashes on the deformed lid every frame while the GLB
   exports a linear lash morph: they differed by up to 5.2 mm at half blink. (b) The studio scales the blink with
   the exact-height scaling but the GLB's blink targets were exported unscaled (~5 % too large on a 1.66 m character;
   the 0.31 mm GLB-vs-reference difference reported in Phase 3D).

What it was **not**: the lid-bone pivots stay within 1.5 mm of the eyeball centre for every identity; joint
transforms and skin weights are unchanged and fine.

## 2. The correction
**Blink model 2** (`v3/model.py` `blink_closed`; `BLINK_MODEL = 2`):
- *Per-column closure.* Lid vertices turn about the eyeball centre (lid skin keeps its distance from the eye).
  For every column across the opening, the upper margin turns down and the lower margin up until they meet 30 % of
  the way up from the lower margin (`CLOSE_AT`, the upper lid does most of the travel), with a small overlap
  (`CLOSE_OVERLAP` 0.03 rad) because lid edges are thick. Every other lid vertex turns by its MakeHuman lid-bone
  weight relative to the margin's weight in its column, so MakeHuman's falloff toward the crease and cheek is kept.
  Continuous in the shape: no grid choice, so correctives change smoothly and sum well.
- *Anchored fornix.* Lining within 1.2 mm of the eyeball, more than 3-15 degrees past a margin, stays on the
  eyeball (as in a real eye); only the lining near the margin travels with the lid.
- *Clean margins.* Profiles use only margin vertices with real lid weight; the turn at the canthi is half the
  nearest sample's (`CANTHUS_TURN`; zero left gaps at the corners of wide-set eyes, full folded them); the margin
  vertices are held on the closure line while the displacement is relaxed.
- *Chord clearance.* Where a lid vertex's straight path (or closed position) would come closer to the eye than
  when open, its closed position is pushed out from the eyeball centre just enough, then smoothed: every
  in-between weight stays outside the eye. The closed lid rides slightly out over the cornea, as a real lid does.

The existing keep-off-cornea and untangling passes run as before. The pack format is unchanged: neutral blink,
per-control and per-identity correctives (both ends) and preset residuals, all rebuilt from model 2
(`v3/evaluate.py`; caches keyed by the model's parameters).

**Lashes in an expression** (`v3/lash_contact.py`; studio `lashTurn` and `lashContact`, same rules):
- *Turn with the lid surface.* A lash keeps its root on its triangle and turns with the smoothed surface normal at
  the root (vertex normals of the root triangle's corners) instead of being rigid in that one triangle's frame:
  model 2 holds the margin on the closure line while the lid around it relaxes, which shears single margin
  triangles, and lashes rigid in those frames stood upright on the closed lid. Two alternatives were tried and
  rejected after looking at them: turning the lid-bone-weighted root vertices rigidly (the middle lashes draped, the
  corners still stood up, and lid folds jumped to 36-47) and the best-fit rotation of the surrounding outer skin
  (that skin barely turns, so every lash stayed upright).
- *Contact.* In the closed pose and along the straight morph path to it, a lash point is kept at least as far
  outside the outer lid skin as it was open (and 0.1 mm outside it), pushed along the nearest skin triangle's normal;
  the push is carried to the rest of the strand, so the lash bends. Contact acts between the lids (upper lashes rest
  on the lower lid and the reverse) and, with a 1 mm allowance, between upper lashes and the fold of their own lid.
  Pushes are capped (2.5 mm, and half the point's distance from its root). An uncapped version flung a few corner
  lashes visibly off the lid; a version acting fully on the lash's own lid pushed corner lashes upward off it; both
  were rejected after looking at them. The open pose is never changed.

**Studio/GLB parity** (`studio.js`): lashes, brows and hair follow expressions as the same linear morph the GLB
exports (from the expression-free body, with contact), blink targets are exported at the character's height scale,
and the GLB base is always the expression-free character. Contact is cached per face shape, so dragging the blink
slider stays cheap (first blink after a shape change ~0.5 s under software rendering, then ~0.1 s per frame).

**Historical characters:** DNA, shape and the open face are unchanged (a v3 DNA loads to the identical open
geometry in the Phase 3D and the Phase 4A studio: 0.0 m difference). Their *blink* changes: it is regenerated by
model 2 for every character. That is the point of this phase; it is stated here, not silent.

## 3. Measurements: 18-case stress matrix, both eyes, weights 0 / 0.25 / 0.5 / 0.75 / 1
`tools/v3_phase4a.py` (`matrix_before.json` = blink model 1 as the Phase 3D studio built it, `matrix_after.json`).
Cases: the four identities on the female, male and neutral body presets; ID-A and Mercy-inspired at the eye-size
slider ends; two identity/control combinations. Every case is the studio's linear blink (summed correctives +
residual), reproduced in Python; section 5 checks the same numbers on the studio's own geometry.

Definitions (`v3/blink_quality.py`): folds = lid triangles whose normal flips, split into the visible lid (outer
skin and margin) and the hidden lining (on or inside the eyeball sphere: never visible, still counted); exposure =
front-view visible eyeball relative to open, per eye; lid inside eye = deepest visible-lid vertex newly inside the
eyeball or cornea; lash strands = strands with a point >0.15 mm directly behind outer lid skin (exact
point-triangle distance), counting strands clear in the open pose; smoothness = 99th percentile of the lid
Laplacian relative to the open lid; symmetry = |left - right| exposure.

| Case | Folded lid triangles, closed (visible + hidden lining) | Visible folds, worst weight (per eye) | Eyeball exposure closed | Lid inside eye, worst mid-blink (mm) | Lash strands through skin, worst weight | Smoothness p99 | L/R exposure diff |
|---|---|---|---|---|---|---|---|
| neutral / female body | 11 + 2 → **2 + 0** | 6 → **1** | 0.0000 → 0.0000 | 1.02 → **0.46** | 10 → **2** | 2.23 → 2.44 | 0.0006 → 0.0009 |
| ID-A / female body | 30 + 45 → **5 + 9** | 15 → **3** | 0.0006 → 0.0000 | 0.87 → **0.46** | 16 → **3** | 2.19 → 2.42 | 0.0003 → 0.0007 |
| ID-B / female body | 10 + 0 → **2 + 0** | 5 → **1** | 0.0019 → 0.0000 | 0.00 → **0.00** | 7 → **1** | 2.09 → 2.21 | 0.0009 → 0.0000 |
| MERCY-INSPIRED / female body | 50 + 0 → **9 + 0** | 26 → **5** | 0.0015 → 0.0000 | 0.00 → **0.00** | 7 → **2** | 1.74 → 2.23 | 0.0006 → 0.0006 |
| neutral / male body | 14 + 0 → **2 + 2** | 7 → **1** | 0.0000 → 0.0000 | 1.37 → **0.29** | 4 → **2** | 1.56 → 1.58 | 0.0000 → 0.0000 |
| ID-A / male body | 14 + 16 → **4 + 8** | 7 → **2** | 0.0000 → 0.0000 | 1.24 → **0.81** | 10 → **3** | 1.67 → 1.73 | 0.0000 → 0.0000 |
| ID-B / male body | 10 + 0 → **4 + 0** | 5 → **2** | 0.0000 → 0.0000 | 0.35 → **0.00** | 5 → **3** | 1.41 → 1.60 | 0.0000 → 0.0000 |
| MERCY-INSPIRED / male body | 18 + 0 → **10 + 0** | 9 → **5** | 0.0000 → 0.0000 | 1.24 → **0.85** | 4 → **3** | 1.57 → 1.42 | 0.0000 → 0.0000 |
| neutral / neutral body | 4 + 0 → **2 + 0** | 2 → **1** | 0.0000 → 0.0000 | 1.20 → **0.00** | 4 → **0** | 1.88 → 2.11 | 0.0000 → 0.0000 |
| ID-A / neutral body | 4 + 18 → **4 + 10** | 2 → **2** | 0.0000 → 0.0000 | 1.08 → **0.10** | 10 → **1** | 2.04 → 2.13 | 0.0000 → 0.0000 |
| ID-B / neutral body | 0 + 0 → **4 + 0** | 0 → **2** | 0.0045 → 0.0000 | 1.24 → **0.00** | 3 → **2** | 1.65 → 2.02 | 0.0000 → 0.0000 |
| MERCY-INSPIRED / neutral body | 20 + 0 → **8 + 0** | 10 → **4** | 0.0000 → 0.0000 | 1.29 → **0.00** | 3 → **3** | 1.69 → 1.87 | 0.0000 → 0.0000 |
| ID-A / female body / eye size 0.8 | 94 + 26 → **26 + 16** | 47 → **13** | 0.0523 → 0.0000 | 1.05 → **0.72** | 14 → **1** | 2.21 → 2.16 | 0.0000 → 0.0000 |
| ID-A / female body / eye size 1.25 | 56 + 9 → **12 + 4** | 28 → **7** | 0.0000 → 0.0000 | 0.93 → **0.87** | 15 → **4** | 2.56 → 2.37 | 0.0016 → 0.0004 |
| MERCY-INSPIRED / female body / eye size 0.8 | 88 + 2 → **20 + 0** | 44 → **10** | 0.0024 → 0.0000 | 0.47 → **0.23** | 2 → **1** | 1.97 → 1.84 | 0.0000 → 0.0000 |
| MERCY-INSPIRED / female body / eye size 1.25 | 52 + 0 → **9 + 0** | 27 → **6** | 0.0006 → 0.0000 | 0.00 → **0.00** | 8 → **3** | 1.97 → 2.02 | 0.0008 → 0.0009 |
| ID-A / male, head 1.15, jaw 1.3 | 32 + 8 → **7 + 6** | 16 → **4** | 0.0000 → 0.0000 | 1.14 → **0.39** | 9 → **1** | 1.66 → 1.83 | 0.0004 → 0.0006 |
| Mercy / small head 0.9, face length 1.2 | 50 + 0 → **8 + 0** | 25 → **5** | 0.0034 → 0.0000 | 1.01 → **0.00** | 5 → **2** | 2.15 → 2.12 | 0.0005 → 0.0003 |
| **All 18 cases** | **683 → 193** (visible 557 → 138) | | | | | | |

Summary over all 18 cases: folded lid triangles at full blink **683 -> 193** (visible lid 557 -> 138; the remaining
visible folds are 1-13 small triangles per eye, mostly at the canthi, where the lids overlap); every case closes
(exposure 0.0000, also ID-A at eye size 0.8, which did not close before: 0.052); lid-inside-eye mid-blink at most
0.87 mm (was up to 1.37 mm); lash penetration at most 4 strands at the worst weight (was up to 16); left/right
exposure difference at most 0.0009. Return to neutral is exact (blink 1 then 0 restores body and lashes: 0 m).

## 4. Visual evidence (identical cameras, the real studio; hair style bald for the eye close-ups)
- `blink_before_after_yaw10.png`, `blink_before_after_yaw50.png`: Neutral, ID-A, ID-B, Mercy-inspired and the
  stress case (Mercy-inspired at eye size 0.8), half blink and full blink, before (Phase 3D build) and after;
- `glb_walk_blink_before_after.png`: the ID-A GLB, walk frame 10, blink 0.5 and 1, before and after, rendered from
  the exported files by the independent loader (clothed, as exported);
- `shots/after_walk10_blink0.5.png`, `shots/before_walk10_blink0.5.png`: the studio walking mid-blink.

What the sheets show (my reading; it needs your eyes, which is why this phase stops here):
- *Full blink.* Before, the closed lids of ID-A and Mercy-inspired showed a crease line and lumps where the upper
  lid overshot and folded the lower lid; ID-A at eye size 0.8 left a visible slit. After, the lids meet on one
  smooth closure line slightly below the middle of the eye, every case is closed, and the upper lashes drape on the
  lower lid instead of standing in it.
- *Half blink.* Before, the lid edge cut into the cornea at ID-A's outer corner (grey sliver) and some lashes ran
  through the lid. After, the lid edge stays outside the eye; the lashes follow the lid.
- *Still visible after:* small kinks at the outer canthus on the extreme cases (the remaining visible folds), 2-3
  lashes at the outer corner that stand more upright than their neighbours when closed, and on Mercy-inspired at
  eye size 0.8 a cornea highlight showing through the upper lid near the outer corner. That last one is also in the
  *open* pose and in the before shots: it is the eye-size slider pushing the eyeball through a thin lid, not the
  blink.
- *Walking.* The studio walk frame and the GLB walk frames close the same way as the standing pose; the head moves
  (0.043 m head travel over the clip) and the blink morph rides on top of the skinning, as it must.

## 5. Studio, saved DNA and GLB
**Studio vs independent Python reference** (studio geometry dumped by `tools/studio_v3_blink.mjs --dump`,
`phase4a_evidence.json` `parity`), max over all vertices, blink 0 / 0.5 / 1:

| Character | Body (mm) | Lashes (mm) |
|---|---|---|
| Neutral | 0.002 / 0.03 / 0.06 | 0.03 / 1.05 / 2.11 |
| ID-A | 0.09 / 0.09 / 0.15 | 0.53 / 0.97 / 1.96 |
| ID-B | 0.12 / 0.12 / 0.20 | 0.38 / 1.40 / 2.78 |
| Mercy-inspired | 0.08 / 0.09 / 0.17 | 0.70 / 0.90 / 1.78 |
| Mercy-inspired, eye 0.8 | 0.08 / 0.09 / 0.17 | 0.81 / 0.86 / 1.71 |

The body agrees to float precision plus the studio's float32 pack. The lashes do not agree exactly: the lash
contact and root turn are run independently in JS and Python on bodies that differ by ~0.1 mm, and those small
input differences are amplified along a 10 mm strand (up to 2.8 mm at a tip). That is a reference mismatch, not a
studio/GLB one: **the exported GLB matches the studio to 0.0001 mm**, lashes included, because the GLB is written
from the studio's own arrays.

**Quality measured on the studio's own geometry** (not the Python reproduction), full blink:

| Character | Folds closed (visible + hidden) | Exposure closed | Lid in eye (mm) | Lash strands through skin |
|---|---|---|---|---|
| Neutral | 2 + 0 | 0 | 0.45 | 2 |
| ID-A | 5 + 13 | 0 | 0.46 | 4 |
| ID-B | 3 + 0 | 0 | 0.00 | 2 |
| Mercy-inspired | 12 + 0 | 0 | 0.00 | 2 |
| Mercy-inspired, eye 0.8 | 26 + 0 | 0 | 0.24 | 1 |

Half-blink exposure 0.44-0.46 for all of them, left and right within 0.001: the lid travels evenly.

**Return to neutral:** blink 1 then 0 restores the studio body and lashes exactly (0 m).

**Exported GLBs** (`regression/`, exported from the studio, validated by the independent loader):
ID-A 12,186,404 bytes, ID-B 12,186,380, Mercy-inspired 12,186,532 (Phase 3D: 12,191,416 / 12,189,732 / 12,189,748:
no size increase). Each: glTF validation passes, 8 morph targets, skinning intact, GLB vs studio 0.0001 mm, GLB vs
Python reference <= 0.15 mm (was 0.31 mm in Phase 3D because of the unscaled blink targets, now fixed), exposure 0
at blink 1. Played through the walk clip with the blink morph by `tools/glb_playback.mjs`: frames render, the head
moves 0.043 m, the lids close on the moving head, garments present (public renders stay clothed).
Studio pack: 7,032,430 -> 7,032,626 bytes (+196 bytes for the lash-contact parameters).

**Save/load and regression** (`tools/studio_v3_identity.mjs` against this build, legacy check against the Phase 3D
build; `regression/studio_checks.json`): **19/19 pass**: studio boots, 36 identity sliders, four editable presets,
strand roots on the skin for every identity, lashes ride the blink (4.4-5.2 mm), DNA carries the identity group,
save -> reload -> load restores the character (4.99e-5 m, the DNA's 4-decimal trait precision), re-save gives the
same DNA, v3 DNA without identity loads neutral, an unsupported identity version is refused, **legacy v3 DNA looks
identical to the Phase 3D studio (0.0 m)**, three GLB exports, no page errors. `tools/v3_phase3d.py` re-run on the
new exports: `regression/phase3d_report.json`, `regression/glb_playback_sheet.png`.

**Cost:** first blink evaluation after a face-shape change ~0.5 s under software rendering (SwiftShader; the lash
contact), then ~0.1 s per blink-slider frame from the cache. Playback of the exported GLB costs nothing extra: it
is ordinary morph targets.

## 6. Tests
`python3 -m unittest tests.test_character_forge_v3_blink tests.test_character_forge_v3_identity
tests.test_character_forge_v3_identity_dna tests.test_character_forge_v3`: **51 tests, OK** (426 s).
- New `tests/test_character_forge_v3_blink.py` (8): neutral blink is exact model 2; ID-A + female and
  Mercy-inspired + female close with few folds; continuity (the closed lid moves at most 1.2 mm per unit of any
  identity parameter: correctives sum well); lid vertices stay on the lids; lash contact never moves the open pose,
  only helps and leaves at most 5 strands through the closed lid, at most 1 mid-blink; the pack carries
  `blink_model` 2, the contact triangles and parameters, and its neutral blink matches the Python one to 5.1e-5 m.
- The existing v3 (24), identity (9) and identity-DNA (10) tests pass unchanged; the per-control blink corrective
  test (every reshaping control end closes to exposure <= 0.005) passes on model 2 **with its threshold unchanged**.
- Not re-run this phase: the v2 studio smoke test. v1/v2 code and packs were not touched, but `studio.js` is shared;
  the v3 changes are inside v3-only paths. Treat v2 as unverified by this phase.

## 7. Remaining limitations (honest)
- **Not zero folds.** 193 folded lid triangles remain over the 18 cases (138 visible). Per eye they are 1-13
  small triangles, mostly at the canthi where the two lids overlap, plus hidden lining folds on ID-A (9-16) that are
  inside the eye socket and never visible. Eliminating the canthus folds needs a real canthus model (a tucked
  corner), which is beyond a proportionate fix here.
- **ID-B on the neutral body got slightly worse:** 0 -> 4 folded triangles (2 per eye, at the outer corner). Every
  other case improved. Small; stated, not hidden.
- **Smoothness p99 is a little worse** (p99 1.41-2.56 before, 1.42-2.44 after, worse in 12 of 18 cases): the closed lid is now one surface across
  the eye where before it was crumpled at the corners but flat in the middle. Not visible in the renders; it is a
  stricter measure of curvature, not a defect I can see.
- **ID-A at eye size 0.8** pokes the eyeball through the lower lid in the *open* pose (cheekbone_height 0.8 with
  cheek_fullness -0.8 pull the lower lid down onto a large eye). The blink now closes it, but the open pose is an
  identity-basis problem, not a blink one.
- **Mercy-inspired at eye size 0.8:** cornea highlight through the upper lid near the outer corner, open and
  closed, before and after. Same cause class: eye size vs thin lid.
- **2-3 corner lashes** per eye stand more upright than their neighbours in the closed pose, and up to 4 lash
  strands still touch through the skin by >0.15 mm at the worst weight (16 before). Not visible at normal distance;
  visible in a macro close-up.
- **Python lash reference differs from the studio by up to 2.8 mm** at strand tips (see section 5). The studio and
  the GLB agree exactly, so what you see is what you export; the Python reference is the looser check.
- **Every character's blink changed.** Open geometry and DNA are untouched; the closed eye is regenerated by model 2.
  Deliberate and stated.
- **Lid motion is still a linear morph.** Chord clearance keeps the straight path out of the eye, but the lid still
  travels in a straight line rather than an arc; at 0.25/0.75 it is clean by measurement, not by construction.
- I have not seen this in a hardware-GPU browser, only SwiftShader screenshots. Shading of the lid crease may read
  differently under real lighting.

## 8. Next recommendation
Recommendation for review, in this order (not started):
1. **Identity basis v2: protect the lower lid and eye-size clearance.** The worst remaining visible defects are in
   the open pose (eye size vs thin lids, cheek operators dragging the lower lid). Constrain the cheek operators near
   the lower-lid margin and add an eyeball/lid clearance term to eye size. This needs a new identity basis version
   (DNA stays compatible: version the basis, keep v1 reproducible).
2. **Canthus treatment** for the remaining corner folds: a small tuck of the lid corners toward the eye in the closed
   pose, fitted per character like the rest of model 2.
3. **Corner lashes:** shorten / taper the outermost 2-3 roots per lid or turn them with the canthus rather than the
   margin.
4. Then re-run the v2 smoke test on a hardware GPU and take real-lighting close-ups before any further facial work.

## Reproduce
```
python3 -c "from forge_character_forge.v3.bake import bake; bake('examples/character_forge_aaa/studio/studio_pack_v3.bin')"
python3 tools/v3_phase4a.py before --model 1 && python3 tools/v3_phase4a.py after && python3 tools/v3_phase4a_table.py
python3 -m forge_character_forge studio --port 8799 &        # and the Phase 3D build (9a6aeb3) on 8798
node tools/studio_v3_blink.mjs http://127.0.0.1:8798/ examples/character_forge_aaa/humanity/v3_phase4a before
node tools/studio_v3_blink.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_phase4a after --dump
node tools/studio_v3_identity.mjs http://127.0.0.1:8799/ examples/character_forge_aaa/humanity/v3_phase4a/regression --legacy-url http://127.0.0.1:8798/
python3 tools/v3_phase3d.py examples/character_forge_aaa/humanity/v3_phase4a/regression
python3 tools/v3_phase4a_evidence.py
python3 -m unittest tests.test_character_forge_v3_blink tests.test_character_forge_v3_identity tests.test_character_forge_v3_identity_dna tests.test_character_forge_v3
```
