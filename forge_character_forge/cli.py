"""Black Lantern Character Forge command line.

  python -m forge_character_forge new --preset female --name ada --out ada.dna.json
  python -m forge_character_forge set ada.dna.json body.height_m=1.72 face.jaw_width=0.9 --lock
  python -m forge_character_forge lock ada.dna.json body.height_m appearance.hair_color
  python -m forge_character_forge regenerate ada.dna.json --group face --seed 7
  python -m forge_character_forge export ada.dna.json --out ada.glb [--profile developer] [--physics] [--body-morphs]
  python -m forge_character_forge render ada.dna.json --out ada.png [--pose contrapposto] [--yaw 30]
  python -m forge_character_forge reconstruct photo.png --authorized [--side side.png] --out ref.dna.json
  python -m forge_character_forge validate ada.glb [--profile public]
  python -m forge_character_forge physics ada.dna.json --clip jump [--outfit-support]
  python -m forge_character_forge info ada.dna.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _value(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="forge_character_forge", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("new")
    p.add_argument("--preset", default="neutral", choices=["male", "female", "neutral"])
    p.add_argument("--name", default="character")
    p.add_argument("--age", type=float, default=30.0)
    p.add_argument("--out", required=True)
    p = sub.add_parser("set")
    p.add_argument("dna")
    p.add_argument("assignments", nargs="+", help="trait=value (JSON values, e.g. 1.2, \"long\", [\"tshirt\"])")
    p.add_argument("--lock", action="store_true")
    for name in ("lock", "unlock"):
        p = sub.add_parser(name)
        p.add_argument("dna")
        p.add_argument("traits", nargs="+")
    p = sub.add_parser("regenerate")
    p.add_argument("dna")
    p.add_argument("--group", required=True)
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--out")
    p = sub.add_parser("export")
    p.add_argument("dna")
    p.add_argument("--out", required=True)
    p.add_argument("--profile", default="public", choices=["public", "developer"])
    p.add_argument("--clips", default="idle,walk,jump,wave")
    p.add_argument("--physics", action="store_true", help="bake secondary motion into *_secondary clips")
    p.add_argument("--body-morphs", action="store_true", help="add runtime body-shape morph targets (slower)")
    p = sub.add_parser("render")
    p.add_argument("dna")
    p.add_argument("--out", required=True)
    p.add_argument("--profile", default="public", choices=["public", "developer"])
    p.add_argument("--pose", default=None)
    p.add_argument("--yaw", type=float, default=20.0)
    p.add_argument("--face", action="store_true")
    p = sub.add_parser("reconstruct")
    p.add_argument("images", nargs="+")
    p.add_argument("--side", default=None)
    p.add_argument("--authorized", action="store_true", help="confirm you have the right to use these images")
    p.add_argument("--base", default=None, help="existing DNA whose locked traits must be preserved")
    p.add_argument("--height", type=float, default=None)
    p.add_argument("--interpretation", default="realistic", choices=["realistic", "faithful"])
    p.add_argument("--posture", default=None, choices=["standing", "seated"])
    p.add_argument("--out", required=True)
    p = sub.add_parser("validate")
    p.add_argument("glb")
    p.add_argument("--profile", default=None)
    p = sub.add_parser("physics")
    p.add_argument("dna")
    p.add_argument("--clip", default="jump")
    p.add_argument("--profile", default="developer", choices=["public", "developer"])
    p.add_argument("--outfit-support", action="store_true")
    p = sub.add_parser("info")
    p.add_argument("dna")
    a = ap.parse_args(argv)

    from forge_character_forge import dna as D

    if a.cmd == "new":
        d = D.new_dna(a.preset, name=a.name, age_years=a.age)
        D.save_dna(d, a.out)
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "set":
        d = D.load_dna(a.dna)
        for asg in a.assignments:
            k, _, v = asg.partition("=")
            d = D.set_trait(d, k, _value(v), lock=True if a.lock else None)
        D.save_dna(d, a.dna)
        print(f"updated {a.dna}")
        return 0
    if a.cmd in ("lock", "unlock"):
        d = D.lock(D.load_dna(a.dna), a.traits, a.cmd == "lock")
        D.save_dna(d, a.dna)
        print(f"{a.cmd}ed {len(a.traits)} trait(s)")
        return 0
    if a.cmd == "regenerate":
        d = D.regenerate(D.load_dna(a.dna), a.group, a.seed)
        D.save_dna(d, a.out or a.dna)
        print(f"regenerated {d['history'][-1]['changed']}")
        return 0
    if a.cmd == "info":
        d = D.load_dna(a.dna)
        print(json.dumps({"identity": d["identity"], "provenance": D.provenance_summary(d), "hash": D.dna_hash(d),
                          "locked": [k for k, t in d["traits"].items() if t["locked"]],
                          "sources": d["sources"], "regions": d.get("regions"),
                          "reconstruction": d.get("reconstruction")}, indent=1))
        return 0
    if a.cmd == "export":
        from forge_character_forge.pipeline import export_character
        out = export_character(D.load_dna(a.dna), a.out, profile=a.profile,
                               clips=[c for c in a.clips.split(",") if c], physics=a.physics,
                               body_morphs=a.body_morphs)
        print(json.dumps(out, indent=1))
        return 0 if out["validation"]["ok"] else 1
    if a.cmd == "render":
        from forge_character_forge.animation import POSES
        from forge_character_forge.character import build_character
        from forge_character_forge.preview import render_character, render_face
        from forge_character_forge.render import save
        ch = build_character(D.to_spec(D.load_dna(a.dna)), a.profile)
        pose = POSES[a.pose] if a.pose else None
        img = render_face(ch, pose=pose, yaw=a.yaw) if a.face else render_character(ch, pose=pose, yaw=a.yaw)
        save(img, a.out)
        print(f"wrote {a.out}")
        return 0
    if a.cmd == "reconstruct":
        from forge_character_forge import reconstruct as R
        if not a.authorized:
            print("refusing: pass --authorized to confirm you have the right to use these images", file=sys.stderr)
            return 2
        refs = [R.load_reference(p, "front", authorized=True) for p in a.images]
        if a.side:
            refs.append(R.load_reference(a.side, "side", authorized=True))
        base = D.load_dna(a.base) if a.base else None
        d, rep = R.reconstruct(refs, base, a.interpretation, a.height, a.posture)
        D.save_dna(d, a.out)
        print(json.dumps({"provenance": D.provenance_summary(d), "reconstruction": d["reconstruction"],
                          "regions": d["regions"]}, indent=1))
        return 0
    if a.cmd == "validate":
        from forge_character_forge.validate import validate_glb
        r = validate_glb(a.glb, a.profile)
        print(json.dumps(r, indent=1))
        return 0 if r["ok"] else 1
    if a.cmd == "physics":
        from forge_character_forge.animation import clip
        from forge_character_forge.character import build_character
        from forge_character_forge import physics as P
        spec = D.to_spec(D.load_dna(a.dna))
        from forge_character_forge.skeleton import build_skeleton
        from forge_character_forge.anatomy import build_field
        skel = build_skeleton(spec.body, spec.face, spec.genital)
        build_field(spec.body, spec.face, skel)
        dev = a.profile == "developer" and spec.genital.enabled >= 0.5
        chains = P.default_chains(skel, include_dev=dev)
        cont = P.garment_containment(skel, spec.outfit, chains) if a.outfit_support else []
        r = P.simulate(skel, clip(a.clip), chains, containment=cont)
        print(json.dumps({"stable": r.stable, "max_penetration_m": r.max_penetration,
                          "raw_penetration_m": r.raw_max_penetration, "containment_corrections": r.containment_violations,
                          "amplitude_m": {b: round(P.amplitude(r, b), 4) for b in r.rotations},
                          "max_angle_deg": {b: round(float(v.max()), 2) for b, v in r.angles_deg.items()},
                          "params": r.params}, indent=1))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
