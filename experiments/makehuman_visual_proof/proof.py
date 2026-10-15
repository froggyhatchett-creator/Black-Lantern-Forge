"""Visual proof: MakeHuman hm08 (CC0 assets) head vs the current Forge v2 head, matched renders.

Experiment only: reads the downloaded CC0 asset files, uses Forge's existing software rasterizer and v2 character build
for comparison, and writes images plus measurements to ./out.  No MakeHuman/MPFB code is used; parsers here are new.
Matched conditions: same rasterizer and lights, flat skin color for both, no hair/brows/lashes/garments on either,
camera aimed at the eye midpoint at a distance proportional to each head's interpupillary distance.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
sys.path.insert(0, str(ROOT))
from forge_character_forge.appearance import AppearanceParams  # noqa: E402
from forge_character_forge.character import CharacterSpec, build_character  # noqa: E402
from forge_character_forge.params import preset  # noqa: E402
from forge_character_forge.preview import posed_parts  # noqa: E402
from forge_character_forge.render import Camera, DrawItem, _project, rasterize  # noqa: E402

A = HERE / "assets" / "data"
OUT = HERE / "out"
SKIN = tuple(AppearanceParams(skin_tone=0.3).skin_linear())
IRIS = (0.20, 0.09, 0.03)
W, H = 520, 600


# ---------------------------------------------------------------- MakeHuman parsing (new code, CC0 data)
def load_obj(path, scale=0.1):
    """Vertices (meters, Y up), and faces per group as vertex-index lists (quads or tris)."""
    verts, groups, cur = [], {}, None
    for line in open(path):
        if line.startswith("v "):
            verts.append([float(x) for x in line.split()[1:4]])
        elif line.startswith("g "):
            cur = line.split()[1]
            groups.setdefault(cur, [])
        elif line.startswith("f "):
            groups.setdefault(cur, []).append([int(tok.split("/")[0]) - 1 for tok in line.split()[1:]])
    return np.array(verts) * scale, groups


def tris_of(faces):
    t = []
    for f in faces:
        for k in range(1, len(f) - 1):
            t.append((f[0], f[k], f[k + 1]))
    return np.array(t, np.int64)


def fit_mhclo(path, base):
    """Place a proxy (eyes) on the base mesh from its mhclo vertex references."""
    lines = [l.split() for l in open(path) if l.strip() and not l.startswith("#")]
    scale = {}
    for l in lines:
        if l[0] in ("x_scale", "y_scale", "z_scale"):
            a, b, den = int(l[1]), int(l[2]), float(l[3])
            ax = "xyz".index(l[0][0])
            scale[ax] = abs(base[a, ax] - base[b, ax]) / den
    i = next(k for k, l in enumerate(lines) if l[0] == "verts")
    refs = []
    for l in lines[i + 1:]:
        if len(l) != 9:
            break
        refs.append([float(x) for x in l])
    r = np.array(refs)
    idx, w, d = r[:, :3].astype(int), r[:, 3:6], r[:, 6:9]
    s = np.array([scale[0], scale[1], scale[2]])
    return (base[idx] * w[:, :, None]).sum(1) + d * s


def bvh_frame_rotations(path, names_json, unit):
    """Per-joint (X, Y, Z) rotation in degrees for one named pose-unit frame."""
    lines = open(path).read().split("\n")
    order, chans = [], []
    for l in lines:
        tok = l.split()
        if tok and tok[0] in ("ROOT", "JOINT"):
            order.append(tok[1])
        elif tok and tok[0] == "CHANNELS":
            chans.append(tok[2:])
    m = lines.index(next(l for l in lines if l.startswith("MOTION")))
    frames = [list(map(float, l.split())) for l in lines[m + 3:] if l.strip()]
    fi = json.load(open(names_json))["framemapping"].index(unit)
    vals, out, k = frames[fi], {}, 0
    for name, ch in zip(order, chans):
        rot = {c[0]: vals[k + j] for j, c in enumerate(ch) if c.endswith("rotation")}
        k += len(ch)
        if any(abs(v) > 1e-3 for v in rot.values()):
            out[name] = (rot.get("X", 0.0), rot.get("Y", 0.0), rot.get("Z", 0.0))
    return out


def rot_x(deg):
    a = np.radians(deg)
    return np.array([[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]])


def mh_lid_close(base, skel, weights, rots, sign):
    """Skin only the eyelid bones: rotate weighted vertices about each bone head around the lateral (X) axis.
    BVH rest frames are axis-aligned; X is lateral in both the BVH and the mesh, so only the sign is a convention."""
    v = base.copy()
    joints = skel["joints"]
    for bone, (rx, ry, rz) in rots.items():
        if bone not in weights or bone not in skel["bones"]:
            continue
        head = base[joints[skel["bones"][bone]["head"]]].mean(0)
        R = rot_x(sign * rx)
        wl = np.array(weights[bone])
        idx, w = wl[:, 0].astype(int), wl[:, 1]
        moved = (base[idx] - head) @ R.T + head
        v[idx] += (moved - base[idx]) * w[:, None]
    return v


# ---------------------------------------------------------------- helpers
def eye_colors(verts, center):
    d = verts - center
    d /= np.linalg.norm(d, axis=1, keepdims=True)
    ang = np.arccos(np.clip(d[:, 2], -1, 1))
    iris = ang < 0.48
    pupil = ang < 0.19
    c = np.tile(np.array([0.80, 0.77, 0.73]), (len(verts), 1))
    c[iris] = IRIS
    c[pupil] = 0.02
    return c


def outward(v, t):
    """Flip triangle winding if most normals point inward (MakeHuman winding is not assumed)."""
    n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
    s = np.sum(n * (v[t].mean(1) - v.mean(0)), 1)
    return t if (s > 0).mean() > 0.5 else t[:, ::-1]


def camera(eye_mid, ipd, yaw, dist_ipd=6.5):
    return Camera(yaw_deg=yaw, pitch_deg=0.0, target=tuple(eye_mid + np.array([0, -0.15 * ipd * 6.5 / 6.5, 0])),
                  distance=dist_ipd * ipd, fov_deg=24)


def wire(img, items, cam, color=(30, 30, 30)):
    """Overlay visible-side mesh edges (screen-space, back faces culled)."""
    im = Image.fromarray(img).convert("RGB")
    dr = ImageDraw.Draw(im)
    for it in items:
        v, t = np.asarray(it.verts), np.asarray(it.tris)
        scr, depth, R, eye = _project(v, cam, W, H)
        p = scr[t]
        area = (p[:, 1, 0] - p[:, 0, 0]) * (p[:, 2, 1] - p[:, 0, 1]) - (p[:, 1, 1] - p[:, 0, 1]) * (p[:, 2, 0] - p[:, 0, 0])
        for tri in p[area < 0]:
            if (tri[:, 0] < 0).all() or (tri[:, 0] > W).all() or (tri[:, 1] < 0).all() or (tri[:, 1] > H).all():
                continue
            dr.line([tuple(tri[0]), tuple(tri[1]), tuple(tri[2]), tuple(tri[0])], fill=color, width=1)
    return np.asarray(im)


def eye_pixels(items_fn, cam):
    """Count visible eyeball pixels: eyes flat red, everything else flat grey."""
    img = rasterize(items_fn(), cam, W=W, H=H, background=(1, 1, 1), ground_y=None, ssaa=1).astype(int)
    return int(((img[:, :, 0] > 120) & (img[:, :, 1] < 70) & (img[:, :, 2] < 70)).sum())


def topology_stats(v, faces, head_y, eye_centers):
    f = [x for x in faces]
    quads = sum(len(x) == 4 for x in f)
    edges = set()
    for x in f:
        for k in range(len(x)):
            a, b = x[k], x[(k + 1) % len(x)]
            edges.add((min(a, b), max(a, b)))
    e = np.array(sorted(edges))
    used = np.unique(e)
    val = np.bincount(e.ravel(), minlength=len(v))[used]
    head = used[v[used, 1] > head_y]
    L = np.linalg.norm(v[e[:, 0]] - v[e[:, 1]], axis=1)
    hm = (v[e[:, 0], 1] > head_y) & (v[e[:, 1], 1] > head_y)
    near = np.zeros(len(e), bool)
    for c in eye_centers:
        near |= np.linalg.norm((v[e[:, 0]] + v[e[:, 1]]) / 2 - c, axis=1) < 0.022
    return {"vertices": int(len(used)), "faces": len(f), "quad_share": round(quads / len(f), 3),
            "valence_irregular_share": round(float((val != 4).mean()), 3),
            "head_vertices": int(len(head)), "head_edge_mean_mm": round(float(L[hm].mean() * 1000), 2),
            "eye_region_edge_mean_mm": round(float(L[near].mean() * 1000), 2),
            "eye_region_vertices_within_22mm": int(len(np.unique(e[near])))}


# ---------------------------------------------------------------- main
def main():
    OUT.mkdir(exist_ok=True)
    rep, t0 = {}, time.time()
    base, groups = load_obj(A / "3dobjs" / "base.obj")
    body_faces = groups["body"]
    bt = outward(base, tris_of(body_faces))
    eyes_v, eyes_g = load_obj(A / "eyes" / "high-poly" / "high-poly.obj")
    eyes_v = fit_mhclo(A / "eyes" / "high-poly" / "high-poly.mhclo", base)
    eye_faces = [f for fs in eyes_g.values() for f in fs]
    et = tris_of(eye_faces)
    # split the two eyes by x sign, center each
    left = eyes_v[:, 0] > 0
    centers = [eyes_v[left].mean(0), eyes_v[~left].mean(0)]
    ecol = np.where(left[:, None], eye_colors(eyes_v, centers[0]), eye_colors(eyes_v, centers[1]))
    et = outward(eyes_v, et) if False else et
    skel = json.load(open(A / "rigs" / "default.mhskel"))
    weights = json.load(open(A / "rigs" / "default_weights.mhw"))["weights"]
    neck_y = base[skel["joints"][skel["bones"]["neck01"]["head"]]].mean(0)[1]
    head_y = neck_y + 0.04
    rep["makehuman"] = {"topology": topology_stats(base, body_faces, head_y, centers),
                        "uv_coords": sum(1 for l in open(A / "3dobjs" / "base.obj") if l.startswith("vt ")),
                        "bones": len(skel["bones"]), "weighted_bones": len(weights),
                        "face_bones": sorted(b for b in skel["bones"] if any(k in b for k in ("orbicularis", "levator", "oris", "lid", "jaw", "tongue", "eye", "risorius", "temporalis", "mandible")))[:60]}
    ipd_mh = float(np.linalg.norm(centers[0] - centers[1]))
    mid_mh = (centers[0] + centers[1]) / 2

    def mh_items(v=base, eyes_red=False):
        skin = (0.55, 0.55, 0.55) if eyes_red else SKIN
        it = [DrawItem(v, bt, color=skin, roughness=0.5, specular=0.25, sss=0.0 if eyes_red else 1.0),
              DrawItem(eyes_v, et, colors=None if eyes_red else ecol, color=(1, 0, 0), roughness=1.0 if eyes_red else 0.15,
                       specular=0.0 if eyes_red else 0.8, double_sided=True)]
        return it

    # blink: upper-lid-closed units for both eyes from the face pose-unit BVH
    rots = {}
    for unit in ("LeftUpperLidClosed", "RightUpperLidClosed"):
        rots.update(bvh_frame_rotations(A / "poseunits" / "face-poseunits.bvh", A / "poseunits" / "face-poseunits.json", unit))
    rep["makehuman"]["lid_closed_rotations_deg"] = rots
    cam_f = camera(mid_mh, ipd_mh, 0)
    open_px = eye_pixels(lambda: mh_items(base, True), cam_f)
    best = None
    for sign in (1, -1):  # BVH axis convention: pick the sign that closes (reported)
        vc = mh_lid_close(base, skel, weights, rots, sign)
        px = eye_pixels(lambda: mh_items(vc, True), cam_f)
        if best is None or px < best[1]:
            best = (sign, px, vc)
    rep["makehuman"]["blink"] = {"open_eye_pixels": open_px, "closed_eye_pixels": best[1], "sign_used": best[0],
                                 "visible_fraction_closed": round(best[1] / max(open_px, 1), 3)}
    mh_closed = best[2]

    # ---------------- Forge v2 head, same conditions
    b, f, g = preset("female")
    ch = build_character(CharacterSpec(b, f, g, AppearanceParams(hair_style="bald", skin_tone=0.3), ("tshirt",), 30, "v2"), "public")
    sk = ch.skeleton
    c_l, c_r = sk["eye_l"], sk["eye_r"]
    ipd_v2, mid_v2 = float(np.linalg.norm(c_l - c_r)), (c_l + c_r) / 2
    keep = {"body", "eye_l", "eye_r"}

    def v2_items(morph=None, eyes_red=False):
        posed, _ = posed_parts(ch, {}, morph_weights=morph, include=keep)
        it = []
        for p, v in posed:
            if p.name == "body":
                it.append(DrawItem(v, p.tris, color=(0.55, 0.55, 0.55) if eyes_red else SKIN, roughness=0.5, specular=0.25,
                                   sss=0.0 if eyes_red else 1.0))
            else:
                c = c_l if p.name == "eye_l" else c_r
                it.append(DrawItem(v, p.tris, colors=None if eyes_red else eye_colors(v, c), color=(1, 0, 0),
                                   roughness=1.0 if eyes_red else 0.15, specular=0.0 if eyes_red else 0.8))
        return it

    tpl = ch.template
    rep["forge_v2"] = {"topology": topology_stats(ch.body.verts, [list(x) for x in ch.body.tris], sk["neck_01"][1] + 0.04, [c_l, c_r]),
                       "uv": "automatic cylindrical layout", "bones": len(sk.names)}
    cam_v2 = camera(mid_v2, ipd_v2, 0)
    o = eye_pixels(lambda: v2_items(None, True), cam_v2)
    c = eye_pixels(lambda: v2_items({"blink_l": 1.0, "blink_r": 1.0}, True), cam_v2)
    rep["forge_v2"]["blink"] = {"open_eye_pixels": o, "closed_eye_pixels": c, "visible_fraction_closed": round(c / max(o, 1), 3)}

    # ---------------- matched renders
    tiles = []
    for yaw, tag in ((0, "front"), (35, "3q"), (90, "side")):
        a = rasterize(v2_items(), camera(mid_v2, ipd_v2, yaw), W=W, H=H)
        m = rasterize(mh_items(), camera(mid_mh, ipd_mh, yaw), W=W, H=H)
        Image.fromarray(a).save(OUT / f"v2_{tag}.png")
        Image.fromarray(m).save(OUT / f"mh_{tag}.png")
        tiles.append((a, m, tag))
    wa = wire(rasterize(v2_items(), cam_v2, W=W, H=H), v2_items(), cam_v2)
    wm = wire(rasterize(mh_items(), cam_f, W=W, H=H), mh_items(), cam_f)
    ba = rasterize(v2_items({"blink_l": 1.0, "blink_r": 1.0}), cam_v2, W=W, H=H)
    bm = rasterize(mh_items(mh_closed), cam_f, W=W, H=H)
    for n, im in (("v2_wire_front", wa), ("mh_wire_front", wm), ("v2_blink_front", ba), ("mh_blink_front", bm)):
        Image.fromarray(im).save(OUT / f"{n}.png")
    rows = [(t[0], t[1], t[2]) for t in tiles] + [(wa, wm, "topology"), (ba, bm, "blink = 1")]
    sheet = Image.new("RGB", (2 * W + 30, len(rows) * (H + 8)), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    for i, (a, m, tag) in enumerate(rows):
        y = i * (H + 8)
        sheet.paste(Image.fromarray(a), (0, y))
        sheet.paste(Image.fromarray(m), (W + 30, y))
        d.text((8, y + 8), f"Forge v2 ({tag})", fill=(255, 255, 0))
        d.text((W + 38, y + 8), f"MakeHuman hm08 CC0 ({tag})", fill=(255, 255, 0))
    sheet.save(OUT / "comparison.png")
    rep["seconds"] = round(time.time() - t0, 1)
    (OUT / "measurements.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps({k: (v if k == "seconds" else {kk: vv for kk, vv in v.items() if kk != "face_bones"}) for k, v in rep.items()}, indent=1, default=str))


if __name__ == "__main__":
    main()
