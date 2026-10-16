# Generator v3, Phase 3C: Mercy-inspired stylisation proof (stopped for review)

Status: **bounded proof complete; stopped.** No DNA serialisation, studio integration (3D/3E) or other expansion.
Verdict in one line: **the Forge identity layer moves a realistic MakeHuman foundation to a clearly different,
coherent, stylised adult woman with working eyelids; it does not reach Mercy likeness**, and two visible defects remain.

## What was added
**One operator group, lid-only (`identity.py`, parameters 33-35, `LID_OPS`, `_lid_op`)**:
- `eye_aperture`: almond (+) / round (-). Upper lid turns down and lower lid up about the eyeball centre
  (0.11 / 0.07 rad at s = 1), weighted by MakeHuman's own lid-bone weights and limited to the eyelids proper
  (fading 18-30 mm from the eyeball centre);
- `eye_outer_corner`: the outer half of both lids turns up about the eyeball centre (canthal lift, independent of
  the whole-eye tilt);
- `eye_length`: the opening lengthens, mostly toward the outer corner.

These rotate lid skin about the eyeball centre (linearised, so they stay linear and composable like every identity
parameter): lid skin keeps its distance from the eyeball (tested: under 0.2 mm), and the eyeball and eye joint do not
move (tested). Nothing else was added: the nose, mouth, jaw, chin and silhouette use the Phase 3A operators.

**The character** (`identity.STYLIZED["MERCY-INSPIRED"]`): almond, larger, outer-lifted eyes; a softer brow; a smaller,
narrower, upturned nose; a smaller, higher mouth; high cheekbones over flatter cheeks; a narrow V jaw, a shorter lower
face and a pointed chin. It also sets one existing body control, `body.femininity = 1` (`STYLIZED_CONTROLS`): sex is
a body control, not identity, and identity alone on the sex-neutral base reads androgynous. The identity-only face is
rendered alongside for transparency.

**Expression stays separate:** the half-lidded look is a blink weight (0.35), not part of the identity.

## Evidence (`examples/character_forge_aaa/humanity/v3_phase3c/`)
Bald, one neutral material, identical light; every face is rigidly aligned on its eyeball-centre midpoint, so the
cameras frame each head identically (the femininity control also shortens the body).
- `stylized_sheet.png`: neutral v3 default, Mercy-inspired, identity only; front, left profile, right profile,
  three-quarter;
- `stylized_closeups.png`: larger front and 30-degree views, with REF-001 beside them (illustration, for orientation
  only);
- `stylized_eyes.png`: eye close-ups: open, half-lidded (0.35), 50 % blink, closed, for every face;
- `stylized_report.json`: every number below.

## Measurements
| | Neutral | Mercy-inspired | Identity only |
|---|---|---|---|
| Shape distance from neutral (aligned, mean / p95) | 0 | 7.85 / 16.4 mm | 3.34 / 8.8 mm |
| Displacement after alignment, mean / max | 0 | 7.96 / 23.7 mm | 3.37 / 16.0 mm |
| Flipped triangles on the head / triangles under 2 degrees | 0 / 0 | 0 / 0 | 0 / 0 |
| Max triangle area change, min angle (p1) | 1.0, 7.6 deg | 3.85, 6.7 deg | 2.51, 6.9 deg |
| Eye joint to eyeball centre | 0.72 mm | 0.35 mm | 0.22 mm |
| Eyeball exposure: open / half-lidded / 50 % / closed | 1 / 0.63 / 0.47 / 0 | 1 / 0.61 / 0.44 / 0 | 1 / 0.62 / 0.44 / 0 |
| Folded lid triangles: half-lidded / 50 % / closed | 0 / 0 / 4 | 2 / 6 / 36 | 0 / 4 / 22 |
| Blink fit (closing factor, lower-lid raise) | 1.2, 0 | 1.1, 0 | 1.0, 0 |

For scale: MakeHuman's own female variants differ by 0-2.8 mm; ID-A vs ID-B (Phase 3B) by 14.4 mm.

## Visual assessment
- **Different identity, not an edited default:** yes. At normal viewing distance the stylised head reads as a
  different adult woman: narrow V-shaped lower face, pointed chin, small upturned nose, larger almond eyes with lifted
  outer corners, high cheekbones. The profile changes too (smaller nose, shorter lower face, chin).
- **Adult, not childlike or grotesque:** yes; the skull and facial proportions stay adult.
- **Toward Mercy's structure:** almond, tilted eyes with a heavy-lidded expression state; a smaller, delicate nose;
  a smaller mouth; a tapered jaw and pointed chin; a feminine silhouette. All moved in the right direction.
- **Eyelids:** functional in all four states; lids stay on the eyeballs; the blink closes fully (0 % exposure).

**Visible defects (not fixed: stop condition against escalation)**
1. The mouth reads as a slight pout: the female macro's fuller lips plus the higher, narrower mouth make the lips
   project in three-quarter view.
2. The jaw line shows an angular kink near the jaw angle in three-quarter view and in profile (narrow jaw, strong
   taper and shortened lower face meeting there).
3. The closed lids fold more than the neutral's (36 vs 4 folded lid triangles); visible only as a slightly
   irregular closed-lid line in close-up.
4. The eyes are larger and almond, but not the illustration's very large, shaped eyes: eyelid fold, lash line and
   iris size dominate that look, and they are materials and grooming, not geometry.

## Does this prove the identity layer can support stylised adult identities?
**Yes, for structural stylisation**: proportion, silhouette, eye-opening shape, nose, mouth and jaw move far from the
MakeHuman average with no flipped triangles, intact sockets and working lids, using Forge operators plus one existing
body control. It is **not yet** proof of fine-form stylisation.

## Blockers to full Mercy realisation
1. **Fine facial forms:** lip outline (a defined cupid's bow, thinner upper lip), the upper-eyelid fold and crease, and
   nostril shape need dedicated shape operators or authored detail shapes; the region transforms cannot create new forms.
2. **Illustration proportions:** very large eyes and a compact lower face beyond about these values start to break
   realism (the operators keep anatomy plausible, which caps how anime-like the face can become).
3. **Non-geometry identity:** silver-violet hair with the fringe over one eye, winged liner, heavy lashes, violet
   irises, makeup, piercings, gauges and headphones carry most of REF-001's recognisability (out of scope here).
4. **Expression:** the reference smiles; v3 has no expression system beyond the blink.
5. **Jaw and lip defects above** need a jaw-contour operator (gonial transition) and a lip-projection control.

## Recommended next milestone
3D/3E as planned (identity as a versioned DNA group, the stylised and ID-A/ID-B faces as studio identity presets),
with two small operators first: lip projection/outline and a jaw-contour smoothing operator. Then the stylised
material layer (hair, liner, lashes, iris colour) for an actual Mercy attempt.
