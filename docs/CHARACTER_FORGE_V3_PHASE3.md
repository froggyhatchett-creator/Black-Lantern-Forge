# Generator v3, Phase 3A/3B: identity foundation and two distinct faces (review gate)

Status: **Phase 3A built; Phase 3B proof complete. Stopped at the review gate.** Phases 3C (Mercy-inspired
stylisation), 3D (animation/DNA) and 3E (studio integration) have **not** been started, as instructed.

## Phase 3A: the identity layer (`forge_character_forge/v3/identity.py`, version 1)
- **Forge-owned regional transforms, not MakeHuman morphs and not landmark dragging.** Each of the 32
  parameters moves one complete anatomical region by a small affine map: `delta(p) = s * w(p) * (A (p - pivot) + t)`,
  s in [-1, 1], 0 = the v3 neutral.
- **Volumetric regions.** `w` is a plateau ellipsoid with a wide smoothstep falloff in head coordinates (origin between
  the eyeball centres). Hidden geometry moves with its region: eye sockets, mouth interior, joint helpers. Region
  centres and extents were measured from MakeHuman's CC0 detail-target vertex sets (nose, lips, chin, cheeks, eyes,
  brows), so they sit on real anatomy.
- **Coherence safeguards** (each added because a render showed the defect it fixes):
  1. linear Laplacian smoothing of every displacement field over the skin, which removes crease-scale
     discontinuities where neighbouring regions move differently (ID-B's ring around the eyes and temple crease);
  2. rigid ears: each ear takes the displacement at its centre (scaling the skull had sheared the ears into points);
  3. eyeballs follow their lids: the hidden eye-helper and eye-joint vertices take the least-squares affine motion of
     the lids (otherwise the lids cut into deep-set eyes: jagged lid edges on ID-A);
  4. head width acts on the head as one piece, and wide falloffs at the jaw angle and cheeks (a temple valley and a
     jaw-angle ridge on ID-B).
- **Properties (tested, `tests/test_character_forge_v3_identity.py`, 6 tests):** exactly linear and composable
  (sums of parameters equal the sum of their deltas); zero identity = the neutral bit for bit; unknown keys are an
  error, never reinterpreted; nothing moves below the neck; deterministic; topology and UVs unchanged by construction.
- **Independence:** identity is a delta on the neutral mesh; the 53 body/face controls, expressions (blink), materials,
  grooming, garments and animation are evaluated on top. Blink is refitted per identity (`model.fit_blink`).

### Parameters
| Key | Meaning | Region | Transform |
|---|---|---|---|
| `skull_length` | Skull length (back of head) | cranium + back | scale z+10% at s = +1 |
| `skull_width` | Head width | head + above_jaw | scale x+8% at s = +1 |
| `forehead_height` | Forehead height | forehead | scale y+16% at s = +1 |
| `forehead_slope` | Forehead slope | forehead | rotation/shear at s = +1 |
| `brow_ridge` | Brow ridge projection | brow | move y +0.5 mm, z +4.5 mm at s = +1 |
| `eye_depth` | Deep-set eyes | eye (both sides) | move z -2.8 mm at s = +1 |
| `eye_spacing` | Eye spacing | eye (both sides) | move x +4.5 mm at s = +1 |
| `eye_size` | Eye size | eye (both sides) | scale x+13%, y+13%, z+13% at s = +1 |
| `eye_tilt` | Eye tilt (outer corner up) | eye (both sides) | rotation/shear at s = +1 |
| `eye_height` | Eye height | eye (both sides) | move y +4.0 mm at s = +1 |
| `nose_length` | Nose length | nose | scale y+12% at s = +1 |
| `nose_width` | Nose width (alae) | alae | scale x+24% at s = +1 |
| `nose_projection` | Nose projection | nose | scale z+14% at s = +1 |
| `nose_bridge` | Nose bridge height | bridge | move z +3.0 mm at s = +1 |
| `nose_tip_size` | Nose tip size | nose_tip | scale x+28%, y+28%, z+22% at s = +1 |
| `nose_tip_angle` | Nose tip upturn | nose_tip | rotation/shear at s = +1 |
| `cheekbone_width` | Cheekbone width | cheekbone (both sides) | move x +4.5 mm, z +1.0 mm at s = +1 |
| `cheekbone_height` | Cheekbone height | cheekbone (both sides) | move y +4.5 mm at s = +1 |
| `cheek_fullness` | Cheek fullness | cheek (both sides) | move x +3.5 mm, z +3.0 mm at s = +1 |
| `midface_projection` | Midface projection | midface | move z +4.0 mm at s = +1 |
| `mouth_width` | Mouth width | mouth | scale x+15% at s = +1 |
| `mouth_height` | Mouth position (up) | mouth | move y +3.5 mm at s = +1 |
| `upper_lip` | Upper lip fullness | upper_lip | scale y+30%, z+25% at s = +1 |
| `lower_lip` | Lower lip fullness | lower_lip | scale y+30%, z+25% at s = +1 |
| `jaw_width` | Jaw width | lower_face + below_mouth | scale x+12% at s = +1 |
| `jaw_angle` | Jaw angle prominence | gonion (both sides) | move x +4.5 mm, y -3.5 mm, z -2.0 mm at s = +1 |
| `jaw_taper` | Jaw taper (V-shape) | lower_face + front_low | scale x-16% at s = +1 |
| `chin_width` | Chin width | chin | scale x+22% at s = +1 |
| `chin_height` | Chin height | chin | scale y+20% at s = +1 |
| `chin_projection` | Chin projection | chin | move z +6.5 mm at s = +1 |
| `face_length` | Face length | face + below_brow | scale y+8% at s = +1 |
| `face_width` | Face width | face | scale x+7% at s = +1 |

## Phase 3B: two original adults on the same topology
Both are defined only by identity values (`identity.IDENTITIES`); same body controls, bald, one neutral material,
identical cameras and light (Forge software rasteriser).
- **ID-A:** long, narrow and angular. High sloping forehead, strong brow ridge, deep-set close eyes, long high-bridged
  narrow nose, high cheekbones over hollow cheeks, small thin mouth, narrow V-tapered jaw, long projecting pointed chin.
- **ID-B:** short, broad and soft. Round wide skull, low forehead, wide-set large prominent eyes, short broad upturned
  nose, full low cheeks, wide full mouth, wide square jaw with strong angles, short broad receding chin.

Evidence (`examples/character_forge_aaa/humanity/v3_phase3/`):
- `identity_sheet.png`: neutral, ID-A, ID-B; front, left profile, right profile, three-quarter, closed blink;
- `identity_closeups.png`: larger front and three-quarter faces;
- `identity_eyes_blink.png`: eyes open, half and closed per identity;
- `identity_report.json`: all numbers.

### Measurements
| | Neutral | ID-A | ID-B |
|---|---|---|---|
| Flipped triangles on the head (vs neutral) | 0 | 0 | 0 |
| Max / p99 triangle area change | 1 / 1 | 3.27 / 1.54 | 2.08 / 1.62 |
| Min angle (1st percentile), triangles under 2 degrees | 7.63 deg, 0 | 6.38 deg, 0 | 7.99 deg, 0 |
| Mean surface Laplacian (smoothness), mm | 0.805 | 0.826 | 0.836 |
| Eye joint to eyeball centre, mm | 0.72 | 0.76 | 1.74 |
| Blink (refitted): closed exposure, half exposure, folded lid triangles | 0.0, 0.467, 4 | 0.0, 0.458, 22 | 0.0038, 0.52, 0 |
| Head displacement from neutral, mean / p95 / max, mm | 0 | 6.3 / 11.19 / 17.71 | 7.25 / 12.06 / 19.06 |

**Shape distance** (mean head-vertex distance after aligning the eyeball centres): ID-A vs ID-B
**14.41 mm** (p95 24.08); neutral vs ID-A 6.54, neutral vs ID-B
7.92. For comparison: MakeHuman's own female variants differ by 0-2.8 mm, its female vs male
macro by 5.2-5.7 mm, and the earlier regional identity experiment reached 1.28 mm.

### Visual verdict (the gate)
In the matched renders, neutral, ID-A and ID-B read as **three different people**, from the front, in profile and at
three-quarter: different skull and face proportions, eye placement and depth, nose, mouth, jaw and chin. The
differences are structural (silhouette and profile change), not resized features on one face. Anatomy stays coherent:
no flipped triangles, no collapses or dents, intact sockets and eyelids, rigid ears; both blink fully closed.

Remaining defects (my review; your judgement decides the gate):
- ID-B's mouth reads slightly sullen (MakeHuman's lip shape enlarged, corners low), and its cheeks are soft and
  puffy; ID-B's jaw-angle-to-neck transition shows a faint line in profile.
- ID-A's nasal bridge has a narrow crest, and its closed eyelids show slight wrinkling at the inner corner
  (22 folded lid triangles).
- Both faces keep MakeHuman's small-scale forms (lip outline, nostril and eyelid shape, ear): the identity layer
  changes structure and proportion, not fine form. Fine-form identity (lip shape, eyelid fold, nostril shape) needs
  further region operators or authored detail shapes.
- Previews use the Forge software rasteriser with per-vertex iris colouring (pupils look blotchy on the coarse eye
  mesh; the studio shades the iris per pixel). No skin texture, as required for this proof.

## Proposed next steps (not started; awaiting approval)
- **3C** Mercy-inspired geometry-only stylisation with the same operators (almond eyes need an aperture-shape operator
  that keeps lids on the eyeball; a smaller refined nose and mouth, tapered jaw and pointed chin are already
  expressible).
- **3D/3E** identity as a versioned DNA group (`identity.version = 1`, keys as above, values in
  [-1, 1]), each parameter one more linear basis in the studio pack, per-identity blink refits as correctives, and
  identity presets (ID-A, ID-B) in the v3 studio. Old DNA without an identity group loads as the neutral identity
  (explicitly, not by reinterpretation).
