"""Runnable Character Studio Step 6A demonstration."""

from __future__ import annotations

import argparse
from pathlib import Path

from forge_character_studio.generate import generate_character
from forge_character_studio.glb import write_character_glb
from forge_character_studio.model import CharacterParameters
from forge_character_studio.preview import write_character_preview, write_character_preview_set
from forge_character_studio.diagnostics import deformation_diagnostics, surface_quality
from forge_character_studio.skeleton import build_skeleton
from forge.hashing import canonical_json
from forge_character_studio.recipe import load_recipe, save_recipe
from forge_character_studio.validate_glb import validate_character_glb


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge-character-studio")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="generate a connected humanoid base")
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--height", type=float, default=1.75)
    for name in ("torso", "chest", "waist", "hip", "arm", "leg", "head", "neck", "hand", "foot",
                 "shoulder-width", "pelvis-width", "left-arm", "right-arm", "left-leg", "right-leg"):
        generate.add_argument(f"--{name}-scale", type=float, default=1.0)
    generate.add_argument("--symmetry", type=float, default=1.0)
    generate.add_argument("--subdivision", type=int, default=1)
    generate.add_argument("--out", type=Path, required=True, help="output directory")
    load = sub.add_parser("load", help="regenerate and verify a saved recipe")
    load.add_argument("recipe", type=Path)
    load.add_argument("--out", type=Path, required=True)
    validate = sub.add_parser("validate-glb", help="independently validate Character Mesh Contract v1")
    validate.add_argument("glb", type=Path)
    return parser


def _write_all(asset, out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    save_recipe(asset, out / "character.recipe.json")
    write_character_glb(asset, out / "character.glb")
    write_character_preview(asset, out / "character.preview.png")
    write_character_preview_set(asset, out)
    (out / "character.skeleton.json").write_bytes(canonical_json(build_skeleton(asset.parameters).to_dict()) + b"\n")
    report = {"surface": surface_quality(asset), "deformation": deformation_diagnostics(asset)}
    (out / "character.diagnostics.json").write_bytes(canonical_json(report) + b"\n")
    summary = validate_character_glb(out / "character.glb")
    print(f"generated {summary['vertices']} vertices, {summary['triangles']} triangles")
    print(out / "character.glb")


def main(argv=None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate-glb":
        result = validate_character_glb(args.glb)
        print(f"VALID {result['vertices']} vertices, {result['triangles']} triangles")
        return 0
    if args.command == "load":
        _write_all(load_recipe(args.recipe), args.out)
        return 0
    params = CharacterParameters(height_m=args.height, torso_scale=args.torso_scale, chest_scale=args.chest_scale,
        waist_scale=args.waist_scale, hip_scale=args.hip_scale, arm_scale=args.arm_scale, leg_scale=args.leg_scale,
        head_scale=args.head_scale, neck_scale=args.neck_scale, hand_scale=args.hand_scale, foot_scale=args.foot_scale,
        shoulder_width=args.shoulder_width_scale, pelvis_width=args.pelvis_width_scale,
        left_arm_scale=args.left_arm_scale, right_arm_scale=args.right_arm_scale,
        left_leg_scale=args.left_leg_scale, right_leg_scale=args.right_leg_scale,
        symmetry=args.symmetry, subdivision=args.subdivision)
    _write_all(generate_character(args.seed, params), args.out)
    return 0
