"""Stolen Fire E2 verification: foot locks off vs on for v3 Studio exports (measurements, plots, renders).

    python3 tools/footlock_report.py <off dir> <on dir> <out dir> [character ...]

Each dir holds <character>.glb exported by the Character Studio (tools/studio_v3_footlock.mjs writes them), the
off ones with foot locks off (the default) and the on ones with them on. Everything is read back from the GLBs,
independently of the studio: forward kinematics of the exported channels, the lock spans and ground speed from
asset.extras.forge.animation_corrections, posed meshes from tools/glb_playback.mjs. Writes report.json, plots and
renders into <out dir>.
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from forge_character_forge.render import Camera, DrawItem, label, rasterize, save, sheet  # noqa: E402
from forge_character_forge.validate import accessor, read_glb, validate_glb  # noqa: E402
from forge_character_forge.v3 import footlock as FL  # noqa: E402

CLIPS = ("walk", "run")
LEG_JOINTS = [j for leg in FL.LEGS for j in leg]
FPS = 30
EX = np.array([1.0, 0.0, 0.0])


class Glb:
    def __init__(self, path):
        self.path = Path(path)
        self.g, self.b = read_glb(path)
        self.nodes = self.g["nodes"]
        self.joints = self.g["skins"][0]["joints"]
        self.names = [self.nodes[j]["name"] for j in self.joints]
        pos = {j: k for k, j in enumerate(self.joints)}
        par = {c: i for i, n in enumerate(self.nodes) for c in n.get("children", [])}
        self.parents = [pos.get(par.get(j), -1) for j in self.joints]
        self.local = np.array([self.nodes[j].get("translation", [0, 0, 0]) for j in self.joints], float)
        self.rest = np.zeros_like(self.local)
        for k, p in enumerate(self.parents):
            self.rest[k] = self.local[k] + (self.rest[p] if p >= 0 else 0)
        self.anims = {}
        for a in self.g["animations"]:
            d = {"times": None, "rot": {}, "tr": {}, "out_acc": {}}
            for ch in a["channels"]:
                s = a["samplers"][ch["sampler"]]
                n = self.nodes[ch["target"]["node"]]["name"]
                d["times"] = accessor(self.g, self.b, s["input"])
                key = "rot" if ch["target"]["path"] == "rotation" else "tr"
                d[key][n] = accessor(self.g, self.b, s["output"]).astype(float)
                d["out_acc"][(n, ch["target"]["path"])] = s["output"]
            self.anims[a["name"]] = d
        self.forge = self.g["asset"].get("extras", {}).get("forge", {})

    def world(self, clip):
        """W (F, J, 4), P (F, J, 3) of every joint at every key."""
        d = self.anims[clip]
        F = len(d["times"])
        W, P = np.zeros((F, len(self.names), 4)), np.zeros((F, len(self.names), 3))
        for f in range(F):
            for k, n in enumerate(self.names):
                p = self.parents[k]
                t = d["tr"][n][f] if n in d["tr"] else self.local[k]
                q = d["rot"][n][f] if n in d["rot"] else FL._ID
                if p < 0:
                    W[f, k], P[f, k] = q, t
                else:
                    W[f, k], P[f, k] = FL.qmul(W[f, p], q), P[f, p] + FL.qrot(W[f, p], t)
        return W, P


def qangle(a, b):  # normalised first: the clips' float32 turns are unit to ~3e-8 only, enough to read as 0.03 degrees
    return math.degrees(2 * math.acos(min(1.0, abs(float(FL._unit(a) @ FL._unit(b))))))


def leg_metrics(off: Glb, on: Glb, clip: str) -> dict:
    rec = on.forge.get("animation_corrections", {}).get("foot_lock", {}).get("clips", {}).get(clip)
    if rec is None:
        return {"error": "no foot_lock record for this clip"}
    v = rec["ground_speed_m_s"]
    out = {"ground_speed_m_s": v, "feet": {}}
    Wo, Po = off.world(clip)
    Wn, Pn = on.world(clip)
    F = len(Po)
    ix = {n: i for i, n in enumerate(on.names)}
    for U, L, B in FL.LEGS:
        span = rec["locked"].get(B)
        r = {"locked": span}
        iU, iL, iB = ix[U], ix[L], ix[B]
        # bone lengths and knees, every frame
        l1, l2 = (float(np.linalg.norm(on.rest[ix[x]] - on.rest[ix[y]])) for x, y in ((L, U), (B, L)))
        r["bone_length_max_error_m"] = float(max(np.abs(np.linalg.norm(Pn[:, iL] - Pn[:, iU], axis=1) - l1).max(),
                                                 np.abs(np.linalg.norm(Pn[:, iB] - Pn[:, iL], axis=1) - l2).max()))

        def knee(W, P):
            d1, d2 = P[:, iL] - P[:, iU], P[:, iB] - P[:, iL]
            flex = np.degrees(np.arccos(np.clip((d1 * d2).sum(1) / (np.linalg.norm(d1, axis=1) * np.linalg.norm(d2, axis=1)), -1, 1)))
            axis = np.array([FL.qrot(W[f, iU], EX) for f in range(F)])
            return flex, np.sign((np.cross(d1, d2) * axis).sum(1))
        fo, so = knee(Wo, Po)
        fn, sn = knee(Wn, Pn)
        r["knee_flex_deg"] = {"before_min": float(fo.min()), "after_min": float(fn.min()), "after_max": float(fn.max())}
        r["knee_bend_direction_same_as_source_all_frames"] = bool((so == sn).all())
        if not span:
            out["feet"][B] = r
            continue
        ls = span[0]
        n = span[1]
        k_lock = list(range(ls, ls + n))
        k_in = list(range(ls - FL.BLEND + 1, ls))
        k_out = list(range(ls + n, ls + n + FL.BLEND - 1))

        def g(P, k):  # the ankle in the ground frame (the belt moving back at v)
            return P[k % F, iB] + np.array([0.0, 0.0, v * k / FPS])

        for tag, P, W in (("before", Po, Wo), ("after", Pn, Wn)):
            ref = g(P, ls)
            dl = np.array([g(P, k) - ref for k in k_lock])
            r[f"locked_ankle_drift_{tag}_mm"] = {"max_3d": float(np.linalg.norm(dl, axis=1).max() * 1000),
                                                 "max_horizontal": float(np.linalg.norm(dl[:, [0, 2]], axis=1).max() * 1000),
                                                 "max_vertical": float(np.abs(dl[:, 1]).max() * 1000)}
            r[f"locked_foot_rotation_drift_{tag}_deg"] = float(max(qangle(W[k % F, iB], W[ls % F, iB]) for k in k_lock))
            tr = [np.linalg.norm(g(P, k) - g(P, ls)) for k in k_in] + [np.linalg.norm(g(P, k) - g(P, ls + n - 1)) for k in k_out]
            r[f"transition_ankle_offset_{tag}_mm"] = float(max(tr) * 1000) if tr else 0.0
        r["locked_knee_flex_after_min_deg"] = float(min(fn[k % F] for k in k_lock))
        out["feet"][B] = r
    # continuity, per leg joint: the largest step between neighbouring keys of its world rotation (what is seen) and
    # of its local channel (what the file stores), inside the clip and across the loop seam (last key -> first key);
    # and the ankle's largest acceleration in the ground frame, seam included
    cont = {}
    for j in LEG_JOINTS:
        i = ix[j]
        row = {}
        for tag, W, q in (("before", Wo, off.anims[clip]["rot"][j]), ("after", Wn, on.anims[clip]["rot"][j])):
            sw = [qangle(W[f, i], W[(f + 1) % F, i]) for f in range(F)]
            sl = [qangle(q[f], q[(f + 1) % F]) for f in range(F)]
            row[f"{tag}_world_max_step_deg"], row[f"{tag}_world_seam_step_deg"] = max(sw[:-1]), sw[-1]
            row[f"{tag}_local_max_step_deg"], row[f"{tag}_local_seam_step_deg"] = max(sl[:-1]), sl[-1]
        cont[j] = row
    for B in ("foot_l", "foot_r"):
        i = ix[B]
        for tag, P in (("before", Po), ("after", Pn)):
            G = np.array([P[f % F, i] + np.array([0.0, 0.0, v * f / FPS]) for f in range(F + 2)])
            acc = np.linalg.norm(G[2:] - 2 * G[1:-1] + G[:-2], axis=1) * FPS * FPS
            cont[B][f"{tag}_ankle_max_accel_m_s2"] = float(acc.max())
    out["continuity"] = cont
    # quaternions as written
    qs = np.concatenate([on.anims[clip]["rot"][j] for j in LEG_JOINTS])
    out["quaternions"] = {"max_norm_error": float(np.abs(np.linalg.norm(qs, axis=1) - 1).max()), "nan": bool(np.isnan(qs).any()),
                          "hemisphere_flips_inside_clip": int(sum(int(((on.anims[clip]["rot"][j][1:] * on.anims[clip]["rot"][j][:-1]).sum(1) < 0).sum()) for j in LEG_JOINTS))}
    # Python reference applied to the off export vs the browser's on export
    d = off.anims[clip]
    pel = off.names.index("pelvis")
    root = d["tr"]["pelvis"] - off.local[pel]
    py, _ = FL.lock_clip(off.names, off.parents, off.rest, d["rot"], root, FPS)
    out["python_vs_browser_max_quat_diff"] = float(max(np.minimum(np.abs(py[j] - on.anims[clip]["rot"][j]), np.abs(py[j] + on.anims[clip]["rot"][j])).max() for j in LEG_JOINTS))
    return out


def contract(off: Glb, on: Glb) -> dict:
    """What differs between the off and on files besides the six leg rotation channels of walk and run."""
    changed = {on.anims[c]["out_acc"][(j, "rotation")] for c in CLIPS for j in LEG_JOINTS if (j, "rotation") in on.anims[c]["out_acc"]}
    go, gn = off.g, on.g
    res = {"changed_accessors": sorted(changed)}
    res["same_animation_names_and_order"] = [a["name"] for a in go["animations"]] == [a["name"] for a in gn["animations"]]
    res["same_channels"] = all(a["channels"] == b["channels"] and len(a["samplers"]) == len(b["samplers"]) for a, b in zip(go["animations"], gn["animations"]))
    res["same_accessor_definitions"] = go["accessors"] == gn["accessors"] and go["bufferViews"] == gn["bufferViews"]
    diff = []
    for i in range(len(go["accessors"])):
        if not np.array_equal(accessor(go, off.b, i), accessor(gn, on.b, i)):
            diff.append(i)
    res["accessors_with_different_data"] = diff
    res["only_leg_rotations_of_walk_and_run_differ"] = set(diff) <= changed
    for k in ("nodes", "meshes", "skins", "materials", "scenes"):
        res[f"same_{k}"] = go.get(k) == gn.get(k)
    fo = dict(off.forge)
    fn = {k: v for k, v in on.forge.items() if k != "animation_corrections"}
    res["same_forge_metadata_apart_from_animation_corrections"] = fo == fn
    return res


def posed_min_y(glb: Glb, clip: str, F: int, tmp: Path) -> dict:
    """Lowest posed body vertex per frame: the whole body and each foot (rest vertices below 12 cm, |x| > 5 cm)."""
    o = tmp / f"{glb.path.parent.name}_{glb.path.stem}_{clip}"
    subprocess.run(["node", str(ROOT / "tools/glb_playback.mjs"), str(glb.path), str(o), "--anim", clip, "--meshes", "body",
                    "--frames", ",".join(map(str, range(F)))], check=True, capture_output=True)
    m = next(m for m in glb.g["meshes"] if m["name"] == "body")
    rp = accessor(glb.g, glb.b, m["primitives"][0]["attributes"]["POSITION"])
    sets = {"body": np.ones(len(rp), bool), "foot_l": (rp[:, 1] < 0.12) & (rp[:, 0] > 0.05), "foot_r": (rp[:, 1] < 0.12) & (rp[:, 0] < -0.05)}
    out = {k: [] for k in sets}
    for f in range(F):
        y = np.fromfile(o / f"body_f{f}.f4", "<f4").reshape(-1, 3)[:, 1]
        for k, sel in sets.items():
            out[k].append(float(y[sel].min()))
    return out


def posed_body(glb: Path, clip: str, frames, tmp: Path):
    o = tmp / f"pose_{glb.parent.name}_{glb.stem}_{clip}"
    subprocess.run(["node", str(ROOT / "tools/glb_playback.mjs"), str(glb), str(o), "--anim", clip, "--meshes", "body",
                    "--frames", ",".join(map(str, frames))], check=True, capture_output=True)
    tri = np.fromfile(o / "body_idx.u4", "<u4").reshape(-1, 3).astype(np.int64)
    return {f: np.fromfile(o / f"body_f{f}.f4", "<f4").reshape(-1, 3).astype(float) for f in frames}, tri


# --- plots (Pillow; no plotting library in the environment) --------------------------------------------------

def plot(panels, path, title):
    """panels: [(title, [(xs, ys, colour, width, marker_idx)], xlabel, ylabel)] drawn on one shared scale per panel."""
    W, H, pad = 420, 300, 46
    imgs = []
    for ptitle, series, xl, yl in panels:
        im = Image.new("RGB", (W, H), (250, 250, 248))
        d = ImageDraw.Draw(im)
        xs = np.concatenate([s[0] for s in series])
        ys = np.concatenate([s[1] for s in series])
        x0, x1 = float(xs.min()), float(xs.max())
        y0, y1 = float(ys.min()), float(ys.max())
        mx, my = (x1 - x0) * 0.05 or 0.01, (y1 - y0) * 0.08 or 0.01
        x0, x1, y0, y1 = x0 - mx, x1 + mx, y0 - my, y1 + my
        X = lambda x: pad + (x - x0) / (x1 - x0) * (W - pad - 12)  # noqa: E731
        Y = lambda y: H - pad - (y - y0) / (y1 - y0) * (H - pad - 26)  # noqa: E731
        d.rectangle([pad, 26, W - 12, H - pad], outline=(170, 170, 170))
        for t in np.linspace(0, 1, 5):
            gx, gy = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
            d.line([X(gx), 26, X(gx), H - pad], fill=(228, 228, 228))
            d.line([pad, Y(gy), W - 12, Y(gy)], fill=(228, 228, 228))
            d.text((X(gx) - 14, H - pad + 4), f"{gx:.2f}", fill=(90, 90, 90))
            d.text((4, Y(gy) - 6), f"{gy:.3f}", fill=(90, 90, 90))
        for sx, sy, col, w, mark in series:
            pts = [(X(a), Y(b)) for a, b in zip(sx, sy)]
            d.line(pts, fill=col, width=w)
            for i in mark:
                x, y = pts[i]
                d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=col)
        d.text((pad, 6), ptitle, fill=(20, 20, 20))
        d.text((W // 2 - 40, H - 16), xl, fill=(60, 60, 60))
        d.text((4, 10), yl, fill=(60, 60, 60))
        imgs.append(np.asarray(im))
    cols = 2
    grid = sheet(imgs, cols)
    head = np.full((28, grid.shape[1], 3), 250, np.uint8)
    out = Image.fromarray(np.concatenate([head, grid]))
    ImageDraw.Draw(out).text((10, 8), title, fill=(20, 20, 20))
    out.save(path)


GREY, ACCENT = (150, 150, 150), (200, 90, 20)


def trajectory_plots(chars, glbs, metrics, out: Path):
    for clip, zoom in ((c, z) for c in CLIPS for z in (False, True)):
        panels = []
        for ch in chars:
            off, on = glbs[ch]
            v = metrics[ch][clip]["ground_speed_m_s"]
            ix = on.names.index
            for B in ("foot_l", "foot_r"):
                span = metrics[ch][clip]["feet"][B]["locked"]
                series = []
                for P, col, w in ((off.world(clip)[1], GREY, 2), (on.world(clip)[1], ACCENT, 2)):
                    F = len(P)
                    k0 = span[0] if span else 0
                    if zoom and span:  # the lock and its blends only
                        ks = list(range(k0 - FL.ROT_BLEND, k0 + span[1] + FL.ROT_BLEND))
                    else:
                        ks = list(range(k0 - F // 2, k0 + F // 2 + 1))  # one cycle around the lock, unwrapped
                    z = np.array([P[k % F, ix(B), 2] + v * k / FPS for k in ks])
                    y = np.array([P[k % F, ix(B), 1] for k in ks])
                    mark = [i for i, k in enumerate(ks) if span and span[0] <= k < span[0] + span[1]]
                    series.append((z, y, col, w, mark))
                panels.append((f"{ch} {B} (grey before, orange after; dots = locked frames)", series, "ground-frame z (m)", "ankle y (m)"))
        plot(panels, out / f"trajectory_{clip}{'_stance' if zoom else ''}.png",
             f"E2 {clip}: ankle path in the ground frame (belt at the clip's stride speed), {'the lock and its blends' if zoom else 'one cycle'}")


def floor_plots(chars, floors, metrics, out: Path):
    for clip in CLIPS:
        panels = []
        for ch in chars:
            fo, fn = floors[ch][clip]
            F = len(fo)
            series = [(np.arange(F), np.array(fo) * 1000, GREY, 2, []), (np.arange(F), np.array(fn) * 1000, ACCENT, 2, [])]
            panels.append((f"{ch}: lowest body vertex per frame", series, "frame", "min y (mm)"))
        plot(panels, out / f"floor_{clip}.png", f"E2 {clip}: floor contact (lowest skinned body vertex; < 0 = below the floor)")


def renders(chars, glbs, metrics, out: Path, tmp: Path):
    """Side views of the left leg through its locked stance, in the ground frame (the body shifted forward by the
    belt so a planted foot stands still); a small cube marks the ankle at the first locked frame."""
    tiles = []
    for ch in chars:
        off, on = glbs[ch]
        m = metrics[ch]["walk"]
        span = m["feet"]["foot_l"]["locked"]
        if not span:
            continue
        v, ls, n = m["ground_speed_m_s"], span[0], span[1]
        F = len(on.anims["walk"]["times"])
        ks = [ls - FL.BLEND + 1, ls, ls + n // 2, ls + n - 1, ls + n + FL.BLEND - 2]
        P = on.world("walk")[1]
        mark = P[ls % F, on.names.index("foot_l")] + np.array([0, 0, v * ls / FPS])
        cube = np.array([[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)], float) * 0.008 + mark
        ctri = np.array([[0, 1, 3], [0, 3, 2], [4, 6, 7], [4, 7, 5], [0, 4, 5], [0, 5, 1], [2, 3, 7], [2, 7, 6], [0, 2, 6], [0, 6, 4], [1, 5, 7], [1, 7, 3]])
        for tag, glb in (("before", off), ("after", on)):
            poses, tri = posed_body(glb.path, "walk", sorted({k % F for k in ks}), tmp)
            for k in ks:
                V = poses[k % F] + np.array([0, 0, v * k / FPS])
                cam = Camera(yaw_deg=90, pitch_deg=4, target=(mark[0], 0.25, mark[2]), distance=1.5, fov_deg=30)
                im = rasterize([DrawItem(V, tri, color=(0.72, 0.56, 0.48), sss=0.3), DrawItem(cube, ctri, color=(0.1, 0.5, 0.9))], cam, W=260, H=300,
                               background=(0.42, 0.43, 0.46), ground_y=0.0)
                state = "blend in" if k < ls else "blend out" if k >= ls + n else "locked"
                tiles.append(label(im, f"{ch} {tag} f{k % F} ({state})", size=11))
    save(sheet(tiles, 5), out / "renders_walk_left_foot.jpg")


def main():
    off_dir, on_dir, out = (Path(a) for a in sys.argv[1:4])
    chars = sys.argv[4:] or ["neutral", "id_a", "long_legs"]
    out.mkdir(parents=True, exist_ok=True)
    report = {"characters": chars, "clips": list(CLIPS), "method_version": FL.VERSION}
    glbs, metrics, floors = {}, {}, {}
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for ch in chars:
            off, on = Glb(off_dir / f"{ch}.glb"), Glb(on_dir / f"{ch}.glb")
            glbs[ch] = (off, on)
            r = {"validator_off": validate_glb(off.path, "public"), "validator_on": validate_glb(on.path, "public"), "contract": contract(off, on)}
            ind = subprocess.run(["node", str(ROOT / "tools/glb_independent_check.mjs"), str(on.path), "--anim", "walk", "--frame", "12"], capture_output=True, text=True)
            r["independent_check_on"] = {"exit": ind.returncode, "ok": ind.returncode == 0}
            metrics[ch], floors[ch] = {}, {}
            for clip in CLIPS:
                metrics[ch][clip] = leg_metrics(off, on, clip)
                F = len(on.anims[clip]["times"])
                po, pn = posed_min_y(off, clip, F, tmp), posed_min_y(on, clip, F, tmp)
                fo, fn = po["body"], pn["body"]
                floors[ch][clip] = (fo, fn)
                fl = {"before_min_body_y_mm": min(fo) * 1000, "after_min_body_y_mm": min(fn) * 1000,
                      "before_max_lowest_vertex_mm": max(fo) * 1000, "after_max_lowest_vertex_mm": max(fn) * 1000}
                for B, d in metrics[ch][clip]["feet"].items():  # the locked foot's own sole height over its locked frames
                    if d.get("locked"):
                        ls, n = d["locked"]
                        ks = [(ls + i) % F for i in range(n)]
                        fl[f"{B}_locked_sole_y_mm"] = {"before_min": min(po[B][k] for k in ks) * 1000, "before_max": max(po[B][k] for k in ks) * 1000,
                                                      "after_min": min(pn[B][k] for k in ks) * 1000, "after_max": max(pn[B][k] for k in ks) * 1000}
                metrics[ch][clip]["floor"] = fl
            r["clips"] = metrics[ch]
            report[ch] = r
        trajectory_plots(chars, glbs, metrics, out)
        floor_plots(chars, floors, metrics, out)
        renders(chars, glbs, metrics, out, tmp)
    (out / "report.json").write_text(json.dumps(report, indent=1, default=float))
    print(json.dumps(report, indent=1, default=float)[:20000])


if __name__ == "__main__":
    main()
