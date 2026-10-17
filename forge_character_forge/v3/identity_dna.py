"""Versioned face-identity group of Character DNA (generator v3, Phase 3D).

An optional top-level DNA key. Absent means the neutral identity, so every existing DNA (v1/v2 characters and v3
characters saved before identity existed) keeps its exact appearance:

    "face_identity": {
      "schema": "forge.v3-face-identity", "version": 1,
      "generator": {"id": "forge.character-forge", "version": 3},
      "preset": "ID-A",           # where the values started: neutral, ID-A, ID-B, MERCY-INSPIRED, MERCY-REFINED or custom
      "values": {"nose_length": 0.7, ...},   # s in [-1, 1]; 0 = neutral; a missing key is 0
      "locked": ["nose_length"]   # kept by preset changes in the studio
    }

No silent reinterpretation: an unknown schema or version, an unknown key, or a non-numeric or out-of-range value is
an error, never dropped or clamped here. Version 1 is exactly the basis recorded in
``identity_basis_v1.json`` (sha256 of every parameter's geometry, checked by the tests); changing any
parameter's geometry requires a new version, never a silent edit of version 1.

The identity group holds face shape only. Body controls (including ``body.femininity``) stay in the DNA traits;
a preset may also suggest body controls (``PRESETS[...]["controls"]``), applied to the traits like any edit.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import numpy as np

SCHEMA = "forge.v3-face-identity"
VERSION = 1
GROUP = "face_identity"
RANGE = (-1.0, 1.0)
KEYS_V1 = (
    "skull_length", "skull_width", "forehead_height", "forehead_slope", "brow_ridge", "eye_depth", "eye_spacing",
    "eye_size", "eye_tilt", "eye_height", "nose_length", "nose_width", "nose_projection", "nose_bridge",
    "nose_tip_size", "nose_tip_angle", "cheekbone_width", "cheekbone_height", "cheek_fullness", "midface_projection",
    "mouth_width", "mouth_height", "upper_lip", "lower_lip", "jaw_width", "jaw_angle", "jaw_taper", "chin_width",
    "chin_height", "chin_projection", "face_length", "face_width", "eye_aperture", "eye_outer_corner", "eye_length",
    "lip_projection",
)
BASIS_RECORD = Path(__file__).resolve().parent / "identity_basis_v1.json"  # Forge-made, not a third-party asset
PRESET_LABELS = {"neutral": "Neutral", "ID-A": "ID-A", "ID-B": "ID-B", "MERCY-INSPIRED": "Mercy-inspired",
                 "MERCY-REFINED": "Mercy-inspired (refined)"}


# Presets that carry a blink residual. Frozen: the residuals blend by distance, so a new preset near an old one would
# change the blink of characters at and around the old one. Later presets (MERCY-REFINED) carry none.
RESIDUAL_PRESETS = ("ID-A", "ID-B", "MERCY-INSPIRED")


def presets() -> dict:
    """{name: {"values": identity values, "controls": suggested body controls}} (neutral = all zero)."""
    from forge_character_forge.v3 import identity
    out = {"neutral": {"values": {}, "controls": {}}}
    for n, vals in identity.IDENTITIES.items():
        out[n] = {"values": dict(vals), "controls": {}}
    for n, vals in identity.STYLIZED.items():
        out[n] = {"values": dict(vals), "controls": dict(identity.STYLIZED_CONTROLS.get(n, {}))}
    return out


def validate_group(g) -> None:
    if not isinstance(g, dict):
        raise ValueError("face_identity must be an object")
    if g.get("schema") != SCHEMA:
        raise ValueError(f"face_identity schema {g.get('schema')!r} is not {SCHEMA}")
    if g.get("version") != VERSION:
        raise ValueError(f"face_identity version {g.get('version')!r} is not supported (this engine reads version {VERSION})")
    vals = g.get("values")
    if not isinstance(vals, dict):
        raise ValueError("face_identity.values must be an object")
    unknown = sorted(set(vals) - set(KEYS_V1))
    if unknown:
        raise ValueError(f"face_identity has unknown parameters {unknown} (version {VERSION} defines {len(KEYS_V1)})")
    for k, x in vals.items():
        if isinstance(x, bool) or not isinstance(x, (int, float)) or not np.isfinite(x):
            raise ValueError(f"face_identity.{k} is not a number")
        if not RANGE[0] <= x <= RANGE[1]:
            raise ValueError(f"face_identity.{k} = {x} is outside {list(RANGE)}")
    locked = g.get("locked", [])
    if not isinstance(locked, list) or set(locked) - set(KEYS_V1):
        raise ValueError("face_identity.locked must list known parameters")
    if not isinstance(g.get("preset", "custom"), str):
        raise ValueError("face_identity.preset must be a string")


def values_from_dna(dna: dict) -> dict:
    """All identity values of a DNA (every key; 0 where unset; all 0 when the DNA has no identity group)."""
    out = {k: 0.0 for k in KEYS_V1}
    g = dna.get(GROUP)
    if g is None:
        return out
    validate_group(g)
    out.update({k: float(x) for k, x in g["values"].items()})
    return out


def make_group(values: dict, preset: str = "custom", locked=()) -> dict:
    g = {"schema": SCHEMA, "version": VERSION, "generator": {"id": "forge.character-forge", "version": 3},
         "preset": preset, "values": {k: round(float(values.get(k, 0.0)), 4) for k in KEYS_V1},
         "locked": sorted(set(locked))}
    validate_group(g)
    return g


def set_identity(dna: dict, values: dict, preset: str = "custom", locked=()) -> dict:
    """Return a new DNA with the given identity group (values validated, history appended)."""
    out = copy.deepcopy(dna)
    out[GROUP] = make_group(values, preset, locked)
    out.setdefault("history", []).append({"op": "set_face_identity", "preset": preset})
    return out


def preset_affinity(values: dict) -> dict:
    """Weight of each non-neutral preset's blink residual: 1 at the preset, fading linearly to 0 at a distance equal
    to the preset's own size (|s - s_P| / |s_P|). The studio uses the same formula."""
    out = {}
    for n, p in presets().items():
        if not p["values"] or n not in RESIDUAL_PRESETS:
            continue
        sp = np.array([p["values"].get(k, 0.0) for k in KEYS_V1])
        s = np.array([values.get(k, 0.0) for k in KEYS_V1])
        out[n] = float(max(0.0, 1.0 - np.linalg.norm(s - sp) / np.linalg.norm(sp)))
    return out


def basis_fingerprint(key: str) -> str:
    """sha256 of one parameter's geometry (float32 deltas at s = 1, rounded to 0.1 micrometre)."""
    from forge_character_forge.v3 import identity
    b = np.round(identity.basis(key), 7).astype("<f4")
    return hashlib.sha256(b.tobytes()).hexdigest()


def basis_moments(key: str) -> list:
    """Tolerance-friendly geometry signature of one parameter: sum, absolute sum and first moments of its deltas
    (sha256 is exact but sensitive to last-bit floating-point differences between machines)."""
    from forge_character_forge.v3 import identity, model
    b = identity.basis(key)
    p = model.neutral() - identity.frame()
    return [round(float(x), 9) for x in (*b.sum(0), np.abs(b).sum(), *(b * p).sum(0), *(np.abs(b) * p).sum(0))]


def record_basis() -> dict:
    """Write identity_basis_v1.json (run once when a version is created; never to paper over a change)."""
    rec = {"schema": SCHEMA, "version": VERSION, "keys": list(KEYS_V1),
           "sha256": {k: basis_fingerprint(k) for k in KEYS_V1}, "moments": {k: basis_moments(k) for k in KEYS_V1}}
    BASIS_RECORD.write_text(json.dumps(rec, indent=1) + "\n")
    return rec


def recorded() -> dict:
    return json.loads(BASIS_RECORD.read_text())
