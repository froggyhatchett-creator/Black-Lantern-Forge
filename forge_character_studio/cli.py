"""Runnable Character Studio Step 6A demonstration."""

from __future__ import annotations

import argparse
from pathlib import Path

from forge_character_studio.generate import generate_character
from forge_character_studio.glb import write_character_glb
from forge_character_studio.model import CharacterParameters
from forge_character_studio.preview import write_character_preview
from forge_character_studio.recipe import load_recipe, save_recipe
from forge_character_studio.validate_glb import validate_character_glb


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="forge-character-studio")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="generate a connected humanoid base")
    generate.add_argument("--seed", type=int, required=True)
    generate.add_argument("--height", type=float, default=1.75)
    for name in ("torso", "chest", "waist", "hip", "arm", "leg"):
        generate.add_argument(f"--{name}-scale", type=float, default=1.0)
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
    params = CharacterParameters(args.height, args.torso_scale, args.chest_scale, args.waist_scale,
                                 args.hip_scale, args.arm_scale, args.leg_scale)
    _write_all(generate_character(args.seed, params), args.out)
    return 0
