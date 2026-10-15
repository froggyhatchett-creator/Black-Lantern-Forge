"""Phase 2 demonstrations A-H for the Character Studio.

Starts the local engine server, drives the studio in headless Chromium (tools/studio_smoke.mjs and
tools/studio_demos.mjs), validates every exported file with the Python validator and the independent Node.js
checker, builds LODs, runs reconstruction on the phase 2 references, and writes contact sheets, plots and
examples/character_forge_aaa/phase2/summary.json.

Usage: python3 tools/run_phase2_demos.py [stage,stage,...]   (stages: studio,sheets,H,F,G,kit; default all)
"""
import hashlib
import json
import socket
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, ".")
sys.path.insert(0, "tools")
from run_demos import LOG, log, node_check, plot  # noqa: E402  (phase 1 helpers)

from forge_character_forge import dna as D  # noqa: E402
from forge_character_forge import reconstruct as R  # noqa: E402
from forge_character_forge.character import build_character  # noqa: E402
from forge_character_forge.lod import character_lod  # noqa: E402
from forge_character_forge.pipeline import export_character  # noqa: E402
from forge_character_forge.preview import render_character  # noqa: E402
from forge_character_forge.render import label, save, sheet  # noqa: E402
from forge_character_forge.rig import quat_from_euler  # noqa: E402
from forge_character_forge.validate import validate_glb  # noqa: E402

OUT = Path("examples/character_forge_aaa/phase2")
REFS = Path("examples/character_forge_aaa/references")
SHOTS = OUT / "frames"


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def tile(names, cols, size=(440, 275), captions=None):
    ims = []
    for i, n in enumerate(names):
        p = SHOTS / n
        if not p.exists():
            continue
        im = Image.open(p).convert("RGB")
        im = np.asarray(im.resize((size[0], int(im.height * size[0] / im.width))))
        ims.append(label(im, captions[i] if captions else Path(n).stem))
    h = max(i.shape[0] for i in ims)
    ims = [np.pad(i, ((0, h - i.shape[0]), (0, 0), (0, 0)), constant_values=24) for i in ims]
    return sheet(ims, cols)


STAGES = ("studio", "sheets", "H", "F", "G", "kit")


def main(stages=STAGES):
    """Run the given stages; results merge into an existing summary.json so stages can be re-run on their own."""
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(exist_ok=True)
    prev = OUT / "summary.json"
    summary = json.loads(prev.read_text()) if prev.exists() else {}
    timings = summary.setdefault("stage_seconds", {})
    if "studio" in stages:
        port = free_port()
        srv = subprocess.Popen([sys.executable, "-m", "forge_character_forge", "studio", "--port", str(port),
                                "--out", str(OUT / "exports")], stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        url = f"http://127.0.0.1:{port}/"
        try:
            for _ in range(60):
                try:
                    socket.create_connection(("127.0.0.1", port), 0.5).close()
                    break
                except OSError:
                    time.sleep(0.5)
            # ---- A: interactive studio (23 checks) ----
            log("== A: studio smoke test in headless Chromium")
            t0 = time.time()
            r = subprocess.run(["node", "tools/studio_smoke.mjs", url, str(OUT / "smoke")], capture_output=True, text=True)
            smoke = json.loads((OUT / "smoke" / "smoke_report.json").read_text())
            summary["A"] = {"checks": smoke["checks"], "passed": sum(c["pass"] for c in smoke["checks"]),
                            "total": len(smoke["checks"]), "seconds": round(time.time() - t0, 1), "console_errors": smoke["errors"]}
            log(r.stdout[-3000:])
            # ---- B, C, D frames, E, H via the demo driver ----
            log("== B/C/D/E/H: studio demo driver")
            t0 = time.time()
            r = subprocess.run(["node", "tools/studio_demos.mjs", url, str(SHOTS)], capture_output=True, text=True)
            log(r.stdout[-2000:], r.stderr[-2000:])
            demos = json.loads((SHOTS / "demos.json").read_text())
            summary["driver_seconds"] = round(time.time() - t0, 1)
        finally:
            srv.terminate()
            srv.wait(10)

    else:  # reuse the completed studio stage (smoke report + driver outputs) instead of re-running Chromium
        smoke = json.loads((OUT / "smoke" / "smoke_report.json").read_text())
        summary["A"] = {"checks": smoke["checks"], "passed": sum(c["pass"] for c in smoke["checks"]),
                        "total": len(smoke["checks"]), "console_errors": smoke["errors"], "reused": True}
        demos = json.loads((SHOTS / "demos.json").read_text())

    if "sheets" in stages:
        # ---- B: contact sheets ----
        save(tile(["B_preset_female.png", "B_preset_male.png", "B_preset_neutral.png",
                   "B_body_height_m_lo.png", "B_body_height_m_hi.png", "B_body_body_fat_lo.png", "B_body_body_fat_hi.png",
                   "B_body_muscle_hi.png", "B_body_shoulder_width_hi.png", "B_body_hip_width_hi.png"], 5), OUT / "B_body.png")
        face = [f"B_face_{k}_{s}.png" for k in ("jaw_width", "nose_length", "eye_size", "cheekbone_width") for s in ("lo", "hi")]
        face += [f"B_expr_{e}.png" for e in demos.get("expressions", [])]
        save(tile(face, 4, size=(400, 250)), OUT / "B_face.png")
        summary["B"] = {"body_measurements": demos["body"], "expressions": demos["expressions"]}
        # ---- C ----
        clips = ["idle", "walk", "run", "jump", "turn", "sudden_stop"]
        save(tile([f"C_{c}_{i}.png" for c in clips for i in range(4)], 4, size=(360, 225)), OUT / "C_animations.png")
        summary["C"] = demos["clips"]
        # ---- D: physics plots ----
        ph = demos["physics"]

        def series(keys, col):
            return {k: ([r[0] for r in ph[k]], [r[col] for r in ph[k]]) for k in keys}
        plot(series(["spin_damping_0_10", "spin_damping_0_22", "spin_damping_0_50", "camera_orbit_only"], 1),
             "Breast particle offset after a 0.35 s character spin (camera orbit: flat zero)", OUT / "D_damping.png", ylabel="mm")
        plot(series(["spin_damping_0_22", "spin_with_bra", "spin_intensity_0_5"], 1),
             "Garment support (bra) and intensity scaling", OUT / "D_support.png", ylabel="mm")
        plot(series(["sudden_stop_clip", "jump_clip"], 1), "Secondary motion driven by clips", OUT / "D_clips.png", ylabel="mm")
        plot(series(["spin_damping_0_22", "camera_orbit_only"], 2), "Skirt front panel offset", OUT / "D_cloth.png", ylabel="mm")
        save(tile([f"D_spin_{i}.png" for i in range(4)], 4, size=(360, 225)), OUT / "D_spin_frames.png")

        def stats(rows):
            a = np.array(rows)
            pk = int(np.argmax(a[:, 1]))
            after = a[pk:, 1]
            settle = next((a[pk + i, 0] for i in range(len(after)) if after[i:].max() < 0.1 * max(after[0], 1e-9)), None)
            return {"peak_mm": round(float(a[:, 1].max()), 2), "peak_t": round(float(a[pk, 0]), 3),
                    "settle_10pct_s": None if settle is None else round(float(settle - a[pk, 0]), 3),
                    "final_mm": round(float(a[-1, 1]), 3), "cloth_peak_mm": round(float(a[:, 2].max()), 2)}
        summary["D"] = {k: stats(v) for k, v in ph.items() if k != "columns"}
        # ---- E ----
        save(tile([f"E_hair_{h}.png" for h in ("bald", "buzz", "short", "pixie", "bob", "bangs", "long", "bun")] + ["E_highlights_on.png"],
                  3, size=(400, 250)), OUT / "E_hair.png")
        save(tile([f"E_skin_{i}.png" for i in range(4)] + ["E_outfit_robe.png", "E_outfit_bra_pants.png"], 3, size=(400, 250)),
             OUT / "E_appearance.png")
    # ---- H: save -> reload -> exports ----
    dna_h = json.loads((SHOTS / "H_demo.dna.json").read_text())
    D.validate_dna(dna_h)
    hb = validate_glb(SHOTS / "H_browser_export.glb")
    se = demos["server_export"]
    summary["H"] = {"reload": demos["reload"], "dna_valid": True, "anatomy_hash": D.anatomy_hash(dna_h),
                    "browser_glb": {"validate_glb": hb["ok"], "stats": hb["stats"],
                                    "node_check": node_check(SHOTS / "H_browser_export.glb").get("ok")},
                    "server_export": {k: se.get(k) for k in ("status", "path", "bytes", "seconds", "error")}}
    if se.get("status") == 200:
        p = Path(se["path"])
        summary["H"]["server_export"].update(validate_glb=validate_glb(p)["ok"], node_check=node_check(p).get("ok"))
    log("H:", json.dumps(summary["H"])[:600])
    if "F" in stages:
        # ---- F: optimized GLBs (LOD) from the same DNA ----
        log("== F: LOD export")
        prof = {}
        t0 = time.time()
        ch = build_character(D.to_spec(dna_h), "public")  # built once; the export and the previews share it
        prof["build_character"] = round(time.time() - t0, 2)
        t0 = time.time()
        exp = export_character(dna_h, OUT / "exports" / "demo_f.glb", physics=True, lods=(0.25, 0.1), character=ch)
        prof["export_with_lods"] = round(time.time() - t0, 2)
        files = [OUT / "exports" / "demo_f.glb"] + [Path(x["path"]) for x in exp["lods"]]
        summary["F"] = {"seconds": prof["export_with_lods"], "files": [], "profile_s": prof,
                        "sha256": {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in files}}
        renders = []
        for f, ratio in zip(files, (1.0, 0.25, 0.1)):
            t0 = time.time()
            nc = node_check(f)
            v = validate_glb(f)
            prof[f"validate_{f.stem}"] = round(time.time() - t0, 2)
            tris = sum(m["triangles"] for m in nc.get("meshes", {}).values())
            summary["F"]["files"].append({"file": f.name, "bytes": f.stat().st_size, "triangles": tris, "validate_glb": v["ok"],
                                          "node_check": nc.get("ok"), "max_weight_sum_error": nc.get("maxWeightSumError")})
            t0 = time.time()
            c = ch if ratio == 1.0 else character_lod(ch, ratio)
            prof[f"character_lod_{ratio}"] = round(time.time() - t0, 2)
            t0 = time.time()
            renders.append(render_character(c, yaw=25, text=f"{f.name}: {tris:,} triangles"))
            prof[f"render_full_{ratio}"] = round(time.time() - t0, 2)
            t0 = time.time()
            renders.append(render_character(c, yaw=25, target=(0, ch.skeleton.marks["y_chin"] + 0.1, 0), distance=0.9,
                                            text="head detail"))
            prof[f"render_head_{ratio}"] = round(time.time() - t0, 2)
        save(sheet(renders, 6), OUT / "F_lods.png")
        log("F:", json.dumps(summary["F"]))
    if "G" in stages:
        # ---- G: reconstruction with DNA and provenance ----
        log("== G: reconstruction")
        summary["G"] = {}
        tiles = []
        truth = json.loads((REFS / "ground_truth.json").read_text())
        for fname in ("ref_bob_skirt.png", "ref_bangs_portrait.png", "ref_long_male.png", "ref_waist_up.png"):
            t0 = time.time()
            ref = R.load_reference(REFS / fname, authorized=True)
            dna_r, rep = R.reconstruct([ref], log=lambda *a: None)
            D.save_dna(dna_r, OUT / f"G_{Path(fname).stem}.dna.json")
            t = dna_r["traits"]
            obs = rep["observation"]
            b, f = D.to_spec(dna_r).body, D.to_spec(dna_r).face
            syn_mask = R.field_silhouette(b, f, cell=0.006)
            ov = R.overlay_image(obs, R.measure_silhouette(syn_mask), syn_mask)
            chr_ = build_character(D.to_spec(dna_r), "public")
            h = 900
            ov_im = Image.fromarray(ov)
            tiles += [np.asarray(ov_im.resize((max(1, int(ov_im.width * h / ov_im.height)), h))),
                      render_character(chr_, yaw=20, text=f"from {fname}")]
            summary["G"][fname] = {
                "seconds": round(time.time() - t0, 1), "provenance": D.provenance_summary(dna_r),
                "hair_style": [t["appearance.hair_style"]["value"], truth[fname]["appearance"]["hair_style"],
                               t["appearance.hair_style"]["confidence"], t["appearance.hair_style"]["note"]],
                "outfit": [t["wardrobe.outfit"]["value"], truth[fname]["outfit"], t["wardrobe.outfit"]["note"]],
                "regions": obs.regions, "likeness": dna_r["reconstruction"]["likeness"],
                "uncertainty_examples": dict(list(dna_r["reconstruction"]["uncertainty"].items())[:4])}
        w = max(x.shape[1] for x in tiles)
        tiles = [np.pad(x, ((0, 0), (0, w - x.shape[1]), (0, 0)), constant_values=20) for x in tiles]
        save(sheet(tiles, 4), OUT / "G_reconstruction.png")
    if "kit" in stages:
        # ---- reusable kit: SDF props/armor meshed, decimated, attached to joints, exported and skinned ----
        log("== Kit: lantern + pauldron attached to a character")
        from forge_character_forge import kit
        t0 = time.time()
        ch_k = build_character(D.to_spec(dna_h), "public")
        ch_k.parts = ch_k.parts + kit.equip_demo(ch_k)
        kexp = export_character(dna_h, OUT / "exports" / "kit_equipped.glb", character=ch_k, clips=("idle", "walk", "wave"))
        knc = node_check(OUT / "exports" / "kit_equipped.glb", anim="wave", frame=20)
        lt = kit.lantern()
        chain = kit.lod_chain(*lt["frame"], (0.5, 0.25))
        summary["kit"] = {"seconds": round(time.time() - t0, 1), "validate_glb": kexp["validation"]["ok"], "node_check": knc.get("ok"),
                          "parts": {n: m for n, m in knc.get("meshes", {}).items() if n.startswith("kit_")},
                          "lantern_frame_lod_triangles": [int(len(t)) for _, t in chain]}
        save(sheet([render_character(ch_k, yaw=-35, text="kit: lantern (hand_r) + pauldron (upperarm_l)"),
                    render_character(ch_k, pose={"upperarm_r": quat_from_euler(0, 0, -1.2)},
                                     yaw=-35, text="posed: props follow their joints")], 2), OUT / "kit_equipped.png")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    (OUT / "demo_log.txt").write_text("\n".join(LOG))
    log("wrote", OUT / "summary.json")


if __name__ == "__main__":
    main(tuple(sys.argv[1].split(",")) if len(sys.argv) > 1 else STAGES)
