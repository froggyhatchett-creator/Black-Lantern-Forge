"""Reference evaluation of a v3 character in Python: the same linear model the studio evaluates from the pack.

    v = neutral + sum_controls w_c * D_c(side) + sum_identity s_k * B_k
    blink(side) = blink0 + sum_controls w_c * C_c(side) + sum_identity |s_k| * C_k(sign s_k) [+ preset residual]

then the whole character is scaled about the floor origin to the exact height control (``uniform_scale``).
With eyelid fit 2 (Phase 4A.1, ``eyelid_fit``) every D_c and B_k carries its eyelid correction K (D -> D + K(D));
fit 1 reproduces the geometry saved before Phase 4A.1.
D_c are MakeHuman control deltas, B_k the Forge identity basis (``identity.basis``), C the blink correctives (the
blink refitted at a control or identity end, minus the neutral blink). Used for tests, the blink report and to
compare the studio's GLB export against an independent evaluation.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

import numpy as np

from forge_character_forge.v3 import controls, eyelid_fit, identity, model

BLINK_MODEL = model.BLINK_MODEL  # 2 (Phase 4A); set to 1 to reproduce the Phase 1-3 blink for before/after evidence
EYELID_FIT = eyelid_fit.FIT      # 2 (Phase 4A.1); 1 = the shape bases before the eyelid fit (legacy DNA)
BLINK_RESHAPE_M = 0.0003  # a side whose lid region changes shape by more than this gets a blink corrective
CACHE = Path(__file__).resolve().parents[2] / ".forge_cache"


def control_defaults() -> dict:
    from forge_character_forge.studio_bake import BODY_RANGES, FACE_RANGES, base_params
    b, f = base_params()
    return {f"{g}.{n}": float(getattr(o, n)) for g, o, R in (("body", b, BODY_RANGES), ("face", f, FACE_RANGES)) for n in R}


@lru_cache(maxsize=None)
def _control_term(key: str, side: str, fit: int):
    r = model.control_delta(key, side)
    if r is None:
        return None
    d = eyelid_fit.fitted(r[0], fit)
    d.flags.writeable = False
    return d


def control_term(key: str, side: str) -> np.ndarray | None:
    """Shape delta of one control side at its slider end, with the current eyelid fit."""
    return _control_term(key, side, EYELID_FIT)


@lru_cache(maxsize=None)
def _identity_term(key: str, fit: int):
    d = eyelid_fit.fitted(identity.basis(key), fit)
    d.flags.writeable = False
    return d


def identity_term(key: str) -> np.ndarray:
    """Identity basis vector (s = +1) with the current eyelid fit (s = -1 is its negative)."""
    return _identity_term(key, EYELID_FIT)


class fit:
    """``with fit(1): ...`` evaluates with another eyelid fit (the bake writes both)."""

    def __init__(self, f: int):
        self.f = f

    def __enter__(self):
        global EYELID_FIT
        self.prev, EYELID_FIT = EYELID_FIT, self.f

    def __exit__(self, *exc):
        global EYELID_FIT
        EYELID_FIT = self.prev


def is_scale(key: str) -> bool:
    return controls.CONTROLS[key][1] == "scale"


def control_weights(values: dict):
    """[(key, side, weight)] exactly as the studio's piecewise-linear weights() (height excluded: post-scale)."""
    dflt = control_defaults()
    out = []
    for k, x in values.items():
        if is_scale(k):
            continue
        dv = x - dflt[k]
        if abs(dv) < 1e-9:
            continue
        side = "hi" if dv > 0 else "lo"
        r = model.control_delta(k, side)
        if r is None:
            continue
        out.append((k, side, dv / (r[1] - dflt[k])))
    return out


def _lid_reshape(d: np.ndarray, side: str) -> float:
    lid = model.lid_region(side, model.CORRECTIVE_RINGS)
    q = d[lid] - d[lid].mean(0)
    return float(np.abs(q).max())


def _model_tag() -> str:
    """Cache tag of the blink model and its parameters (a changed parameter never reuses stale correctives)."""
    if BLINK_MODEL == 1:
        return ""
    params = (model.BLINK_MODEL, model.CLOSE_AT, model.CLOSE_OVERLAP, model.FORNIX, model.MARGIN_MIN_W, model.CANTHUS_TURN,
              model.CORRECTIVE_RINGS, model.CHORD_TS)
    if model.NO_OVERTAKE is not None or model.ANGLE_UNTANGLE:  # Phase 4A.1 corner limits (absent: the Phase 4A tag)
        params += (model.NO_OVERTAKE, model.NO_OVERTAKE_ROUNDS, model.ANGLE_UNTANGLE)
    return f"_m{BLINK_MODEL}{hashlib.sha256(repr(params).encode()).hexdigest()[:8]}"


def exact_sides(v: np.ndarray):
    """The blink fitted to character ``v`` itself, per eye: ({side: delta}, info). Model 2: per-column closure
    (model.blink_closed); model 1: the Phase 1-3 grid fit of one global closing factor."""
    if BLINK_MODEL == 1:
        _, fit = model.fit_blink(v)
        return {s: model.blink_delta(v, s, fit["factor"], lower=fit["lower"]) for s in "lr"}, fit
    return {s: model.blink_closed(v, s) for s in "lr"}, {"model": 2}


def _blink0(m):
    sides, info = exact_sides(model.neutral())
    if m != 1:
        info = {**info, "exposure": _closed_exposure(model.neutral(), sides)}
    return sides, info


_B0 = {}


def blink0():
    if _model_tag() not in _B0:
        _B0[_model_tag()] = _blink0(BLINK_MODEL)
    return _B0[_model_tag()]


def _corrective(d: np.ndarray, tag: str, per_side: bool = True):
    """Blink corrective per eye side for a shape delta d (None for a side the delta does not reshape). Identity uses a
    per-side reshape test; controls keep the bake's original test on both lid regions together (per_side=False)."""
    key = hashlib.sha256(np.round(d, 7).astype("<f4").tobytes()).hexdigest()[:16]
    path = CACHE / f"v3_blinkcorr{_model_tag()}_{tag}_{key}.npz"
    v = model.neutral() + d
    if path.is_file():
        z = np.load(path)
        out = {s: (z[s] if s in z.files else None) for s in "lr"}
        info = {k: float(z[k]) for k in ("factor", "lower", "exposure") if k in z.files}
        if BLINK_MODEL != 1 and "exposure" not in info:  # caches written before exposure was recorded
            b0, _ = blink0()
            info["exposure"] = _closed_exposure(v, {s: b0[s] + (out[s] if out[s] is not None else 0) for s in "lr"})
            np.savez_compressed(path, **info, **{s: c for s, c in out.items() if c is not None})
        return out, info
    b0, _ = blink0()
    sides, fit = exact_sides(v)
    out = {}
    both = np.concatenate([model.lid_region(s, model.CORRECTIVE_RINGS) for s in "lr"])
    q = d[both] - d[both].mean(0)
    for s in "lr":
        if (_lid_reshape(d, s) if per_side else float(np.abs(q).max())) <= BLINK_RESHAPE_M:
            out[s] = None
            continue
        c = sides[s] - b0[s]
        out[s] = c if np.abs(c).max() > 1e-4 else None
    CACHE.mkdir(exist_ok=True)
    info = {k: fit[k] for k in ("factor", "lower", "exposure") if k in fit}
    if BLINK_MODEL != 1:  # the refitted blink at this end closes the eye (checked by the pack tests)
        info["exposure"] = _closed_exposure(v, sides)
    np.savez_compressed(path, **info, **{s: c for s, c in out.items() if c is not None})
    return out, info


def _closed_exposure(v, sides) -> float:
    from forge_character_forge.v3 import metrics
    return round(metrics.eye_exposure_pixels(v + sides["l"] + sides["r"]) / max(metrics.eye_exposure_pixels(v), 1), 4)


def identity_corrective(key: str, sign: int):
    """Blink corrective of one identity parameter at s = sign (+1 or -1), per eye side."""
    return _corrective(sign * identity_term(key), f"id_{key}_{'hi' if sign > 0 else 'lo'}")


def control_corrective(key: str, side: str):
    return _corrective(control_term(key, side), f"ctl_{key}_{side}", per_side=False)


def shape(control_values: dict | None = None, identity_values: dict | None = None) -> np.ndarray:
    """Unscaled base vertices (V,3) of the character (before the exact-height scaling)."""
    v = model.neutral().copy()
    for k, side, w in control_weights(control_values or {}):
        v += w * control_term(k, side)
    unknown = set(identity_values or {}) - set(identity.KEYS)
    if unknown:
        raise KeyError(f"unknown identity parameters: {sorted(unknown)}")
    for k, s in (identity_values or {}).items():
        if s:
            v += float(s) * identity_term(k)
    return v


def blink_sides(control_values: dict | None = None, identity_values: dict | None = None) -> dict:
    """Per eye: neutral blink plus the summed control and identity correctives (no preset residual), unscaled."""
    b0, _ = blink0()
    d = {s: b0[s].copy() for s in "lr"}
    terms = [(control_corrective(k, side)[0], w) for k, side, w in control_weights(control_values or {})]
    terms += [(identity_corrective(k, 1 if s > 0 else -1)[0], abs(s)) for k, s in (identity_values or {}).items() if s]
    for corr, w in terms:
        for s in "lr":
            if corr[s] is not None:
                d[s] += w * corr[s]
    return d


def preset_residuals() -> dict:
    """{preset: {side: residual}}: exact blink fit at the preset's identity (controls at default) minus the summed
    correctives there. Cached on disk with the correctives."""
    from forge_character_forge.v3 import identity_dna
    out = {}
    for name, pr in identity_dna.presets().items():
        if not pr["values"] or name not in identity_dna.RESIDUAL_PRESETS:
            continue
        vi = shape({}, pr["values"])
        tag = hashlib.sha256(np.round(vi - model.neutral(), 7).astype("<f4").tobytes()).hexdigest()[:16]
        path = CACHE / f"v3_blinkres{_model_tag()}_{tag}.npz"
        if not path.is_file():
            sides, fit = exact_sides(vi)
            summed = blink_sides({}, pr["values"])
            CACHE.mkdir(exist_ok=True)
            info = {k: fit[k] for k in ("factor", "lower") if k in fit}
            np.savez_compressed(path, **info, **{s: sides[s] - summed[s] for s in "lr"})
        z = np.load(path)
        out[name] = {"l": z["l"], "r": z["r"], "fit": {"model": BLINK_MODEL, **{k: float(z[k]) for k in ("factor", "lower") if k in z.files}}}
    return out


def blink(control_values: dict | None = None, identity_values: dict | None = None, residuals: bool = True) -> np.ndarray:
    """Studio blink morph (both eyes, closed minus open) for the character, unscaled: summed correctives plus each
    preset's residual weighted by ``identity_dna.preset_affinity``."""
    from forge_character_forge.v3 import identity_dna
    d = blink_sides(control_values, identity_values)
    out = d["l"] + d["r"]
    if residuals and identity_values:
        aff = identity_dna.preset_affinity(identity_values)
        for name, r in preset_residuals().items():
            if aff.get(name):
                out = out + aff[name] * (r["l"] + r["r"])
    return out


def height_scale(v: np.ndarray, control_values: dict | None = None) -> float:
    """Factor the studio applies so the character is exactly the height control (crown to sole of the body)."""
    hk = next(k for k in controls.CONTROLS if is_scale(k))
    h = (control_values or {}).get(hk, control_defaults()[hk])
    y = v[model.body_vertex_ids(), 1]
    return h / float(y.max() - y.min())
