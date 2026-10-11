"""Step 4 tests 32 and 58-63: rendering from package data, the validation-before-render rule, overlays, views.

Frames are headless draw lists (forge_engine_viewer.render). The real-window test at the end is
skipped automatically without Tkinter or a display.
"""

import json
import math
import struct
import tempfile
import unittest
from pathlib import Path

try:
    import tkinter as tk
    _root = tk.Tk()
    _root.destroy()
    HAVE_DISPLAY = True
except Exception:  # ImportError (no tkinter) or TclError (no display)
    HAVE_DISPLAY = False

from forge_engine_viewer.errors import IngestionError
from forge_engine_viewer.ingest import ingest
from forge_engine_viewer.render import Camera, Line, Marker, Polygon, Text, build_frame
from forge_engine_viewer.session import ViewerSession
from viewer_support import FROZEN_SOCKET_TIP, GOLDEN_DIR, copy_golden, golden_bytes, node, prim, raw_rows, split, variant

GOLDEN = ingest(GOLDEN_DIR)
GLTF, _, BIN_CHUNK = split(golden_bytes()[0])
W, H = 600, 800


def frame(**kwargs):
    return build_frame(GOLDEN, width=W, height=H, **kwargs)


class TestRenderUsesPackageGeometry(unittest.TestCase):
    def test_32_render_path_uses_package_geometry(self):
        f = frame(camera=Camera.preset("front"))
        polys = f.layer("render")
        self.assertEqual(f.stats["render_triangles"] + f.stats["render_culled"], 280)   # every package triangle
        self.assertEqual({p.source for p in polys}, {"blade", "guard", "grip", "pommel"})
        # the topmost drawn point is the package's own apex vertex (y = socket_tip), mapped by the fit
        top_screen = min(pt[1] for p in polys for pt in p.points)
        self.assertAlmostEqual(top_screen, 52.0, places=6)                 # top band kept for the caption
        # Edit the package itself (consistently re-hashed): narrow the blade to half width in the BIN chunk.
        # The viewer must draw the narrower blade, because it draws the package and nothing else.
        from engine_support import rehash

        acc_index = prim(GLTF, "blade")["attributes"]["POSITION"]
        rows = raw_rows(GLTF, BIN_CHUNK, acc_index)
        narrow = [(x * 0.5, y, z) for x, y, z in rows]

        def positions(b):
            view = GLTF["bufferViews"][GLTF["accessors"][acc_index]["bufferView"]]
            struct.pack_into(f"<{3 * len(narrow)}f", b, view["byteOffset"], *[c for r in narrow for c in r])
            return b

        def bounds(gltf):
            a = gltf["accessors"][acc_index]
            a["min"][0], a["max"][0] = a["min"][0] * 0.5, a["max"][0] * 0.5

        def blade_width(fr):
            xs = [x for p in fr.layer("render") if p.source == "blade" for x, _ in p.points]
            return max(xs) - min(xs)

        with tempfile.TemporaryDirectory() as tmp:
            d = variant(Path(tmp) / "narrow.forgepkg", gltf_fn=bounds, bin_fn=positions)
            (d / "manifest.json").write_bytes(rehash((d / "asset.glb").read_bytes(),
                                                     json.loads((d / "manifest.json").read_bytes())))
            narrowed = ingest(d)
            self.assertEqual(list(narrowed.meshes[0].positions), narrow)
            g = build_frame(narrowed, width=W, height=H, camera=Camera.preset("front"))
            self.assertAlmostEqual(blade_width(g), blade_width(f) * 0.5, places=6)

            def lift(gltf):                                      # moved outside the shipped hull: refused
                node(gltf, "blade")[1]["translation"] = [0.25, 0.0, 0.0]
            d = variant(Path(tmp) / "moved.forgepkg", gltf_fn=lift)
            (d / "manifest.json").write_bytes(rehash((d / "asset.glb").read_bytes(),
                                                     json.loads((d / "manifest.json").read_bytes())))
            with self.assertRaises(IngestionError) as ctx:
                ingest(d)
            self.assertEqual(ctx.exception.code, "bad_collision")

    def test_32b_world_transforms_are_applied_at_render_time(self):
        mesh = GOLDEN.meshes[0]
        self.assertEqual(mesh.world.translation, (0.0, 0.0, 0.0))
        f1 = frame(camera=Camera.preset("front"))
        self.assertEqual(f1.items, frame(camera=Camera.preset("front")).items)             # deterministic
        self.assertNotEqual(f1.items, frame(camera=Camera.preset("side")).items)

    def test_render_does_not_modify_the_ingested_package(self):
        before = (GOLDEN.meshes, GOLDEN.sockets, GOLDEN.collision, GOLDEN.materials)
        for view in ("three_quarter", "front", "side"):
            for mode in ("render", "render+collision", "collision"):
                frame(camera=Camera.preset(view), mode=mode, show_sockets=True)
        self.assertEqual(before, (GOLDEN.meshes, GOLDEN.sockets, GOLDEN.collision, GOLDEN.materials))
        self.assertEqual(list(GOLDEN.socket("socket_tip").world.translation), FROZEN_SOCKET_TIP)   # canonical values

    def test_material_factors_drive_shading(self):
        from forge_engine_viewer.render import shade
        grip, blade = GOLDEN.materials[2], GOLDEN.materials[0]
        n = (0.0, 0.0, 1.0)
        self.assertLess(max(shade(grip, n)), max(shade(blade, n)))        # dark leather vs bronze metal
        self.assertNotEqual(shade(blade, (0.0, 0.0, 1.0)), shade(blade, (0.0, 1.0, 0.0)))


class TestValidationBeforeRender(unittest.TestCase):
    def test_58_no_render_before_validation_completes(self):
        events = []

        def ingest_spy(path):
            events.append("ingest:start")
            result = ingest(path)
            events.append("ingest:done")
            return result

        def frame_spy(pkg, **kwargs):
            events.append("frame")
            return build_frame(pkg, **kwargs)

        s = ViewerSession(ingest_fn=ingest_spy, frame_fn=frame_spy)
        self.assertIsNone(s.frame(W, H))                          # nothing loaded: nothing to draw
        s.listeners.append(lambda: s.frame(W, H))                 # a window redraws on every change
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy_golden(Path(tmp) / "bad.forgepkg")
            (bad / "manifest.json").unlink()
            self.assertFalse(s.open(bad))
            self.assertNotIn("frame", events)                     # refused: never drawn
            self.assertEqual(s.status_kind, "error")
            self.assertEqual(s.last_error.code, "missing_manifest")
        self.assertTrue(s.open(GOLDEN_DIR))
        first_frame = events.index("frame")
        self.assertLess(events.index("ingest:done", 2), first_frame)   # validation finished before the first draw
        self.assertIsNotNone(s.frame(W, H))

    def test_58b_a_refused_package_never_replaces_the_current_one(self):
        s = ViewerSession()
        self.assertTrue(s.open(GOLDEN_DIR))
        current = s.package
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy_golden(Path(tmp) / "bad.forgepkg")
            (bad / "asset.glb").write_bytes(b"not a glb")
            self.assertFalse(s.open(bad))
        self.assertIs(s.package, current)
        self.assertTrue(s.status.startswith("Refused [hash_mismatch]"))


class TestOverlaysAndViews(unittest.TestCase):
    def test_59_socket_overlay(self):
        self.assertEqual(frame(show_sockets=False).layer("socket"), ())
        f = frame(show_sockets=True)
        markers = [i for i in f.layer("socket") if isinstance(i, Marker)]
        axes = [i for i in f.layer("socket") if isinstance(i, Line)]
        self.assertEqual([m.label.split()[0] for m in markers], ["socket_grip", "socket_tip"])
        self.assertEqual(len(axes), 6)                                   # x, y, z per socket
        self.assertIn("(0, 0.6049, 0) m", markers[1].label)
        # the tip marker sits exactly where the package's apex vertex projects
        apex = max((p for m in GOLDEN.meshes for p in m.positions), key=lambda p: p[1])
        cam = f.camera
        tip_view = cam.to_view(GOLDEN.socket("socket_tip").world.translation)
        self.assertEqual(cam.to_view(apex), tip_view)
        self.assertEqual(f.stats["sockets"], 2)

    def test_60_collision_overlay(self):
        plain = frame(mode="render")
        self.assertEqual(plain.layer("collision"), ())
        overlay = frame(mode="render+collision")
        edges = [i for i in overlay.layer("collision") if isinstance(i, Line)]
        self.assertEqual(len(edges), 94 * 3 // 2)                        # every hull edge, once
        self.assertEqual(len(overlay.layer("render")), plain.stats["render_triangles"])
        self.assertTrue(any(e.dash for e in edges) and any(not e.dash for e in edges))   # hidden edges dashed
        only = frame(mode="collision")
        self.assertEqual(only.layer("render"), ())                      # collision-only hides the render mesh
        self.assertGreater(only.stats["collision_faces"], 0)
        self.assertTrue(all(isinstance(i, (Polygon, Line)) for i in only.layer("collision")))
        with self.assertRaises(ValueError):
            frame(mode="wireframe")

    def gizmo(self, f):
        lines = [i for i in f.layer("gizmo") if isinstance(i, Line)]
        return {label: (l.b[0] - l.a[0], l.b[1] - l.a[1]) for label, l in zip("XYZ", lines)}

    def test_61_front_view(self):
        f = frame(camera=Camera.preset("front"))
        g = self.gizmo(f)
        self.assertGreater(g["X"][0], 25.0)                             # +X to the right
        self.assertLess(g["Y"][1], -25.0)                               # +Y up (screen y grows downward)
        self.assertAlmostEqual(math.hypot(*g["Z"]), 0.0, places=9)      # +Z points at the camera
        self.assertEqual([t.text for t in f.layer("gizmo") if isinstance(t, Text)], ["X", "Y"])

    def test_62_side_view(self):
        f = frame(camera=Camera.preset("side"))
        g = self.gizmo(f)
        self.assertAlmostEqual(math.hypot(*g["X"]), 0.0, places=9)      # +X points at the camera
        self.assertLess(g["Z"][0], -25.0)                               # +Z to the left
        self.assertLess(g["Y"][1], -25.0)
        front = frame(camera=Camera.preset("front"))
        width = lambda fr: max(x for p in fr.layer("render") for x, _ in p.points) - min(x for p in fr.layer("render") for x, _ in p.points)
        self.assertNotAlmostEqual(width(f), width(front), places=1)    # edge-on vs broadside silhouettes

    def test_63_three_quarter_default_view(self):
        f = frame()
        self.assertEqual((f.camera.name, f.camera.azimuth, f.camera.elevation), ("three_quarter", -35.0, 20.0))
        self.assertGreater(f.stats["render_triangles"], 0)
        self.assertGreater(f.stats["render_culled"], 0)
        depths = [p.depth for p in f.layer("render")]
        self.assertEqual(depths, sorted(depths))                       # far to near
        s = ViewerSession()
        s.open(GOLDEN_DIR)
        s.orbit(-60.0, 10.0)
        self.assertEqual((s.camera.name, s.camera.azimuth, s.camera.elevation), ("orbit", -95.0, 30.0))
        s.orbit(0.0, 500.0)
        self.assertEqual(s.camera.elevation, 89.0)                     # clamped: no flipping over the pole


@unittest.skipUnless(HAVE_DISPLAY, "needs tkinter and a display")
class TestRealViewerWindow(unittest.TestCase):
    def setUp(self):
        from forge_engine_viewer.window import ViewerWindow
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.geometry("1100x760")
        self.win = ViewerWindow(self.root)
        self.root.update()

    def tearDown(self):
        self.root.destroy()

    def count(self, tag):
        return len(self.win.canvas.find_withtag(tag))

    def test_window_flow(self):
        w = self.win
        self.assertEqual(self.count("render"), 0)
        self.assertEqual(w.frames_drawn, 0)
        self.assertIn("disabled", w.sockets_check.state())
        with tempfile.TemporaryDirectory() as tmp:
            bad = copy_golden(Path(tmp) / "bad.forgepkg")
            (bad / "manifest.json").unlink()
            w.session.open(bad)                                         # session-level: no dialog in tests
            self.root.update()
            self.assertEqual(self.count("render"), 0)
            self.assertEqual(w.frames_drawn, 0)
            self.assertTrue(w.status_var.get().startswith("Error: Refused [missing_manifest]"))
        w.session.open(GOLDEN_DIR)
        self.root.update()
        self.assertGreater(self.count("render"), 100)
        self.assertEqual(self.count("collision"), 0)
        w.sockets_check.invoke()
        self.assertEqual(self.count("marker"), 2)
        w.mode_buttons["render+collision"].invoke()
        self.assertEqual(len([i for i in w.canvas.find_withtag("collision")
                              if w.canvas.type(i) == "line"]), 141)
        w.mode_buttons["collision"].invoke()
        self.assertEqual(self.count("render"), 0)
        for name in ("front", "side", "three_quarter"):
            w.view_buttons[name].invoke()
            self.assertEqual(w.session.camera.name, name)
        details = w.details.get("1.0", "end")
        for text in ("socket_tip", "[0.0, 0.60488361120224, 0.0]", "collision_hull", "convex_hull", "LOD0",
                     "forge.engine-contract v1", "meters", "b91900f7a1fc95f3ec6678e3dc8fa875b91bcce115c3231bd14dc5d0e2828bc3"):
            self.assertIn(text, details)


if __name__ == "__main__":
    unittest.main()
