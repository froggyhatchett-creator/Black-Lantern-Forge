"""Vectorized software rasterizer for previews of the actual generated geometry.

Orthographic or perspective camera, z-buffer, per-vertex normal/color
interpolation, three-light rig with wrapped diffuse (a cheap skin
sub-surface approximation), Blinn specular and a ground contact shadow.
It renders exactly the triangles that are exported; nothing is painted in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class DrawItem:
    verts: np.ndarray
    tris: np.ndarray
    colors: np.ndarray | None = None      # (V,3) linear 0..1
    color: tuple = (0.7, 0.7, 0.7)
    roughness: float = 0.6
    specular: float = 0.25
    sss: float = 0.0                      # wrap-lighting amount (skin)
    double_sided: bool = False
    alpha: float = 1.0


def look_at(eye, target, up=(0.0, 1.0, 0.0)) -> np.ndarray:
    eye, target, up = (np.asarray(v, float) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    r = np.cross(f, up)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return np.stack([r, u, -f]), eye  # rows: camera axes (x right, y up, z back)


@dataclass
class Camera:
    yaw_deg: float = 20.0
    pitch_deg: float = 5.0
    target: tuple = (0.0, 0.9, 0.0)
    distance: float = 4.5
    fov_deg: float = 26.0
    ortho_height: float | None = None     # set for orthographic

    def basis(self):
        yaw, pitch = np.radians(self.yaw_deg), np.radians(self.pitch_deg)
        d = np.array([np.sin(yaw) * np.cos(pitch), np.sin(pitch), np.cos(yaw) * np.cos(pitch)])
        eye = np.asarray(self.target) + d * self.distance
        return look_at(eye, self.target)


def _project(verts, cam: Camera, W, H):
    R, eye = cam.basis()
    pc = (verts - eye) @ R.T  # camera space, looking down -z
    if cam.ortho_height:
        s = H / cam.ortho_height
        sx = W / 2 + pc[:, 0] * s
        sy = H / 2 - pc[:, 1] * s
        depth = -pc[:, 2]
    else:
        f = (H / 2) / np.tan(np.radians(cam.fov_deg) / 2)
        z = np.maximum(-pc[:, 2], 1e-4)
        sx = W / 2 + pc[:, 0] * f / z
        sy = H / 2 - pc[:, 1] * f / z
        depth = z
    return np.stack([sx, sy], 1), depth, R, eye


def _normals(verts, tris):
    fn = np.cross(verts[tris[:, 1]] - verts[tris[:, 0]], verts[tris[:, 2]] - verts[tris[:, 0]])
    n = np.zeros_like(verts)
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    return n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-20)


def rasterize(items: list[DrawItem], cam: Camera, W=800, H=1000, background=None, ground_y: float | None = 0.0,
              ssaa: int = 2):
    """Returns an RGB uint8 image (H, W, 3)."""
    W2, H2 = W * ssaa, H * ssaa
    zbuf = np.full(H2 * W2, np.inf)
    nbuf = np.zeros((H2 * W2, 3))
    cbuf = np.zeros((H2 * W2, 3))
    mbuf = np.zeros((H2 * W2, 4))  # roughness, specular, sss, item id+1
    pbuf = np.zeros((H2 * W2, 3))
    for item_id, it in enumerate(items):
        v = np.asarray(it.verts, float)
        t = np.asarray(it.tris, np.int64)
        if not len(t):
            continue
        n = _normals(v, t)
        col = np.broadcast_to(np.asarray(it.color, float), v.shape) if it.colors is None else np.asarray(it.colors)
        scr, depth, R, eye = _project(v, cam, W2, H2)
        p0, p1, p2 = scr[t[:, 0]], scr[t[:, 1]], scr[t[:, 2]]
        area = (p1[:, 0] - p0[:, 0]) * (p2[:, 1] - p0[:, 1]) - (p1[:, 1] - p0[:, 1]) * (p2[:, 0] - p0[:, 0])
        # screen y is down, so front faces (CCW in world) have negative area here
        front = area < 0 if not it.double_sided else np.abs(area) > 1e-12
        keep = front & (np.abs(area) > 1e-9)
        t, p0, p1, p2, area = t[keep], p0[keep], p1[keep], p2[keep], area[keep]
        if not len(t):
            continue
        xmin = np.floor(np.minimum(np.minimum(p0[:, 0], p1[:, 0]), p2[:, 0])).astype(int)
        xmax = np.ceil(np.maximum(np.maximum(p0[:, 0], p1[:, 0]), p2[:, 0])).astype(int)
        ymin = np.floor(np.minimum(np.minimum(p0[:, 1], p1[:, 1]), p2[:, 1])).astype(int)
        ymax = np.ceil(np.maximum(np.maximum(p0[:, 1], p1[:, 1]), p2[:, 1])).astype(int)
        size = np.maximum(xmax - xmin, ymax - ymin) + 1
        for lo, hi in ((0, 4), (4, 8), (8, 16), (16, 32), (32, 64), (64, 256), (256, 4096)):
            sel = np.where((size > lo) & (size <= hi))[0]
            if not len(sel):
                continue
            k = hi
            for start in range(0, len(sel), max(1, 3_000_000 // (k * k))):
                s = sel[start:start + max(1, 3_000_000 // (k * k))]
                ox, oy = np.meshgrid(np.arange(k), np.arange(k))
                px = xmin[s, None] + ox.reshape(1, -1)
                py = ymin[s, None] + oy.reshape(1, -1)
                cx, cy = px + 0.5, py + 0.5
                a0, a1, a2 = p0[s], p1[s], p2[s]
                w0 = (a1[:, None, 0] - cx) * (a2[:, None, 1] - cy) - (a1[:, None, 1] - cy) * (a2[:, None, 0] - cx)
                w1 = (a2[:, None, 0] - cx) * (a0[:, None, 1] - cy) - (a2[:, None, 1] - cy) * (a0[:, None, 0] - cx)
                ar = area[s, None]
                b0, b1 = w0 / ar, w1 / ar
                b2 = 1.0 - b0 - b1
                inside = (b0 >= -1e-6) & (b1 >= -1e-6) & (b2 >= -1e-6) & (px >= 0) & (px < W2) & (py >= 0) & (py < H2)
                ti, pi = np.nonzero(inside)
                if not len(ti):
                    continue
                tri = t[s][ti]
                bb = np.stack([b0[ti, pi], b1[ti, pi], b2[ti, pi]], 1)
                z = np.sum(bb * depth[tri], 1)
                pix = py[ti, pi] * W2 + px[ti, pi]
                order = np.lexsort((z, pix))
                pix, z, tri, bb = pix[order], z[order], tri[order], bb[order]
                first = np.ones(len(pix), bool)
                first[1:] = pix[1:] != pix[:-1]
                pix, z, tri, bb = pix[first], z[first], tri[first], bb[first]
                win = z < zbuf[pix]
                pix, z, tri, bb = pix[win], z[win], tri[win], bb[win]
                zbuf[pix] = z
                nn = np.einsum("pk,pkj->pj", bb, n[tri])
                if it.double_sided:
                    view = eye - np.einsum("pk,pkj->pj", bb, v[tri])
                    flip = np.sum(nn * view, 1) < 0
                    nn[flip] *= -1
                nbuf[pix] = nn
                cbuf[pix] = np.einsum("pk,pkj->pj", bb, col[tri])
                pbuf[pix] = np.einsum("pk,pkj->pj", bb, v[tri])
                mbuf[pix] = (it.roughness, it.specular, it.sss, item_id + 1)
    img = _shade(zbuf, nbuf, cbuf, mbuf, pbuf, cam, W2, H2, background, ground_y)
    im = Image.fromarray(img)
    if ssaa > 1:
        im = im.resize((W, H), Image.LANCZOS)
    return np.asarray(im)


def _shade(zbuf, nbuf, cbuf, mbuf, pbuf, cam, W, H, background, ground_y):
    hit = np.isfinite(zbuf)
    yy = np.repeat(np.linspace(0, 1, H), W)
    if background is None:
        top, bot = np.array([0.20, 0.21, 0.24]), np.array([0.07, 0.07, 0.08])
        bg = top[None, :] * (1 - yy[:, None]) + bot[None, :] * yy[:, None]
    else:
        bg = np.broadcast_to(np.asarray(background, float), (W * H, 3)).copy()
    out = bg.copy()
    R, eye = cam.basis()
    n = nbuf[hit]
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    p = pbuf[hit]
    vdir = eye - p
    vdir /= np.linalg.norm(vdir, axis=1, keepdims=True)
    base = cbuf[hit]
    rough, spec, sss = mbuf[hit, 0], mbuf[hit, 1], mbuf[hit, 2]
    lights = [  # direction (toward light), color, intensity
        (np.array([0.55, 0.65, 0.75]), np.array([1.0, 0.96, 0.9]), 2.3),
        (np.array([-0.7, 0.25, 0.45]), np.array([0.75, 0.85, 1.0]), 0.75),
        (np.array([-0.2, 0.5, -0.9]), np.array([1.0, 1.0, 1.0]), 1.3),
    ]
    col = np.zeros_like(base)
    for d, lc, li in lights:
        d = d / np.linalg.norm(d)
        ndl = n @ d
        wrap = sss[:, None] * 0.5
        diff = np.clip((ndl[:, None] + wrap) / (1 + wrap), 0, 1)
        scatter = np.array([1.0, 0.55, 0.45])[None, :]
        tint = np.where(sss[:, None] > 0, 1.0 - (1 - scatter) * np.clip(wrap - ndl[:, None], 0, 1) * 0.0, 1.0)
        col += base * diff * lc * li * tint * 0.32
        h = d + vdir
        h /= np.linalg.norm(h, axis=1, keepdims=True)
        shin = 2.0 / np.maximum(rough ** 4, 1e-3) - 2.0
        sp = np.clip(n @ d, 0, 1) > 0
        col += (spec * sp * np.clip(np.sum(n * h, 1), 0, 1) ** np.minimum(shin, 2000) * (shin + 8) / 60.0)[:, None] \
            * lc * li * 0.25
    hemi = 0.5 + 0.5 * n[:, 1]
    amb = (np.array([0.32, 0.34, 0.4])[None, :] * hemi[:, None] + np.array([0.16, 0.13, 0.11])[None, :] * (1 - hemi[:, None]))
    col += base * amb * 0.85
    # subtle sss rim
    rim = (1 - np.clip(np.sum(n * vdir, 1), 0, 1)) ** 3
    col += base * np.array([0.9, 0.35, 0.25])[None, :] * (sss * rim)[:, None] * 0.25
    out[hit] = col
    img = np.clip(np.nan_to_num(out), 0, 1) ** (1 / 2.2)
    return (img.reshape(H, W, 3) * 255 + 0.5).astype(np.uint8)


def label(img: np.ndarray, text: str, pos=(10, 10), size=18) -> np.ndarray:
    im = Image.fromarray(img)
    dr = ImageDraw.Draw(im)
    try:
        font = ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover
        font = ImageFont.load_default()
    for i, line in enumerate(text.split("\n")):
        dr.text((pos[0], pos[1] + i * (size + 4)), line, fill=(235, 235, 235), font=font)
    return np.asarray(im)


def sheet(images: list[np.ndarray], cols: int, pad: int = 6, bg=(18, 18, 20)) -> np.ndarray:
    h = max(i.shape[0] for i in images)
    w = max(i.shape[1] for i in images)
    rows = (len(images) + cols - 1) // cols
    out = np.zeros((rows * (h + pad) + pad, cols * (w + pad) + pad, 3), np.uint8)
    out[:] = bg
    for k, im in enumerate(images):
        r, c = divmod(k, cols)
        out[pad + r * (h + pad): pad + r * (h + pad) + im.shape[0], pad + c * (w + pad): pad + c * (w + pad) + im.shape[1]] = im
    return out


def save(img: np.ndarray, path) -> None:
    Image.fromarray(img).save(path)
