# MakeHuman (CC0) candidate foundation: experiments

Owner-approved experiments only. Nothing here is integrated into Forge generators, Character DNA, rigging or export.

- `proof.py` -> `out/`: v2 head vs MakeHuman hm08 head (matched renders, topology, blink).
- `morph_proof.py` -> `out_morph/`: real macro and detail targets, female/male shapes, representative morph tests,
  mapping of Forge's 53 parameters, garment-fitting checks (`morph_report.json`).
- `assets/` contains only bundled MakeHuman assets (CC0); see `PROVENANCE.json` and both licence files. No
  MakeHuman/MPFB code (AGPL/GPL) is used.

**Developer-only evidence.** `out_morph/bodies.png` and `out_morph/morphs_body.png` show unclothed base bodies for
anatomy and morph inspection (Developer Anatomy Lab material). They are not public character output; any integration
keeps the clothed public profile and the existing developer-export safeguards.
