"""Run acceptance demonstrations A-F and write every artifact under examples/character_forge_aaa/.

Everything shown is produced by the pipeline in this run: DNA files, GLBs,
validator reports, independent (Node.js) skinning checks, renders of the
actual generated geometry, reconstruction overlays and physics plots.
"""
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, ".")
from forge_character_forge import dna as D
from forge_character_forge import physics as P
from forge_character_forge import reconstruct as R
from forge_character_forge.animation import POSES, clip
from forge_character_forge.appearance import AppearanceParams
from forge_character_forge.character import CharacterSpec, build_character
from forge_character_forge.gltf import pose_check_data
from forge_character_forge.pipeline import export_character
from forge_character_forge.preview import render_character, render_face
from forge_character_forge.render import label, save, sheet
from forge_character_forge.rig import quat_from_euler

OUT = Path("examples/character_forge_aaa")
REFS = OUT / "references"
LOG = []


def log(*a):
    msg = " ".join(str(x) for x in a)
    print(msg, flush=True)
    LOG.append(msg)


def node_check(glb: Path, expect: Path | None = None, anim="walk", frame=8) -> dict:
    cmd = ["node", "tools/glb_independent_check.mjs", str(glb), "--anim", anim, "--frame", str(frame)]
    if expect:
        cmd += ["--expect", str(expect)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"ok": False, "error": r.stdout[-500:] + r.stderr[-500:]}


def font(size=18):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def plot(series: dict, title: str, path: Path, ylabel="m", W=900, H=420):
    """Minimal line plot (no matplotlib available): series name -> (x, y)."""
    im = Image.new("RGB", (W, H), (250, 250, 248))
    d = ImageDraw.Draw(im)
    L, Rr, T, B = 70, 20, 40, 50
    xs = np.concatenate([np.asarray(x) for x, _ in series.values()])
    ys = np.concatenate([np.asarray(y) for _, y in series.values()])
    x0, x1 = float(xs.min()), float(xs.max())
    y0, y1 = float(min(0.0, ys.min())), float(ys.max() * 1.1 + 1e-9)
    d.rectangle([L, T, W - Rr, H - B], outline=(120, 120, 120))
    for i in range(5):
        yv = y0 + (y1 - y0) * i / 4
        py = H - B - (H - B - T) * i / 4
        d.line([L - 4, py, L, py], fill=(120, 120, 120))
        d.text((6, py - 8), f"{yv * (1000 if ylabel == 'mm' else 1):.3g}", fill=(60, 60, 60), font=font(13))
    colors = [(37, 99, 235), (220, 38, 38), (22, 163, 74), (217, 119, 6), (124, 58, 237), (8, 145, 178)]
    for k, (name, (x, y)) in enumerate(series.items()):
        x, y = np.asarray(x), np.asarray(y)
        pts = [(L + (W - L - Rr) * (xi - x0) / max(x1 - x0, 1e-9), H - B - (H - B - T) * (yi - y0) / max(y1 - y0, 1e-9))
               for xi, yi in zip(x, y)]
        d.line(pts, fill=colors[k % len(colors)], width=3)
        d.text((L + 10 + 230 * (k % 3), T + 6 + 18 * (k // 3)), name, fill=colors[k % len(colors)], font=font(15))
    d.text((L, 8), title, fill=(20, 20, 20), font=font(18))
    d.text((W // 2 - 30, H - 30), "time (s)", fill=(60, 60, 60), font=font(14))
    d.text((6, T - 22), ylabel, fill=(60, 60, 60), font=font(14))
    im.save(path)


def main():
    t_start = time.time()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "renders").mkdir(exist_ok=True)
    (OUT / "glb").mkdir(exist_ok=True)
    (OUT / "dna").mkdir(exist_ok=True)
    (OUT / "reports").mkdir(exist_ok=True)
    summary = {}

    # ---------------------------------------------------------------- A: baseline character
    log("== Demonstration A: baseline character")
    ada = D.new_dna("female", name="ada", age_years=29)
    ada = D.set_trait(ada, "appearance.hair_style", "long")
    ada = D.set_trait(ada, "appearance.hair_color", "#3a2214")
    ada = D.set_trait(ada, "appearance.eye_color", "green")
    ada = D.set_trait(ada, "appearance.skin_tone", 0.3)
    ada = D.set_trait(ada, "wardrobe.outfit", ["tshirt", "shorts"])
    ada = D.set_trait(ada, "wardrobe.colors", {"tshirt": "#6d8fb3", "shorts": "#2a2f3d"})
    D.save_dna(ada, OUT / "dna/ada.dna.json")
    ch_a = build_character(D.to_spec(ada), "public", body_morphs=True)
    res_a = export_character(ada, OUT / "glb/ada.glb", physics=True, character=ch_a)
    chk = OUT / "reports/ada_walk8_python.json"
    chk.write_text(json.dumps(pose_check_data(ch_a, clip("walk", ch_a.skeleton.marks["height"] / 1.75), 8)))
    res_a["independent_node_check"] = node_check(OUT / "glb/ada.glb", chk)
    (OUT / "reports/A_baseline_export.json").write_text(json.dumps(res_a, indent=1, default=float))
    log("  export:", res_a["bytes"], "bytes", "validation ok:", res_a["validation"]["ok"],
        "node ok:", res_a["independent_node_check"].get("ok"),
        "max err:", res_a["independent_node_check"].get("maxPositionErrorVsPython_m"))
    imgs = [render_character(ch_a, yaw=y, text=t) for y, t in ((0, "A: front"), (35, "three-quarter"), (90, "side"), (180, "back"))]
    save(sheet(imgs, 4), OUT / "renders/A_baseline_turnaround.png")
    save(sheet([render_face(ch_a, yaw=0, text="face"), render_face(ch_a, yaw=40)], 2), OUT / "renders/A_baseline_face.png")
    summary["A"] = {"glb": "glb/ada.glb", "validation_ok": res_a["validation"]["ok"], "stats": res_a["validation"]["stats"],
                    "node_check_ok": res_a["independent_node_check"].get("ok"),
                    "node_max_position_error_m": res_a["independent_node_check"].get("maxPositionErrorVsPython_m"),
                    "body_quality": res_a["body_quality"], "parts": res_a["parts"]}

    # male baseline
    bram = D.new_dna("male", name="bram", age_years=41)
    bram = D.set_trait(bram, "appearance.skin_tone", 0.62)
    bram = D.set_trait(bram, "appearance.hair_color", "#16100c")
    bram = D.set_trait(bram, "wardrobe.outfit", ["tshirt", "pants"])
    bram = D.set_trait(bram, "wardrobe.colors", {"tshirt": "#3d6b45", "pants": "#3b3428"})
    D.save_dna(bram, OUT / "dna/bram.dna.json")
    ch_m = build_character(D.to_spec(bram), "public")
    res_m = export_character(bram, OUT / "glb/bram.glb", physics=True, character=ch_m)
    (OUT / "reports/A_male_export.json").write_text(json.dumps(res_m, indent=1, default=float))
    imgs = [render_character(ch_m, yaw=y, text=t) for y, t in ((0, "A: male front"), (35, "three-quarter"), (180, "back"))]
    save(sheet(imgs, 3), OUT / "renders/A_male_turnaround.png")
    summary["A_male"] = {"glb": "glb/bram.glb", "validation_ok": res_m["validation"]["ok"]}

    # determinism: same DNA -> identical bytes
    again = export_character(bram, OUT / "glb/_bram_repeat.glb", physics=True)
    summary["determinism"] = {"first_sha256": res_m["sha256"], "second_sha256": again["sha256"],
                              "identical": res_m["sha256"] == again["sha256"]}
    (OUT / "glb/_bram_repeat.glb").unlink()
    log("  determinism identical:", summary["determinism"]["identical"])

    # ---------------------------------------------------------------- B: customization
    log("== Demonstration B: customization (same topology, different geometry)")
    ada2 = D.load_dna(OUT / "dna/ada.dna.json")
    for k, v in {"body.height_m": 1.78, "body.body_fat": 0.6, "body.muscle": 0.2, "body.shoulder_width": 1.05,
                 "body.hip_width": 1.12, "body.breast_size": 1.8, "body.belly": 0.35, "body.leg_length": 0.95,
                 "face.jaw_width": 1.1, "face.nose_length": 1.2, "face.nose_width": 1.15, "face.eye_size": 0.9,
                 "face.lip_upper": 0.85, "face.chin_projection": 1.2, "face.cheek_fullness": 1.3,
                 "appearance.skin_tone": 0.75, "appearance.hair_style": "bun", "appearance.hair_color": "#9a9a9a"}.items():
        ada2 = D.set_trait(ada2, k, v)
    ada2["identity"]["name"] = "ada_variant"
    D.save_dna(ada2, OUT / "dna/ada_variant.dna.json")
    ch_b = build_character(D.to_spec(ada2), "public")
    res_b = export_character(ada2, OUT / "glb/ada_variant.glb", character=ch_b)
    va, vb = ch_a.body.verts, ch_b.body.verts
    disp = np.linalg.norm(vb - va, axis=1)
    summary["B"] = {"same_vertex_count": len(va) == len(vb), "same_triangles": bool(np.array_equal(ch_a.body.tris, ch_b.body.tris)),
                    "vertex_displacement_mean_m": float(disp.mean()), "vertex_displacement_max_m": float(disp.max()),
                    "fraction_moved_over_1mm": float((disp > 0.001).mean()),
                    "height_a_m": float(np.ptp(va[:, 1])), "height_b_m": float(np.ptp(vb[:, 1])),
                    "validation_ok": res_b["validation"]["ok"], "changed_traits": ada2["history"][-18:]}
    log("  displacement mean/max:", summary["B"]["vertex_displacement_mean_m"], summary["B"]["vertex_displacement_max_m"])
    save(sheet([render_character(ch_a, yaw=25, text="B: original"), render_character(ch_b, yaw=25, text="B: edited DNA"),
                render_face(ch_a, yaw=25), render_face(ch_b, yaw=25)], 4), OUT / "renders/B_customization.png")

    # ---------------------------------------------------------------- C: skeletal deformation
    log("== Demonstration C: skeletal deformation")
    walk = clip("walk", ch_a.skeleton.marks["height"] / 1.75)
    poses = [("contrapposto", POSES["contrapposto"], None), ("lunge", POSES["lunge"], None),
             ("walk frame 8", {j: q[8] for j, q in walk.rotations.items()}, walk.root_translation[8]),
             ("seated", POSES["seated"], np.array([0, -0.38, 0.0]))]
    imgs = []
    moved = {}
    from forge_character_forge.preview import posed_parts
    for name, pose, root in poses:
        lt = {"pelvis": root} if root is not None else None
        imgs.append(render_character(ch_a, pose=pose, yaw=30, local_trans=lt, text=f"C: {name}"))
        posed, _ = posed_parts(ch_a, pose, local_trans=lt, include={"body"})
        moved[name] = float(np.linalg.norm(posed[0][1] - ch_a.body.verts, axis=1).max())
    save(sheet(imgs, 4), OUT / "renders/C_poses.png")
    jaw = {"jaw": quat_from_euler(0.32, 0, 0)}
    fimgs = [render_face(ch_a, yaw=10, text="rest"), render_face(ch_a, morph_weights={"smile": 1.0}, yaw=10, text="morph: smile"),
             render_face(ch_a, morph_weights={"blink_l": 1.0, "blink_r": 1.0, "brow_raise": 1.0}, yaw=10, text="morph: blink+brow"),
             render_face(ch_a, pose=jaw, morph_weights={"lips_part": 1.0}, yaw=10, text="bone: jaw open")]
    save(sheet(fimgs, 4), OUT / "renders/C_face_controls.png")
    morph_stats = {n: {"max_disp_m": float(np.linalg.norm(d, axis=1).max()), "vertices_moved": int((np.linalg.norm(d, axis=1) > 1e-5).sum())}
                   for n, d in ch_a.body.morphs.items()}
    summary["C"] = {"max_vertex_motion_by_pose_m": moved, "morph_targets": morph_stats,
                    "independent_check": {k: res_a["independent_node_check"].get(k) for k in
                                          ("ok", "comparedVertices", "maxPositionErrorVsPython_m", "anim", "frame")}}

    # ---------------------------------------------------------------- D: image reconstruction
    log("== Demonstration D: image-to-3D reconstruction + full-body completion")
    truth = json.loads((REFS / "ground_truth.json").read_text())
    recon = {}
    cases = [("ref_full_front.png", None), ("ref_waist_up.png", None), ("ref_portrait.jpg", None),
             ("ref_seated.png", None), ("ref_stylized_drawing.png", None)]
    rec_imgs = []
    for fname, side in cases:
        t0 = time.time()
        ref = R.load_reference(REFS / fname, "front", authorized=True)
        dna_r, rep = R.reconstruct([ref], log=log)
        stem = Path(fname).stem
        D.save_dna(dna_r, OUT / f"dna/recon_{stem}.dna.json")
        obs = rep["observation"]
        b, f = D.to_spec(dna_r).body, D.to_spec(dna_r).face
        syn_mask = R.field_silhouette(b, f, cell=0.006)
        syn_sil = R.measure_silhouette(syn_mask)
        ov = R.overlay_image(obs, syn_sil, syn_mask)
        ch_r = build_character(D.to_spec(dna_r), "public")
        render = render_character(ch_r, yaw=20, text=f"D: from {fname}")
        h = 900
        ov_im = Image.fromarray(ov)
        ov_im = ov_im.resize((max(1, int(ov_im.width * h / ov_im.height)), h))
        ov_arr = label(np.asarray(ov_im), "yellow: segmentation\ncyan: fitted model")
        rec_imgs.append((ov_arr, render))
        errs = {}
        if fname in truth and "body" in truth[fname]:
            for k, (v, p, c, n) in rep["estimates"].items():
                g, a = k.split(".", 1)
                if g in ("body", "face") and isinstance(v, (int, float)):
                    errs[k] = {"estimate": v, "truth": truth[fname][g][a], "abs_error": round(abs(v - truth[fname][g][a]), 4),
                               "provenance": p, "confidence": c}
        exp = None
        if fname in ("ref_portrait.jpg", "ref_full_front.png"):
            exp = export_character(dna_r, OUT / f"glb/recon_{stem}.glb", character=ch_r)
        recon[fname] = {"seconds": round(time.time() - t0, 1), "posture": obs.posture, "style": obs.style,
                        "regions": obs.regions, "notes": obs.notes, "segmentation": obs.seg,
                        "provenance_summary": D.provenance_summary(dna_r), "fit_residual_hu": dna_r["reconstruction"]["fit_residual_head_units"],
                        "body_type_prior": rep["prior"], "waist_hip_ratio": rep["waist_hip_ratio"],
                        "observed": sorted(k for k, t in dna_r["traits"].items() if t["provenance"] == "observed"),
                        "errors_vs_ground_truth": errs, "glb_validation": exp["validation"]["ok"] if exp else None,
                        "full_body_geometry": {"vertices": int(len(ch_r.body.verts)),
                                               "height_m": float(np.ptp(ch_r.body.verts[:, 1]))}}
        log(f"  {fname}: {recon[fname]['provenance_summary']} posture={obs.posture} style={obs.style}")
    tiles = []
    for ov, rend in rec_imgs:
        tiles += [ov, rend]
    w = max(t.shape[1] for t in tiles)
    tiles = [np.pad(t, ((0, 0), (0, w - t.shape[1]), (0, 0)), constant_values=20) for t in tiles]
    save(sheet(tiles, 4), OUT / "renders/D_reconstruction.png")
    # locks + targeted regeneration on a reconstructed DNA
    d0 = D.load_dna(OUT / "dna/recon_ref_portrait.dna.json")
    d1 = D.lock(d0, ["appearance.hair_color", "appearance.skin_tone", "body.shoulder_width"])
    d2 = D.regenerate(d1, "body", seed=11)
    d2 = D.regenerate(d2, "appearance", seed=11)
    kept = {k: (d1["traits"][k]["value"], d2["traits"][k]["value"]) for k in ("appearance.hair_color", "appearance.skin_tone", "body.shoulder_width")}
    changed = d2["history"][-1]["changed"] + d2["history"][-2]["changed"]
    d3 = D.set_trait(d2, "body.leg_length", 1.08, lock=True, note="user corrected inferred leg length")
    D.save_dna(d3, OUT / "dna/recon_portrait_locked_regenerated.dna.json")
    ch_l = build_character(D.to_spec(d3), "public")
    save(sheet([render_character(build_character(D.to_spec(d0), "public"), yaw=20, text="portrait recon"),
                render_character(ch_l, yaw=20, text="locked traits kept,\nunlocked regenerated,\nleg length user-edited")], 2),
         OUT / "renders/D_locks_regenerate.png")
    summary["D"] = {"cases": recon, "locks": {"kept_values": kept, "regenerated_traits": sorted(changed)[:40],
                                              "locked_unchanged": all(a == b for a, b in kept.values())}}

    # ---------------------------------------------------------------- E: secondary physics
    log("== Demonstration E: secondary physics")
    sk = ch_a.skeleton
    breast = [c for c in P.default_chains(sk) if c.kind == "breast"]
    jump = clip("jump", sk.marks["height"] / 1.75)
    series, amps = {}, {}
    for label_, outfit, params in (("no support f=2.4Hz z=0.22", (), None), ("t-shirt", ("tshirt",), None),
                                   ("bra", ("bra",), None),
                                   ("stiff f=4Hz z=0.5", (), {"breast": P.SpringParams(4.0, 0.5, 22.0, 0.035)}),
                                   ("soft f=1.6Hz z=0.12", (), {"breast": P.SpringParams(1.6, 0.12, 30.0, 0.035)})):
        chains = [c for c in P.default_chains(sk, params) if c.kind == "breast"]
        r = P.simulate(sk, jump, chains, containment=P.garment_containment(sk, outfit, chains))
        series[label_] = (jump.times, r.tip_offsets["breast_l"])
        amps[label_] = {"amplitude_m": P.amplitude(r, "breast_l"), "max_angle_deg": float(r.angles_deg["breast_l"].max()),
                        "stable": r.stable}
    plot(series, "E1: breast tip deviation from animated target during a jump (simulated)", OUT / "renders/E_breast_jump.png", "mm")
    # developer anatomy chain (numerical, adult male DNA), collision on/off, garment support
    dev = D.load_dna(OUT / "dna/bram.dna.json")
    spec_d = D.to_spec(dev)
    from forge_character_forge.anatomy import build_field
    from forge_character_forge.skeleton import build_skeleton
    skd = build_skeleton(spec_d.body, spec_d.face, spec_d.genital)
    build_field(spec_d.body, spec_d.face, skd)
    gchains = [c for c in P.default_chains(skd) if c.kind in ("penis", "testicle")]
    walk_d = clip("walk", skd.marks["height"] / 1.75)
    dev_res = {}
    series2 = {}
    for label_, outfit, collide in (("nude, colliders on", (), True), ("nude, colliders off", (), False),
                                    ("briefs support", ("briefs",), True)):
        r = P.simulate(skd, walk_d, gchains, containment=P.garment_containment(skd, outfit, gchains), collide=collide)
        dev_res[label_] = {"amplitude_m": {b: round(P.amplitude(r, b), 4) for b in r.rotations},
                           "raw_penetration_m": r.raw_max_penetration, "penetration_after_constraints_m": r.max_penetration,
                           "stable": r.stable}
        series2[label_] = (walk_d.times, r.angles_deg["penis_02"])
    plot(series2, "E2: developer chain (penis_02) angular deviation while walking (simulated)", OUT / "renders/E_dev_chain_walk.png", "deg")
    # baked secondary motion rendered on the clothed public character
    jb = P.bake(jump, P.simulate(sk, jump, breast, containment=P.garment_containment(sk, ("tshirt",), breast)))
    frames = []
    from forge_character_forge.preview import render_character as rc
    m = sk.marks
    tgt = (0.0, m["y_hip"] + 0.45 * m["torso_len"], 0.0)
    for fr in (14, 18, 21, 24):
        pose_s = {j: q[fr] for j, q in jb.rotations.items()}
        pose_n = {j: q[fr] for j, q in jump.rotations.items()}
        lt = {"pelvis": jump.root_translation[fr]}
        a_ = rc(ch_a, pose=pose_n, local_trans=lt, yaw=70, W=300, H=380, target=(tgt[0], tgt[1] + jump.root_translation[fr][1], 0), distance=1.5, text=f"f{fr} no physics")
        b_ = rc(ch_a, pose=pose_s, local_trans=lt, yaw=70, W=300, H=380, target=(tgt[0], tgt[1] + jump.root_translation[fr][1], 0), distance=1.5, text=f"f{fr} simulated")
        frames += [a_, b_]
    save(sheet(frames, 8), OUT / "renders/E_baked_secondary_frames.png")
    dev_glb = None
    dev_dna = D.set_trait(dev, "wardrobe.outfit", ["briefs"])
    res_dev = export_character(dev_dna, OUT / "glb/bram_developer.dev.glb", profile="developer", clips=("walk", "jump"), physics=True)
    dev_glb = {"path": "glb/bram_developer.dev.glb", "validation_ok": res_dev["validation"]["ok"],
               "dev_parts": [p for p in res_dev["parts"] if p.startswith("dev_")], "physics": res_dev["physics"]}
    pub_names = json.dumps(res_a["parts"])
    summary["E"] = {"breast_jump": amps, "developer_chain_walk": dev_res, "developer_glb": dev_glb,
                    "public_glb_has_dev_parts": "dev_" in pub_names}
    log("  breast amplitudes:", {k: round(v["amplitude_m"], 4) for k, v in amps.items()})

    summary["runtime_seconds"] = round(time.time() - t_start, 1)
    (OUT / "reports/summary.json").write_text(json.dumps(summary, indent=1, default=float))
    (OUT / "reports/demo_log.txt").write_text("\n".join(LOG) + "\n")
    log("done in", summary["runtime_seconds"], "s")


if __name__ == "__main__":
    main()
