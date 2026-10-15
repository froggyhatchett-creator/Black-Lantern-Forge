"""Software rasterizer: culling, viewport clipping, near-plane clipping and bounded tiling (preview renders only)."""

import time
import unittest

import numpy as np

from forge_character_forge.lod import decimate
from forge_character_forge.render import Camera, DrawItem, rasterize

BG = (0.5, 0.5, 0.5)
W, H = 120, 100


def cam():
    return Camera(yaw_deg=0, pitch_deg=0, target=(0, 0, 0), distance=2.0, fov_deg=40)


def quad(x0, x1, y0, y1, z=0.0, n=1):
    """Front-facing (toward +z) quad split into 2*n*n triangles."""
    xs, ys = np.linspace(x0, x1, n + 1), np.linspace(y0, y1, n + 1)
    v = np.array([(x, y, z) for y in ys for x in xs], float)
    t = []
    for j in range(n):
        for i in range(n):
            a = j * (n + 1) + i
            t += [(a, a + 1, a + n + 2), (a, a + n + 2, a + n + 1)]
    return v, np.array(t)


def covered(items, c=None, w=W, h=H):
    img = rasterize(items, c or cam(), W=w, H=h, background=BG, ground_y=None, ssaa=1)
    bg = rasterize([], c or cam(), W=w, H=h, background=BG, ground_y=None, ssaa=1)
    return np.any(img != bg, axis=2), img


def item(v, t, **kw):
    return DrawItem(v, t, color=(0.9, 0.2, 0.2), **kw)


class RasterizerTests(unittest.TestCase):
    def test_offscreen_triangles_draw_nothing(self):
        v, t = quad(5.0, 6.0, -0.5, 0.5)            # far right of the frustum
        m, _ = covered([item(v, t)])
        self.assertEqual(int(m.sum()), 0)
        v, t = quad(-0.5, 0.5, -0.5, 0.5, z=3.0)    # entirely behind the camera
        m, _ = covered([item(v, t)])
        self.assertEqual(int(m.sum()), 0)

    def test_partially_visible_matches_visible_part(self):
        # half-width view at z=0: tan(20 deg) * 2 * aspect
        hx = np.tan(np.radians(20)) * 2.0 * W / H
        v, t = quad(0.0, 10.0, -10.0, 10.0)        # right half of the screen and far beyond it
        m, _ = covered([item(v, t)])
        self.assertTrue(m[:, W // 2 + 1:].all())
        self.assertFalse(m[:, :W // 2 - 1].any())
        self.assertGreater(hx, 0.5)

    def test_huge_projected_triangle_is_tiled_not_dropped(self):
        # one triangle whose screen box is ~50x the viewport (the old binning skipped boxes over 4096 px)
        v = np.array([(-40.0, -40.0, 0.5), (40.0, -40.0, 0.5), (0.0, 40.0, 0.5)])
        m, _ = covered([item(v, np.array([[0, 1, 2]]))], w=400, h=300)
        self.assertTrue(m.all())

    def test_tiling_matches_fine_tessellation(self):
        # a 1-triangle-per-half quad (tiled path) must cover exactly what a 40x40 tessellation covers
        v1, t1 = quad(-0.6, 0.6, -0.5, 0.5, n=1)
        v2, t2 = quad(-0.6, 0.6, -0.5, 0.5, n=40)
        m1, i1 = covered([item(v1, t1)], w=300, h=240)
        m2, i2 = covered([item(v2, t2)], w=300, h=240)
        self.assertLessEqual(int((m1 != m2).sum()), 4)  # at most a few pixel centers lying exactly on a diagonal
        self.assertLessEqual(int(np.abs(i1.astype(int) - i2.astype(int)).max()), 2)

    def test_near_plane_crossing_floor(self):
        # an infinite-ish floor under the camera that extends behind it: the visible part fills the lower half
        c = Camera(yaw_deg=0, pitch_deg=0, target=(0, 0, 0), distance=2.0, fov_deg=60)
        v = np.array([(-50.0, -0.5, -50.0), (50.0, -0.5, -50.0), (50.0, -0.5, 50.0), (-50.0, -0.5, 50.0)])
        t = np.array([[0, 3, 2], [0, 2, 1]])  # facing +y
        m, img = covered([item(v, t)], c)
        self.assertTrue(np.isfinite(img).all())
        self.assertTrue(m[H // 2 + 3:].all(), "everything below the horizon is floor")
        self.assertFalse(m[:H // 2 - 3].any(), "nothing above the horizon")

    def test_lod_closeup_is_fast_and_consistent(self):
        from forge_character_forge.accessories import uv_sphere
        v, t = uv_sphere(60, 90)[:2]
        keep, nt = decimate(v, t, 400)                # coarse LOD: large triangles
        c = Camera(yaw_deg=0, pitch_deg=0, target=(0, 0, 0.9), distance=0.25, fov_deg=40)  # inside-the-frame close-up
        t0 = time.perf_counter()
        m, _ = covered([item(v[keep], nt)], c, w=480, h=400)
        self.assertLess(time.perf_counter() - t0, 30.0)
        self.assertGreater(m.mean(), 0.5)


if __name__ == "__main__":
    unittest.main()
