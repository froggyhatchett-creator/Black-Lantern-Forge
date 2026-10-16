"""Character DNA: the editable, versioned, provenance-tracked description of a character.

Every editable value is a *trait* with
  value        the parameter value
  provenance   observed  - measured directly from a reference image region
               estimated - derived from observed data through a model/prior
               invented  - procedurally chosen (preset prior / seeded sampling); not seen anywhere
               user      - set or approved by a person
               default   - untouched generator default
  confidence   0..1 (1 for user edits; reconstruction sets measured confidence)
  locked       locked traits are never changed by regeneration or refitting
  sources      ids of the reference images that informed it
DNA converts to a CharacterSpec (and so to real geometry) at any time.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import fields
from pathlib import Path

import numpy as np

from forge.hashing import canonical_json
from forge_character_forge.appearance import HAIR_STYLES, AppearanceParams
from forge_character_forge.character import CharacterSpec
from forge_character_forge.clothing import GARMENTS
from forge_character_forge.params import BodyParams, FaceParams, GenitalParams, ParameterError, preset

DNA_SCHEMA = "forge.character-dna"
DNA_VERSION = 1
PROVENANCE = ("observed", "estimated", "invented", "user", "default")
GROUPS = {"body": BodyParams, "face": FaceParams, "genital": GenitalParams, "appearance": AppearanceParams}
# regeneration priors: (low, high) sampling window per numeric trait (inside the stability ranges)
_PRIOR = {
    "body.height_m": (1.55, 1.95), "body.body_fat": (0.1, 0.6), "body.muscle": (0.15, 0.8),
    "body.belly": (0.0, 0.4), "body.breast_size": (0.0, 1.6), "body.breast_sag": (0.0, 0.7),
    "face.nose_upturn": (-0.5, 0.5), "face.eye_tilt": (-0.5, 0.5), "face.asymmetry": (0.0, 0.4),
    "appearance.skin_tone": (0.0, 1.0), "appearance.undertone": (-0.6, 0.6), "appearance.flush": (0.2, 0.8),
    "appearance.lip_tint": (0.2, 0.8), "appearance.skin_roughness": (0.3, 0.7),
}
_DEFAULT_WINDOW = (0.85, 1.15)
_SKIP_REGEN = {"genital.enabled", "body.femininity"}


# Layers keep what a character *is* apart from how it is styled or dressed.  Hair style/color/highlights,
# brow color and the wardrobe can change freely without changing the anatomical identity.
STYLING_TRAITS = ("appearance.hair_style", "appearance.hair_color", "appearance.hair_highlight_color",
                  "appearance.hair_highlight_amount", "appearance.brow_color")


def layer_of(key: str) -> str:
    if key.startswith("wardrobe."):
        return "wardrobe"
    if key in STYLING_TRAITS:
        return "styling"
    return "anatomy"


def anatomy_hash(dna: dict) -> str:
    """Hash of the anatomy layer only (body, face, genital, skin and eye appearance)."""
    t = {k: v["value"] for k, v in dna["traits"].items() if layer_of(k) == "anatomy"}
    if "face_identity" in dna:  # only when present: DNA without the group keeps its hash
        t["face_identity"] = _identity_values(dna)
    return hashlib.sha256(canonical_json(t)).hexdigest()[:16]


def _identity_values(dna: dict) -> dict:
    g = dna["face_identity"]
    return {"version": g["version"], "values": {k: v for k, v in sorted(g["values"].items()) if v}}


def spec_to_dict(spec: CharacterSpec) -> dict:
    return {"body": spec.body.to_dict(), "face": spec.face.to_dict(), "genital": spec.genital.to_dict(),
            "appearance": spec.appearance.to_dict(), "outfit": list(spec.outfit), "age_years": float(spec.age_years),
            "name": spec.name, "outfit_colors": [list(x) for x in spec.outfit_colors]}


def _trait(value, provenance="default", confidence=1.0, sources=(), locked=False, note=""):
    if provenance not in PROVENANCE:
        raise ValueError(f"bad provenance {provenance!r}")
    return {"value": value, "provenance": provenance, "confidence": float(confidence), "sources": list(sources),
            "locked": bool(locked), "note": note}


def new_dna(preset_name: str = "neutral", name: str = "character", age_years: float = 30.0,
            appearance: AppearanceParams | None = None, outfit=None, provenance: str = "default") -> dict:
    body, face, gen = preset(preset_name)
    app = appearance or AppearanceParams()
    spec = CharacterSpec(body, face, gen, app, tuple(outfit) if outfit is not None else CharacterSpec().outfit,
                         age_years, name)
    return dna_from_spec(spec, provenance=provenance, preset_name=preset_name)


def dna_from_spec(spec: CharacterSpec, provenance: str = "default", preset_name: str = "custom") -> dict:
    traits = {}
    for g, obj in (("body", spec.body), ("face", spec.face), ("genital", spec.genital), ("appearance", spec.appearance)):
        for k, v in obj.to_dict().items():
            traits[f"{g}.{k}"] = _trait(v, provenance)
    traits["wardrobe.outfit"] = _trait(list(spec.outfit), provenance)
    traits["wardrobe.colors"] = _trait({g: c for g, c in spec.outfit_colors}, provenance)
    return {"schema": DNA_SCHEMA, "version": DNA_VERSION,
            "identity": {"name": spec.name, "age_years": float(spec.age_years), "preset": preset_name},
            "traits": traits, "sources": [], "regions": {}, "reconstruction": None, "history": []}


def to_spec(dna: dict) -> CharacterSpec:
    validate_dna(dna)
    t = dna["traits"]
    groups = {}
    for g, cls in GROUPS.items():
        kw = {f.name: t[f"{g}.{f.name}"]["value"] for f in fields(cls) if f"{g}.{f.name}" in t}
        groups[g] = cls(**kw)
    colors = t.get("wardrobe.colors", {"value": {}})["value"]
    return CharacterSpec(groups["body"], groups["face"], groups["genital"], groups["appearance"],
                         tuple(t["wardrobe.outfit"]["value"]), dna["identity"]["age_years"], dna["identity"]["name"],
                         tuple(sorted(colors.items())))


def validate_dna(dna: dict) -> None:
    if not isinstance(dna, dict) or dna.get("schema") != DNA_SCHEMA or dna.get("version") != DNA_VERSION:
        raise ValueError("not a forge.character-dna v1 document")
    for key in ("identity", "traits", "sources"):
        if key not in dna:
            raise ValueError(f"DNA missing {key}")
    for k, tr in dna["traits"].items():
        if set(tr) != {"value", "provenance", "confidence", "sources", "locked", "note"}:
            raise ValueError(f"trait {k} malformed")
        if tr["provenance"] not in PROVENANCE or not 0.0 <= tr["confidence"] <= 1.0:
            raise ValueError(f"trait {k} has bad provenance/confidence")
    age = dna["identity"].get("age_years")
    if not isinstance(age, (int, float)) or age < 18:
        raise ParameterError("Character DNA must describe an adult (age_years >= 18)")
    outfit = dna["traits"]["wardrobe.outfit"]["value"]
    if any(g not in GARMENTS for g in outfit):
        raise ValueError("unknown garment in wardrobe.outfit")
    if "face_identity" in dna:  # optional generator-v3 identity group (absent = neutral identity)
        from forge_character_forge.v3.identity_dna import validate_group
        validate_group(dna["face_identity"])


def set_trait(dna: dict, key: str, value, *, lock: bool | None = None, note: str = "user edit") -> dict:
    """User edit: validated by building the parameter group. Returns a new DNA."""
    if key not in dna["traits"]:
        raise KeyError(f"unknown trait {key!r}")
    out = copy.deepcopy(dna)
    tr = out["traits"][key]
    tr.update(value=value, provenance="user", confidence=1.0, note=note)
    if lock is not None:
        tr["locked"] = bool(lock)
    to_spec(out)  # raises on invalid values
    out["history"].append({"op": "set", "trait": key, "value": value})
    return out


def lock(dna: dict, keys, locked: bool = True) -> dict:
    out = copy.deepcopy(dna)
    for k in ([keys] if isinstance(keys, str) else keys):
        if k not in out["traits"]:
            raise KeyError(k)
        out["traits"][k]["locked"] = locked
        out["history"].append({"op": "lock" if locked else "unlock", "trait": k})
    return out


def regenerate(dna: dict, group: str, seed: int) -> dict:
    """Re-sample every unlocked trait whose key starts with ``group`` (e.g. 'face', 'body', 'appearance.hair').

    Locked traits are untouched. New values are marked 'invented' with low confidence.
    """
    out = copy.deepcopy(dna)
    rng = np.random.default_rng(seed)
    changed = []
    for key in sorted(out["traits"]):
        tr = out["traits"][key]
        if not key.startswith(group) or tr["locked"] or key in _SKIP_REGEN:
            continue
        v = tr["value"]
        if key == "appearance.hair_style":
            nv = str(rng.choice([s for s in HAIR_STYLES]))
        elif key == "appearance.eye_color":
            from forge_character_forge.appearance import EYE_COLORS
            nv = str(rng.choice(sorted(EYE_COLORS)))
        elif key in ("appearance.hair_color", "appearance.brow_color"):
            if key == "appearance.brow_color":
                continue
            base = np.array([[0.05, 0.035, 0.02], [0.25, 0.12, 0.05], [0.55, 0.40, 0.18], [0.35, 0.08, 0.03],
                             [0.02, 0.02, 0.02], [0.6, 0.6, 0.6]])[rng.integers(0, 6)]
            from forge_character_forge.appearance import linear_to_hex
            nv = linear_to_hex(base)
        elif key.startswith("wardrobe."):
            continue
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            lo, hi = _PRIOR.get(key, (v * _DEFAULT_WINDOW[0], v * _DEFAULT_WINDOW[1]))
            if key not in _PRIOR:
                lo, hi = max(lo, 0.7), min(hi, 1.4)
            nv = float(round(rng.uniform(lo, hi), 4))
        else:
            continue
        tr.update(value=nv, provenance="invented", confidence=0.3, note=f"regenerated(group={group}, seed={seed})")
        changed.append(key)
    to_spec(out)
    out["history"].append({"op": "regenerate", "group": group, "seed": seed, "changed": changed})
    return out


def apply_estimates(dna: dict, estimates: dict, source_ids=()) -> dict:
    """Apply reconstruction results {trait: (value, provenance, confidence, note)}; locked traits are kept."""
    out = copy.deepcopy(dna)
    kept = []
    for key, (value, prov, conf, note) in estimates.items():
        if key not in out["traits"]:
            raise KeyError(key)
        tr = out["traits"][key]
        if tr["locked"]:
            kept.append(key)
            continue
        tr.update(value=value, provenance=prov, confidence=float(conf), note=note, sources=list(source_ids))
    to_spec(out)
    out["history"].append({"op": "apply_estimates", "n": len(estimates), "kept_locked": kept})
    return out


def save_dna(dna: dict, path) -> Path:
    validate_dna(dna)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(dna, indent=1, sort_keys=True).encode() + b"\n")
    return path


def load_dna(path) -> dict:
    try:
        dna = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read DNA: {exc}") from exc
    validate_dna(dna)
    to_spec(dna)
    return dna


def dna_hash(dna: dict) -> str:
    """Hash of everything that affects geometry/appearance (values only, not provenance)."""
    vals = {k: t["value"] for k, t in dna["traits"].items()}
    doc = {"identity": dna["identity"], "values": vals}
    if "face_identity" in dna:  # only when present: DNA without the group keeps its hash
        doc["face_identity"] = _identity_values(dna)
    return hashlib.sha256(canonical_json(doc)).hexdigest()


def provenance_summary(dna: dict) -> dict:
    out = {p: 0 for p in PROVENANCE}
    for t in dna["traits"].values():
        out[t["provenance"]] += 1
    return out
