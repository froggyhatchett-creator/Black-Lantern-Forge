"""Character assembly: spec -> skeleton + body + accessories + garments (+ developer anatomy).

Export profiles
  public     clothed by default; nipple/areola detail removed from the body;
             developer anatomy parts and bones are never built.
  developer  private validation profile; requires an adult (age_years >= 18)
             for anatomy; may be unclothed; parts carry ``dev_only`` flags.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field

import numpy as np

from forge_character_forge import accessories, clothing, mesher
from forge_character_forge.appearance import AppearanceParams, skin_vertex_colors
from forge_character_forge.body import build_body
from forge_character_forge.dev_anatomy import build_genitals
from forge_character_forge.expressions import expression_morphs
from forge_character_forge.params import BodyParams, FaceParams, GenitalParams, ParameterError
from forge_character_forge.parts import Part
from forge_character_forge.skeleton import DEV_BONES, Skeleton

PROFILES = ("public", "developer")
GENERATOR_ID = "forge.character-forge"
GENERATOR_VERSION = 1


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class CharacterSpec:
    body: BodyParams = field(default_factory=BodyParams)
    face: FaceParams = field(default_factory=FaceParams)
    genital: GenitalParams = field(default_factory=GenitalParams)
    appearance: AppearanceParams = field(default_factory=AppearanceParams)
    outfit: tuple = clothing.DEFAULT_PUBLIC_OUTFIT
    age_years: float = 30.0
    name: str = "character"
    outfit_colors: tuple = ()      # ((garment, "#rrggbb"), ...) overrides

    def __post_init__(self):
        if not isinstance(self.age_years, (int, float)) or not 18.0 <= float(self.age_years) <= 120.0:
            raise ParameterError("Black Lantern Character Forge only creates adult characters (age_years 18-120)")
        for g in self.outfit:
            if g not in clothing.GARMENTS:
                raise ParameterError(f"unknown garment {g!r}")
        from forge_character_forge.appearance import hex_to_linear
        for g, c in self.outfit_colors:
            if g not in clothing.GARMENTS:
                raise ParameterError(f"unknown garment {g!r} in outfit_colors")
            hex_to_linear(c)

    def garment_color(self, garment: str):
        from forge_character_forge.appearance import hex_to_linear
        for g, c in self.outfit_colors:
            if g == garment:
                return tuple(float(x) for x in hex_to_linear(c))
        return clothing.COLORS[garment]


@dataclass
class Character:
    spec: CharacterSpec
    profile: str
    skeleton: Skeleton
    parts: list
    body_field: object
    template: object
    quality: dict
    coverage: dict

    def part(self, name: str) -> Part:
        return next(p for p in self.parts if p.name == name)

    @property
    def body(self) -> Part:
        return self.part("body")


def required_coverage(body: BodyParams) -> set:
    need = {"pelvis"}
    if body.femininity > 0.5 or body.breast_size > 0.15:
        need.add("chest")
    return need


def resolve_outfit(spec: CharacterSpec, profile: str) -> tuple:
    outfit = tuple(spec.outfit)
    if profile == "public":
        need = required_coverage(spec.body)
        have = set()
        for g in outfit:
            have |= {r for r, s in clothing.COVERS.items() if g in s}
        missing = need - have
        if "pelvis" in missing:
            outfit += ("shorts",)
        if "chest" in missing:
            outfit += ("tshirt",)
    return outfit


def build_character(spec: CharacterSpec, profile: str = "public", *, body_morphs: bool = False,
                    fast: bool = False) -> Character:
    if profile not in PROFILES:
        raise ProfileError(f"profile must be one of {PROFILES}")
    body_p = spec.body
    if profile == "public":
        body_p = body_p.with_(nipple_size=0.0, areola_size=0.0)
    gen = spec.genital
    bm = build_body(body_p, spec.face, nipples=profile == "developer", fast=fast, genital=gen)
    skel = bm.skeleton
    tpl = bm.template
    app = spec.appearance
    colors = skin_vertex_colors(bm.verts, bm.normals, tpl.tags, tpl.tag_names, bm.joints, bm.weights, skel, app,
                                body_p)
    if app.hair_style == "buzz":
        mask = accessories.hair_mask(tpl, tpl.skeleton)
        colors[mask] = colors[mask] * 0.55 + app.hair_linear() * 0.45
    morphs = expression_morphs(bm.verts, skel, spec.face, tpl.region_of_vertex)
    # rest expression: lips closed (the template keeps a real mouth opening; the jaw bone opens it)
    rest_close = morphs.pop("mouth_close") * 0.9
    bm.verts = bm.verts + rest_close
    bm.normals = mesher.vertex_normals(bm.verts, bm.tris)
    morphs = expression_morphs(bm.verts, skel, spec.face, tpl.region_of_vertex)
    morphs.pop("mouth_close")
    morphs["lips_part"] = -rest_close
    shape_morphs = {}
    if body_morphs and not fast:
        for name, delta in (("body_fat", {"body_fat": min(1.0, body_p.body_fat + 0.4)}),
                            ("muscle", {"muscle": min(1.0, body_p.muscle + 0.4)}),
                            ("breast_size", {"breast_size": min(3.0, body_p.breast_size + 1.0)})):
            other = build_body(body_p.with_(**delta), spec.face, nipples=profile == "developer")
            shape_morphs[f"shape_{name}"] = other.verts - bm.verts
    morphs.update(shape_morphs)
    body = Part("body", bm.verts, bm.tris, "skin", bm.joints, bm.weights, normals=bm.normals, colors=colors,
                morphs=morphs, extras={"fixed_topology": True, "template_vertices": int(len(bm.verts))})
    parts = [body]
    parts += accessories.build_eyes(skel, app)
    parts += accessories.build_mouth(skel)
    parts += accessories.build_brows_lashes(skel, bm.field, app, spec.face)
    parts += accessories.build_hair(bm.verts, bm.normals, tpl, skel, tpl.skeleton, app, bm.field)
    outfit = resolve_outfit(spec, profile)
    garment_morphs = shape_morphs
    parts += clothing.build_garments(outfit, bm.verts, bm.normals, tpl, tpl.skeleton, skel, bm.field, garment_morphs)
    if profile == "developer" and gen.enabled >= 0.5:
        parts.append(build_genitals(skel, gen, app.skin_linear(), bm.field))
    if profile == "public":
        keep = [n for n in skel.names if n not in DEV_BONES]
        skel = _drop_joints(skel, keep, parts)
        if any(p.dev_only for p in parts):
            raise ProfileError("developer-only part leaked into a public build")
    cover = {}
    for p in parts:
        for r in p.extras.get("covers", []):
            cover.setdefault(r, []).append(p.name)
    return Character(spec, profile, skel, parts, bm.field, tpl, bm.quality,
                     {"required": sorted(required_coverage(spec.body)) if profile == "public" else [],
                      "covered_by": cover, "outfit": list(outfit)})


def _drop_joints(skel: Skeleton, keep: list[str], parts: list[Part]) -> Skeleton:
    sub = skel.subset(keep)
    remap = np.full(len(skel.names), -1, np.int64)
    for new, n in enumerate(sub.names):
        remap[skel.index(n)] = new
    for p in parts:
        used = remap[p.joints]
        bad = (used < 0) & (p.weights > 0)
        if bad.any():
            raise ProfileError(f"part {p.name} is weighted to a dropped joint")
        p.joints = np.where(used < 0, 0, used)
    return sub


def spec_hash(spec: CharacterSpec) -> str:
    from forge_character_forge.dna import spec_to_dict
    from forge.hashing import canonical_json
    return hashlib.sha256(canonical_json(spec_to_dict(spec))).hexdigest()
