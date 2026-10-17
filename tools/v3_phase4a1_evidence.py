"""Phase 4A.1 evidence: studio vs Python parity, quality on the studio's own geometry, historical DNA, sheets, GLB
walk + blink playback before/after.

1. Parity: this build's studio body and lash geometry (tools/studio_v3_eyelid.mjs --dump) against the independent
   Python evaluation (v3/evaluate.py, eyelid fit 2) at blink 0-1.
2. blink_quality on the studio's own geometry (body and lashes as dumped).
3. Historical DNA: a Phase 4A DNA loaded in the Phase 4A studio and in this one (eyelid fit 1) must give the same
   geometry; after "Use corrected eyelids" (fit 2) it must match the Python fit-2 reference.
4. Sheets of the studio screenshots, identical cameras: before (Phase 4A build) vs after.
5. GLB playback: the Phase 4A ID-A export and this build's, played by the independent loader (tools/glb_playback.mjs)
   through the walk clip with the blink morph, rendered from the files only.
usage: python3 tools/v3_phase4a1_evidence.py <before-dump-dir>
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from forge_character_forge.render import Camera, DrawItem, label, rasterize, sheet  # noqa: E402
from forge_character_forge.v3 import blink_quality as Q, evaluate as E, model  # noqa: E402

OUT = ROOT / "examples/character_forge_aaa/humanity/v3_phase4a1"
SRC = model.body_surface()[0]
CASES = ("neutral", "ID-A", "ID-B", "MERCY-INSPIRED", "ID-A_eye0.8", "MERCY-INSPIRED_eye0.8", "ID-A_stress")
LABEL = {"neutral": "Neutral", "ID-A": "ID-A", "ID-B": "ID-B", "MERCY-INSPIRED": "Mercy-inspired", "ID-A_eye0.8": "ID-A, eye size 0.8",
         "MERCY-INSPIRED_eye0.8": "Mercy-inspired, eye size 0.8", "ID-A_stress": "ID-A, male build, head 1.15, jaw 1.3"}
WEIGHTS = (0, 0.25, 0.5, 0.75, 1)


def load(d, name):
    meta = json.loads((d / f"{name}.json").read_text())
    body = np.fromfile(d / f"{name}.f4", "<f4").reshape(-1, 3).astype(float)
    lashes = np.fromfile(d / f"{name}_lashes.f4", "<f4").reshape(-1, 5, 2, 3).mean(2).astype(float)
    return body, lashes, meta


def reference(meta, w):
    ctl, iv = meta["params"], meta["identity"]["values"]
    with E.fit(meta.get("lidFit", 1)):
        v = E.shape(ctl, iv)
        d = E.blink(ctl, iv)
    k = E.height_scale(v, ctl)
    vs, ds = v * k, d * k
    c0 = Q.lash_points(vs)
    return ((v + w * d) * k)[SRC], c0 + w * (Q.lash_closed(vs, ds) - c0)


def parity():
    out = {}
    for tag in CASES:
        rows = {}
        for w in WEIGHTS:
            body, lashes, meta = load(OUT / "dumps", f"blink_{tag}_{w}")
            rb, rl = reference(meta, w)
            rows[str(w)] = {"body_max_mm": round(float(np.abs(body - rb).max() * 1000), 4),
                            "lashes_max_mm": round(float(np.linalg.norm(lashes - rl, axis=2).max() * 1000), 4)}
        out[tag] = rows
        print(tag, json.dumps(rows), flush=True)
    return out


def studio_quality():
    """blink_quality on the studio's body (open and closed) and lashes; eyeballs from the scaled reference's helpers."""
    out = {}
    for tag in CASES:
        b0, l0, meta = load(OUT / "dumps", f"blink_{tag}_0")
        b1, l1, _ = load(OUT / "dumps", f"blink_{tag}_1")
        ctl, iv = meta["params"], meta["identity"]["values"]
        with E.fit(meta.get("lidFit", 1)):
            v = E.shape(ctl, iv)
        v0 = v * E.height_scale(v, ctl)
        v0[SRC] = b0
        d = np.zeros_like(v0)
        d[SRC] = b1 - b0
        m = Q.measure(v0, d, lashes=(l0, l1))
        out[tag] = {"summary": Q.summary(m), "detail": m}
        print(tag, "studio geometry", json.dumps(Q.summary(m)), flush=True)
    return out


def historical(before_dumps: Path):
    """The Phase 4A DNA in the Phase 4A studio vs this studio (fit 1), and this studio's fit-2 upgrade vs Python."""
    a, _, ma = load(before_dumps, "legacy_dna_loaded")
    b, _, mb = load(OUT / "dumps", "legacy_dna_loaded")
    u, _, mu = load(OUT / "dumps", "legacy_dna_upgraded")
    r, _, mr = load(OUT / "dumps", "legacy_dna_upgraded_reloaded")
    ref_u, _ = reference(mu, 0)
    res = {"fit_loaded": mb.get("lidFit"), "legacy_vs_phase4a_studio_max_m": float(np.abs(a - b).max()),
           "upgrade_changes_max_mm": round(float(np.abs(u - b).max() * 1000), 3), "upgrade_fit": mu.get("lidFit"),
           "upgraded_vs_python_fit2_max_mm": round(float(np.abs(u - ref_u).max() * 1000), 4),
           "upgraded_save_reload_max_mm": round(float(np.abs(u - r).max() * 1000), 4), "reloaded_fit": mr.get("lidFit")}
    print("historical DNA", json.dumps(res), flush=True)
    return res


def shots_sheet():
    for yaw in (10, 50):
        for group, tags in (("named", ("ID-A_eye0.8", "MERCY-INSPIRED_eye0.8", "ID-A_stress")), ("presets", ("neutral", "ID-A", "ID-B", "MERCY-INSPIRED"))):
            tiles = []
            for tag in tags:
                for w in (0, 0.5, 1):
                    for when in ("before", "after"):
                        p = OUT / "shots" / f"{when}_{tag}_w{w}_y{yaw}.png"
                        if p.is_file():
                            tiles.append(label(np.asarray(Image.open(p).convert("RGB").crop((0, 40, 604, 460))),
                                               f"{LABEL[tag]}: {'open' if not w else f'blink {w}'}, {when}", size=14))
            img = sheet(tiles, 6)
            Image.fromarray(img).save(OUT / f"eyelids_{group}_before_after_yaw{yaw}.jpg", quality=88)


def glb_walk():
    """Walk frame 10 with the blink at 0, 0.5 and 1, from the Phase 4A and this build's ID-A GLBs (face close-up)."""
    glbs = {"before (Phase 4A export)": ROOT / "examples/character_forge_aaa/humanity/v3_phase4a/regression/v3_identity_id_a.glb",
            "after (this build's export)": OUT / "regression/v3_identity_id_a.glb"}
    meshes = ("body", "eye_l", "eye_r", "basic_top", "basic_shorts", "brows", "lashes")
    tiles, report = [], {}
    for when, glb in glbs.items():
        for w in (0, 0.5, 1):
            od = OUT / "playback" / f"{'before' if when.startswith('before') else 'after'}_w{w}"
            r = subprocess.run(["node", str(ROOT / "tools/glb_playback.mjs"), str(glb), str(od), "--anim", "walk", "--frames", "10",
                                "--morph", f"blink_l={w},blink_r={w}", "--meshes", ",".join(meshes)], capture_output=True, text=True, check=True)
            idx = json.loads(r.stdout.strip().splitlines()[-1])
            pos = {m: np.fromfile(od / f"{m}_f10.f4", "<f4").reshape(-1, 3).astype(float) for m in idx["meshes"]}
            tris = {m: np.fromfile(od / f"{m}_idx.u4", "<u4").reshape(-1, 3).astype(np.int64) for m in idx["meshes"]}
            if not any(m.startswith("basic_") for m in pos):
                raise RuntimeError("garments missing: public renders stay clothed")
            items = [DrawItem(pos["body"], tris["body"], color=(0.62, 0.48, 0.41), roughness=0.55, specular=0.15, sss=0.6)]
            col = {"eye_l": (0.75, 0.72, 0.68), "eye_r": (0.75, 0.72, 0.68), "basic_top": (0.33, 0.4, 0.5), "basic_shorts": (0.22, 0.24, 0.28),
                   "brows": (0.1, 0.07, 0.05), "lashes": (0.04, 0.03, 0.02)}
            for m, c in col.items():
                if m in pos:
                    items.append(DrawItem(pos[m], tris[m], color=c, roughness=0.6, specular=0.2, double_sided=True))
            eye = pos["eye_l"].mean(0)
            cam = Camera(yaw_deg=25, pitch_deg=3, target=tuple(eye + [-0.01, 0.0, 0.0]), distance=0.12, fov_deg=26)
            tiles.append(label(rasterize(items, cam, W=420, H=300, background=(0.8, 0.82, 0.85), ground_y=None),
                               f"ID-A GLB, walk frame 10, blink {w}: {when}", size=13))
            report[f"{when} blink {w}"] = {"head_world": idx["frames"][0]["head_world"], "morphs": idx["meshes"]["body"]["morphs_applied"],
                                           "lash_morphs": idx["meshes"]["lashes"]["morphs_applied"]}
    Image.fromarray(sheet(tiles, 3)).save(OUT / "glb_walk_blink_before_after.jpg", quality=90)
    return report


def glb_manifest():
    """sha256, size and validation of the regression GLBs (the GLBs themselves are not committed)."""
    from forge_character_forge.validate import validate_glb
    out = {}
    for f in sorted((OUT / "regression").glob("*.glb")):
        b = f.read_bytes()
        v = validate_glb(f)
        out[f.name] = {"bytes": len(b), "sha256": hashlib.sha256(b).hexdigest(), "valid": v["ok"], "errors": v["errors"],
                       "morph_targets": v["stats"]["morph_targets"], "animations": v["stats"]["animations"], "joints": v["stats"]["joints"]}
    (OUT / "regression" / "glb_manifest.json").write_text(json.dumps(out, indent=1))
    print("GLB manifest", json.dumps(out), flush=True)
    return out


def main():
    before = Path(sys.argv[1])
    rep = {"parity": parity(), "studio_geometry_quality": {k: v["summary"] for k, v in studio_quality().items()},
           "historical_dna": historical(before)}
    shots_sheet()
    rep["glb_walk"] = glb_walk()
    rep["glb_manifest"] = glb_manifest()
    (OUT / "phase4a1_evidence.json").write_text(json.dumps(rep, indent=1))


if __name__ == "__main__":
    main()
