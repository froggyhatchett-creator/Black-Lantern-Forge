"""Myth v0.3.0 proof of concept: render an existing Character Forge v3 GLB, unchanged, with Myth's Python wheel.

Isolated: needs only `myth-py==0.3.0` (its own venv) and the standard library. Imports no Forge code, writes nothing
outside its output folder, never modifies the GLB. Needs a GPU adapter (wgpu: Vulkan, DX12 or Metal).

    python myth_poc.py                 # headless: validation, measured frames, beauty frames -> myth_out/
    python myth_poc.py --window        # interactive window: walk + cycling blink, orbit with the mouse

Headless run, per frame of reference/cameras.json (same cameras as our independent player, make_reference.py):
  1. validation of the loaded GLB: the 10 mesh nodes, morph-target counts (blink_l, blink_r on body, brows, lashes,
     hair_shoulder; addressed by index: Myth does not read mesh.extras.targetNames), the 7 animation clips;
  2. measured passes with the reference's rule (render, render again without some meshes, count changed pixels):
     silhouette mask, visible eyeball pixels, garment pixels; strand cards hidden as in the reference;
  3. one beauty frame with every mesh;
  4. timings. Results: myth_out/myth_metrics.json, *_mask.png, *_beauty.png. Then run compare.py.
"""
import argparse
import json
import platform
import struct
import sys
import time
import zlib
from pathlib import Path

import myth

HERE = Path(__file__).resolve().parent
EXPECTED_CLIPS = {"idle", "walk", "run", "jump", "turn", "sudden_stop", "wave"}
MORPHED = ("body", "brows", "lashes", "hair_shoulder")
FPS = 30.0


def write_png(path, data, w, h, channels):
    raw = b"".join(b"\x00" + data[y * w * channels:(y + 1) * w * channels] for y in range(h))
    ctype = {1: 0, 3: 2, 4: 6}[channels]
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def changed(a, b, thr=8):
    """Pixels (RGBA8 bytes) whose RGB differs by more than thr in any channel."""
    n, out = len(a) // 4, bytearray(len(a) // 4)
    for i in range(n):
        j = 4 * i
        if abs(a[j] - b[j]) > thr or abs(a[j + 1] - b[j + 1]) > thr or abs(a[j + 2] - b[j + 2]) > thr:
            out[i] = 255
    return out


def set_visible(nodes, names):
    for n, node in nodes.items():
        node.mesh.visible = n in names


def set_blink(nodes, w):
    for n in MORPHED:
        nodes[n].mesh.morph_target_influences = [w, w]


def validate(scene, model, nodes, meshes):
    rep = {"mesh_nodes_found": sorted(n for n in meshes if nodes.get(n) is not None), "errors": []}
    for n in meshes:
        node = nodes.get(n)
        if node is None or node.mesh is None:
            rep["errors"].append(f"mesh node {n} missing or without mesh")
            continue
    rep["morph_target_counts"] = {n: len(nodes[n].mesh.morph_target_influences) for n in meshes if nodes.get(n) and nodes[n].mesh}
    for n in MORPHED:
        if rep["morph_target_counts"].get(n) != 2:
            rep["errors"].append(f"{n}: expected 2 morph targets (blink_l, blink_r), got {rep['morph_target_counts'].get(n)}")
    set_blink(nodes, 0.7)
    rep["morph_set_readback"] = {n: list(nodes[n].mesh.morph_target_influences) for n in MORPHED}
    if any(abs(x - 0.7) > 1e-6 for v in rep["morph_set_readback"].values() for x in v):
        rep["errors"].append("morph weights did not read back as set")
    set_blink(nodes, 0.0)
    clips = scene.list_animations(model)
    rep["animations"] = clips
    if not EXPECTED_CLIPS <= set(clips):
        rep["errors"].append(f"missing clips: {sorted(EXPECTED_CLIPS - set(clips))}")
    return rep


def place_camera(scene, cam, c):
    cam.position = c["eye"]
    cam.look_at(c["target"])


def headless(args):
    spec = json.loads((HERE / "reference" / "cameras.json").read_text())
    W, H = spec["size"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    glb = Path(args.glb) if args.glb else (HERE.parents[1] / spec["glb"])
    meshes = spec["measured_meshes"] + spec["strands_excluded"]
    rep = {"myth_version": getattr(myth, "__version__", "0.3.0"), "python": sys.version.split()[0], "platform": platform.platform(),
           "glb": str(glb), "size": [W, H], "render_path": args.render_path, "timings_s": {}, "frames": {}}
    t0 = time.perf_counter()
    r = myth.Renderer(render_path=args.render_path, vsync=False)
    try:
        r.init_headless(W, H)
    except Exception as e:  # no GPU adapter: record it, do not try to install anything
        rep["headless_error"] = f"{type(e).__name__}: {e}"
        (out / "myth_metrics.json").write_text(json.dumps(rep, indent=1))
        print("HEADLESS UNAVAILABLE:", rep["headless_error"])
        return 2
    rep["timings_s"]["init_headless"] = round(time.perf_counter() - t0, 3)
    scene = r.create_scene()
    scene.set_background_color(*spec["background"])
    scene.set_ambient_light(0.45, 0.45, 0.45)
    scene.set_tone_mapping_mode("linear")
    key = scene.add_light(myth.DirectionalLight(color=[1, 1, 1], intensity=2.0))
    key.position = [1.5, 3.0, 4.0]
    key.look_at([0, 1, 0])
    cam = scene.add_camera(myth.PerspectiveCamera(fov=spec["frames"][0]["camera"]["fov_deg"], near=0.01, far=100.0))
    scene.active_camera = cam
    t1 = time.perf_counter()
    model = r.load_gltf(str(glb))
    rep["timings_s"]["load_gltf"] = round(time.perf_counter() - t1, 3)
    nodes = {n: scene.find_node_by_name(n) for n in meshes}
    rep["validation"] = validate(scene, model, nodes, meshes)
    r.update(0.0)
    times = []

    def shot():
        a = time.perf_counter()
        r.update(0.0)
        r.render()
        px = r.readback_pixels()
        times.append(time.perf_counter() - a)
        return px

    walking = False
    for f in sorted(spec["frames"], key=lambda f: f["anim"] is not None):  # rest frames first, then the walk
        if f["anim"] and not walking:
            scene.play_animation(model, f["anim"])
            r.update(0.0)
            for _ in range(int(f["frame"])):  # deterministic: frame k at k / 30 s
                r.update(1.0 / FPS)
            walking = True
        set_blink(nodes, f["blink"])
        place_camera(scene, cam, f["camera"])
        measured, eyes, garm = spec["measured_meshes"], spec["eye_meshes"], spec["garment_meshes"]
        set_visible(nodes, measured)
        base = shot()
        set_visible(nodes, [m for m in measured if m not in eyes])
        no_eyes = shot()
        set_visible(nodes, [m for m in measured if m not in garm])
        no_garm = shot()
        set_visible(nodes, meshes)
        beauty = shot()
        mask = changed(base, bytes(bytearray([0, 0, 0, 255]) * (W * H)))  # background is black
        write_png(out / f"{f['name']}_mask.png", bytes(mask), W, H, 1)
        write_png(out / f"{f['name']}_beauty.png", beauty, W, H, 4)
        rep["frames"][f["name"]] = {"silhouette_px": sum(1 for x in mask if x), "eye_px": sum(1 for x in changed(base, no_eyes) if x),
                                    "garment_px": sum(1 for x in changed(base, no_garm) if x),
                                    "morph_weights": {n: list(nodes[n].mesh.morph_target_influences) for n in MORPHED}}
        print(f["name"], {k: v for k, v in rep["frames"][f["name"]].items() if k != "morph_weights"}, flush=True)
    rep["timings_s"]["render_readback_median"] = round(sorted(times)[len(times) // 2], 4)
    rep["timings_s"]["render_readback_max"] = round(max(times), 4)
    rep["timings_s"]["total"] = round(time.perf_counter() - t0, 3)
    (out / "myth_metrics.json").write_text(json.dumps(rep, indent=1))
    r.dispose()
    return 1 if rep["validation"]["errors"] else 0


def window(args):
    spec = json.loads((HERE / "reference" / "cameras.json").read_text())
    glb = Path(args.glb) if args.glb else (HERE.parents[1] / spec["glb"])
    full = next(f for f in spec["frames"] if f["name"] == "full_34_rest")["camera"]
    app = myth.App(title="Forge GLB in Myth (proof of concept)", render_path=args.render_path)
    state = {}

    @app.init
    def on_init(ctx):
        scene = ctx.create_scene()
        scene.set_background_color(0.08, 0.08, 0.1)
        scene.set_ambient_light(0.35, 0.35, 0.35)
        sun = scene.add_light(myth.DirectionalLight(color=[1, 1, 1], intensity=3.0, cast_shadows=True))
        sun.position = [2, 4, 3]
        sun.look_at([0, 1, 0])
        model = ctx.load_gltf(str(glb))
        scene.play_animation(model, "walk")
        cam = scene.add_camera(myth.PerspectiveCamera(fov=35, near=0.01))
        scene.active_camera = cam
        state.update(scene=scene, cam=cam, orbit=myth.OrbitControls(position=full["eye"], target=full["target"]),
                     nodes={n: scene.find_node_by_name(n) for n in MORPHED})

    @app.update
    def on_update(ctx, frame):
        state["orbit"].update(state["cam"], frame.delta_time)
        w = max(0.0, (abs(((frame.elapsed % 3.0) - 1.5)) - 1.2) / 0.3)  # a blink every 3 s
        set_blink(state["nodes"], min(1.0, w))

    app.run()
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--glb", help="GLB to load (default: the one in reference/cameras.json)")
    ap.add_argument("--out", default=str(HERE / "myth_out"))
    ap.add_argument("--render-path", default="basic", choices=["basic", "high_fidelity"])
    ap.add_argument("--window", action="store_true")
    a = ap.parse_args()
    sys.exit(window(a) if a.window else headless(a))


if __name__ == "__main__":
    main()
