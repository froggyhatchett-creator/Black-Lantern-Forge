# Can the MakeHuman topology support different, recognizable characters? (identity_proof.py)

Run: about 33 s, 16 more CC0 targets (provenance in `PROVENANCE.json`). Evidence in `out_identity/`.

## Measured
| Test | Result |
|---|---|
| Five adults from CC0 targets only: default female, stylized adult (Mercy direction), athletic female, heavy male, lean oval-faced female | Built; head triangle quality fine (1st-percentile minimum angle 6.9–7.8°, at most 4 flips of 3,702) |
| Face diversity (mean head/neck vertex distance, eye-aligned) | Female variants differ from each other by 0–2.8 mm; male vs female 5.2–5.7 mm |
| Stress (stylized face targets at 1×, 2×, 3×) | Flips: 0, 1, 11 of 3,702; **visually grotesque from 2×** (creased sockets, collapsing nose) |
| REF-001 vs the stylized variant (`ref001_vs_stylized.png`) | **No resemblance** |

## Findings
1. **The topology is not the limit.** Quads with eye and mouth loops accept arbitrary per-vertex deformation, and moderate
   extrapolation stays geometrically sound. Any shape we can author, this mesh can carry.
2. **The MakeHuman target library is the limit.** Its targets model realistic variation around the MakeHuman average
   face. Stacking them gives one "family": the female variants are nearly indistinguishable in the face. Using
   targets alone would make every character look like MakeHuman, which is exactly what must not happen.
3. **Extrapolating realistic targets is not stylization.** Coherent stylized faces need shape changes designed together
   (eye aperture shape and lid line, nose reduction, jaw and chin line), not local targets pushed past their range.
   Triangle metrics (flips, angles) **do not detect** the visual breakdown; visual review stays the gate.
4. **Identity lives mostly outside body geometry.** For REF-001 the recognizable features are hair (silver with a purple
   streak, volume over one eye), eye shape and expression (narrow almond, half-lidded, heavy lashes and liner, violet
   iris), makeup, ear gauges, piercings, headphones, then the small nose, small full lips and V-jaw. Body targets touch
   only the last group.

## Consequences for any integration (to review before proposing it)
- MakeHuman should be the **topology, rig and anatomy foundation**, with its targets as one variation basis among others.
  Each character's identity needs a **Forge-owned identity layer** on top:
  - landmark-driven warps on the MakeHuman topology (Forge v2 already has a face RBF warp to build on);
  - authored, coherent stylization shape spaces (realistic to stylized), owned by Forge, not extrapolated MakeHuman targets;
  - independent material, makeup, hair, clothing and accessory layers. The current hair and garment systems fall short
    of REF-001 (no strand-cluster hair, no ear gauges, headphones or piercings).
- **Provenance per feature** stays mandatory: observed from the reference, inferred, or unsupported. A default may not
  stand in for an unsupported feature while a reconstruction claims fidelity.
- **Non-humanoid and anthropomorphic body plans** (REF-002 Gothic Centaur, REF-003 Tavern Cowgirl) cannot come from hm08.
  They need a template registry with per-template rigs, which is out of scope for this milestone. The generator
  versioning and the DNA layers (anatomy / styling / wardrobe) already separate what such templates would swap.

## Limitations of this experiment
Targets only, no sculpting or warps; no hair, materials, makeup or accessories; neutral expression (REF-001 is smiling
and half-lidded); one camera; about 50 of roughly 1,000 MakeHuman targets downloaded. The default (A) and athletic
(C) faces are identical because C changes the body only.

# Facial identity warp (identity_warp.py, owner-approved), result: stopped, minor differences plus one defect

Run: 20.8 s, no downloads. Evidence: `out_warp/identity_warp.png`, `out_warp/warp_report.json`.

- **Method:** 22 surface landmarks (11 mirrored pairs and midline points) located geometrically on the MakeHuman female
  head, plus 13 artist-guided offsets toward REF-001. The offsets are my estimates read from the art, not measurements.
  Gaussian RBF (sigma 16 mm), 12 zero anchors, neck falloff. Topology and UVs unchanged.
- **Geometry:** every landmark reached its requested offset (for example jaw angle 6.96 mm, outer eye corner 3.94 mm,
  nose tip 2.77 mm). 0 flipped triangles of 8,470; 1st-percentile minimum angle 6.53°; maximum area change 1.39×.
- **Visible result:** the eyes changed clearly (heavier upper lid, longer and slightly tilted almond shape), a real
  step toward REF-001's eye structure. Nose, mouth, cheekbone and jaw changes are barely perceptible; mean head
  displacement is only 0.64 mm (p95 2.74 mm). **Overall: not a visibly different person.**
- **Defect:** the blink regressed from 4.7% visible eye (untouched female) to 18.5% (warped); pupils show through a gap.
  The lid bones' fixed closing angle was calibrated for the original lid shape. 38 triangles flip during the warped
  blink (maximum area ratio 7.15), so the lids crumple slightly.

**Why it fell short**
1. The offsets were too conservative. REF-001's stylization is not a few millimetres. It changes proportions: a much
   smaller nose and mouth, a strongly tapered jaw, a different eye aperture shape. That needs roughly 5–15 mm,
   region-wide changes.
2. Sparse points with a 16 mm kernel make local dents, not region-wide shape changes. A coherent identity layer needs
   region transforms (scale, rotate and taper whole feature regions) or dense correspondences, with the point warp
   only for refinement.
3. Moving the eye region requires **re-fitting the rig and pose units** (lid pivot and closing angle) per character.
   An identity layer that ignores animation breaks the blink: the identity layer and the rig adaptation are one
   system, not two.
4. Hair, makeup, lashes and liner, iris colour, accessories and the smiling half-lidded expression carry most of
   REF-001's recognizability and were deliberately excluded. Geometry alone cannot yield likeness here.

# Final facial identity experiment: coherent regional transforms + eyelid refit (identity_regions.py)

Runs: v1 24.4 s (falloff bug; kept in `out_regions_v1_falloff_bug/`), v2 about 25 s (plateau falloff, same identity
values). Evidence: `out_regions/identity_regions.png`, `out_regions/eyelids.png`, `out_regions/regions_report.json`.

| Measure | v1 | v2 |
|---|---|---|
| Head displacement mean / p95 / max (mm) | 0.84 / 2.98 / 14.5 | 1.28 / 3.96 / 14.5 |
| Nose tip / chin side / jaw angle / outer eye corner (mm) | 2.4 / 2.8 / 8.3 / 1.5 | 4.6 / 4.6 / 8.3 / 2.3 |
| Nostril wing / mouth corner landmark (mm) | 0.01 / 0.31 | 0.06 / 0.31 (landmark finder places these outside the feature regions) |
| Flipped triangles (of 8,470) / p1 min angle / max area change | 0 / 6.91° / 1.57 | 0 / 6.62° / 2.16 |
| Mean Laplacian (surface noise), original 1.360 mm | 1.363 | 1.380 |

**Eyelids (v2, front-view eyeball exposure relative to open):**

| Pose | original | modified |
|---|---|---|
| half-lidded (0.45) | 0.465 | 0.461 |
| 50 % blink | 0.411 | 0.391 |
| closed, refit rule | 0.093 | 0.029 |
| closed, fixed 33.2° pose-unit angle | 0.047 | **0.002** |
| neutral return error | 0 mm | 0 mm |

Lid vertices within the eyeball sphere: 140 when open on both heads (an existing property of MakeHuman's lid and socket
geometry), at most +12 during motion, identical on both. Flips while closed: 50 (original), 60 (modified); the bone-only
MakeHuman lid crumples (area change up to 101× original, 10× modified) without corrective shapes.

**Verdict: does not meet "visibly and substantially different".** The modified head reads as the same person with edits.
Anatomy stays coherent from all angles except one new defect: **faint crease lines under the eyes** where the
eyeball-distance constraint ends (hard 1.6× eye-radius boundary). The metrics did not catch it.

**Causes**
1. The artist-guided changes (10–18 % proportional) amount to 2–5 mm on a realistic head: an edit, not a new identity.
   The strongest identity difference measured so far is MakeHuman's own female/male macro (about 5 mm mean). Distinct
   identities need many correlated changes across the whole face, not six regions.
2. Region placement from geometric landmarks is unreliable (nostril wings and mouth corners missed). MakeHuman's CC0
   detail targets define their regions exactly (the vertex set of each `nose-*` or `mouth-*` target), which gives
   data-driven region masks instead of guessed landmarks.
3. The eye constraint needs a smooth blend, not a hard cutoff (the crease defect).
4. The eyelid-refit rule (upper-lid midpoint meets lower lid) is worse than the fixed pose-unit angle. A correct refit
   should minimize exposure under a penetration limit. Preserving the lids on the eyeball sphere is what made the
   blink work (0.2 % exposure vs 18.5 % in the point-warp experiment).
