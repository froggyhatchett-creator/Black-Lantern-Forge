"""DNA -> character -> GLB (+ optional baked physics) -> validation, as one call."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from forge_character_forge import dna as D
from forge_character_forge import physics as P
from forge_character_forge.animation import clip as make_clip
from forge_character_forge.character import build_character
from forge_character_forge.gltf import write_glb
from forge_character_forge.validate import validate_glb


def export_character(dna: dict, out, profile: str = "public", clips=("idle", "walk", "jump", "wave"),
                     physics: bool = False, body_morphs: bool = False, character=None) -> dict:
    spec = D.to_spec(dna)
    ch = character or build_character(spec, profile, body_morphs=body_morphs)
    u = ch.skeleton.marks["height"] / 1.75
    cl = [make_clip(c, u) for c in clips]
    sims = {}
    if physics:
        dev = profile == "developer" and spec.genital.enabled >= 0.5
        chains = P.default_chains(ch.skeleton, include_dev=dev)
        cont = P.garment_containment(ch.skeleton, ch.coverage["outfit"], chains)
        baked = []
        for c in cl:
            r = P.simulate(ch.skeleton, c, chains, containment=cont)
            sims[c.name] = {"stable": r.stable, "max_penetration_m": round(r.max_penetration, 6),
                            "amplitude_m": {b: round(P.amplitude(r, b), 4) for b in r.rotations}}
            baked.append(P.bake(c, r))
        cl += baked
    meta = {"dna_hash": D.dna_hash(dna), "dna_identity": dna["identity"],
            "provenance_summary": D.provenance_summary(dna),
            "reference_sources": [{k: s[k] for k in ("id", "sha256", "file", "view") if k in s} for s in dna.get("sources", [])],
            "reconstruction_method": (dna.get("reconstruction") or {}).get("method"),
            "physics_baked": sorted(sims)}
    path = write_glb(ch, out, clips=cl, extra_meta=meta)
    data = Path(path).read_bytes()
    val = validate_glb(path, profile)
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "parts": {p.name: {"vertices": int(len(p.verts)), "triangles": int(len(p.tris))} for p in ch.parts},
            "body_quality": ch.quality, "coverage": ch.coverage, "clips": [c.name for c in cl], "physics": sims,
            "validation": {"ok": val["ok"], "errors": val["errors"], "stats": val["stats"]}}
