# Character Forge correctness defects (open)

Each entry records evidence and the regression test that must exist before the defect is closed.

## D-001 DNA values outside the studio ranges are clamped silently, so the studio and export disagree
- **Found:** REF-001 baseline (`examples/character_forge_aaa/humanity/ref001_baseline/load_report.json`).
- **Evidence:** reconstruction wrote values up to 1.55 (its fit bounds are 0.65–1.55). The studio clamps to its slider ranges
  (for example 0.8–1.25) and reports "4 value(s) were outside the studio range and were clamped", with a maximum
  parameter difference of 0.35. The Python export uses the unclamped DNA values, so the **studio preview and the exported
  character are different characters**.
- **Root cause:** three separate range definitions: reconstruction `_BOUNDS`/clip (0.65–1.55), studio `BODY_RANGES`/
  `FACE_RANGES`, and engine parameter validation. Nothing enforces a single valid range per trait.
- **Required regression test:** a DNA with a trait outside the studio range must either be rejected or produce the same
  geometry in the studio and the export. Clamping must be visible per trait. Reconstruction must never write a value
  outside the shared range.

## D-002 Extreme proportions invert triangles, and no validator catches it
- **Found:** REF-001 baseline export (`export_result.json`: `flipped_triangles_vs_template: 1906`).
- **Evidence:** chest, waist and thigh width at 1.54–1.55 with body fat 1.0 produce 1,906 triangles whose orientation flips
  relative to the template. Both `validate_glb` and the Node checker still report OK.
- **Required regression test:** build at every parameter's allowed extremes (and the worst combinations) and assert the
  flip count stays below an agreed threshold. Add the flip metric to export validation as a warning or error.

## D-003 Blink morph does not close the eyes
- **Found:** P1 eye experiment (`humanity/p1_eyes/after/eye_checks.json`).
- **Evidence:** both blink morphs at 1.0 move the lids at most 7.7 mm; the eyes stay visibly open (before and after).
- **Root cause:** SDF lids are fused into the face surface with no lid loops (see the foundation assessment).
- **Required regression test:** with blink at 1.0, the visible eyeball area seen from the front must fall below a small
  threshold.

## D-004 Reconstruction records fit bounds and failed cues as estimates
- **Evidence (REF-001):** a broken segmentation produced chest, waist and thigh widths at the fit bound, femininity 0.0
  from a meaningless waist-to-hip ratio (1.068), and a standing posture for a seated subject, all stored as "estimated"
  or "observed" values. Fit confidence was 0.14.
- **Required regression test:** values at the fit bound, or fits under a confidence threshold, are stored with provenance
  "invented" (prior) and a failure note, not as measurements. Segmentation coverage checks must flag a mask that misses
  most of the subject.

## D-005 Reconstruction peak memory 5.5 GB
- **Evidence:** REF-001 baseline peak RSS 5,527 MB for one 1152×1728 image.
- **Required regression test:** peak memory bound for one reference image at the supported resolution.
