"""Generator v3 surface maps, baked by Forge in hm08's UV layout (Forge-owned, deterministic; no third-party images).

- ``skin_albedo`` (RGBA, 2048 px, sRGB-encoded): a linear multiplier on the chosen skin tone (mean about ``ALBEDO_MEAN``), with regional
  colour (lips, cheeks, nose, ears, eyelids, under-eye), low-frequency mottling, sparse moles and freckles; alpha is
  the scalp mask (where hair grows), used to tint the scalp under the hair.
- ``skin_normal`` (RGB, 1024 px): tangent-space normals (X = +u, Y = +v of the OBJ UVs, the glTF convention) from a
  height field: lip lines, fine creases and soft bumps. Pores finer than a texel stay procedural in the shader.

Regions come from data, not guesses: MakeHuman's CC0 detail targets define the lip, nose, cheek and ear vertex sets
(their displacement magnitude is a soft mask); eyelids are the lid bones' skin weights.
"""

from __future__ import annotations

import io
from functools import lru_cache

import numpy as np
from PIL import Image

from forge_character_forge.v3 import mh, model

ALBEDO_PX = 2048
NORMAL_PX = 1024
ALBEDO_MEAN = 0.85  # the shader divides by this, so the skin-tone control keeps its meaning
SEED = 3


# ---------------------------------------------------------------- noise (numpy, deterministic)
def _hash(ix, iy, iz, seed):
    h = (ix.astype(np.int64) * 73856093) ^ (iy.astype(np.int64) * 19349663) ^ (iz.astype(np.int64) * 83492791) ^ (seed * 2654435761)
    h = (h ^ (h >> 13)) * 1274126177
    return ((h ^ (h >> 16)) & 0xFFFFFF) / float(0xFFFFFF)


def vnoise(p: np.ndarray, seed: int = 0) -> np.ndarray:
    """Trilinear value noise in [0, 1] at points p (N,3)."""
    i = np.floor(p).astype(np.int64)
    f = p - i
    f = f * f * (3 - 2 * f)
    out = 0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2])
                out = out + w * _hash(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz, seed)
    return out


def fbm(p, octaves=4, seed=0):
    s, a, tot = 0.0, 1.0, 0.0
    for o in range(octaves):
        s = s + a * vnoise(p * (2 ** o), seed + o)
        tot += a
        a *= 0.5
    return s / tot


def _smooth(x, a, b):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- UV rasterisation
@lru_cache(maxsize=None)
def uv_raster(res: int):
    """For each texel: the body triangle covering it (-1 if none) and barycentric weights (res, res, 3).
    Row 0 is v = 1 (image orientation). Uncovered texels are later filled by dilation."""
    _, uv, tris, _ = model.body_surface()
    tri_id = -np.ones((res, res), np.int64)
    bary = np.zeros((res, res, 3))
    P = np.stack([uv[:, 0] * res - 0.5, (1 - uv[:, 1]) * res - 0.5], 1)
    for t, (a, b, c) in enumerate(tris):
        pa, pb, pc = P[a], P[b], P[c]
        x0, x1 = int(np.floor(min(pa[0], pb[0], pc[0]))), int(np.ceil(max(pa[0], pb[0], pc[0])))
        y0, y1 = int(np.floor(min(pa[1], pb[1], pc[1]))), int(np.ceil(max(pa[1], pb[1], pc[1])))
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, res - 1), min(y1, res - 1)
        if x1 < x0 or y1 < y0:
            continue
        xs, ys = np.meshgrid(np.arange(x0, x1 + 1), np.arange(y0, y1 + 1))
        d = (pb[1] - pc[1]) * (pa[0] - pc[0]) + (pc[0] - pb[0]) * (pa[1] - pc[1])
        if abs(d) < 1e-12:
            continue
        w0 = ((pb[1] - pc[1]) * (xs - pc[0]) + (pc[0] - pb[0]) * (ys - pc[1])) / d
        w1 = ((pc[1] - pa[1]) * (xs - pc[0]) + (pa[0] - pc[0]) * (ys - pc[1])) / d
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-4) & (w1 >= -1e-4) & (w2 >= -1e-4)
        tri_id[ys[inside], xs[inside]] = t
        bary[ys[inside], xs[inside]] = np.stack([w0[inside], w1[inside], w2[inside]], 1)
    return tri_id, bary


def texel_field(per_vertex: np.ndarray, res: int) -> np.ndarray:
    """Interpolate a per-split-vertex field (V,k) into texture space (res, res, k); uncovered texels are NaN."""
    _, _, tris, _ = model.body_surface()
    tid, bary = uv_raster(res)
    out = np.full((res, res, per_vertex.shape[1]), np.nan)
    m = tid >= 0
    t = tris[tid[m]]
    out[m] = (per_vertex[t] * bary[m][:, :, None]).sum(1)
    return out


def dilate(img: np.ndarray, iters: int = 8) -> np.ndarray:
    """Fill NaN texels from covered neighbours (padding against seam bleeding under filtering)."""
    img = img.copy()
    for _ in range(iters):
        nan = np.isnan(img[:, :, 0])
        if not nan.any():
            break
        acc = np.zeros_like(img)
        cnt = np.zeros(img.shape[:2])
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0), (1, 1), (-1, -1), (1, -1), (-1, 1)):
            sh = np.roll(np.roll(img, dy, 0), dx, 1)
            ok = ~np.isnan(sh[:, :, 0])
            acc[ok] += sh[ok]
            cnt += ok
        fill = nan & (cnt > 0)
        img[fill] = acc[fill] / cnt[fill, None]
    return np.nan_to_num(img, nan=float(np.nanmean(img)))


# ---------------------------------------------------------------- regions
def _target_mask(rels, power=1.0):
    v = model.neutral()
    m = np.zeros(len(v))
    for r in rels:
        i, d = mh.target(r)
        mag = np.linalg.norm(d, axis=1)
        m[i] = np.maximum(m[i], mag / max(mag.max(), 1e-12))
    return np.clip(m, 0, 1) ** power


@lru_cache(maxsize=None)
def region_masks() -> dict:
    """Soft masks per base vertex (0..1)."""
    v = model.neutral()
    lips = _target_mask(["mouth/mouth-upperlip-volume-incr.target", "mouth/mouth-lowerlip-volume-incr.target"], 0.7)
    nose = _target_mask(["nose/nose-scale-horiz-incr.target", "nose/nose-point-width-incr.target"], 1.2)
    cheeks = _target_mask(["cheek/l-cheek-volume-incr.target", "cheek/r-cheek-volume-incr.target"], 1.0)
    ears = _target_mask(["ears/l-ear-scale-incr.target", "ears/r-ear-scale-incr.target"], 0.6)
    W = mh.skin_weights()
    lids = np.zeros(len(v))
    for b in ("orbicularis03.L", "orbicularis03.R", "orbicularis04.L", "orbicularis04.R"):
        p = np.asarray(W[b], float)
        lids[p[:, 0].astype(np.int64)] = np.maximum(lids[p[:, 0].astype(np.int64)], p[:, 1])
    under = np.zeros(len(v))
    for s in "lr":
        c, _ = model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])
        d = v - c
        under = np.maximum(under, _smooth(-d[:, 1], 0.004, 0.012) * _smooth(0.03, 0.012, -d[:, 1]) * _smooth(0.022, 0.012, np.abs(d[:, 0]))
                           * _smooth(d[:, 2], -0.02, -0.005))
    return {"lips": lips, "nose": nose, "cheeks": cheeks, "ears": ears, "lids": lids, "under_eye": under * (1 - lids),
            "scalp": scalp_mask(v)}


def head_frame_v3(v):
    """Origin between the eyeball centres; used by the scalp mask and the grooming generator."""
    cs = [model.sphere_fit(mh.fit_eyes(v)[model.eye_parts()[f"eye_{s}"][0]])[0] for s in "lr"]
    return (cs[0] + cs[1]) / 2, cs


HAIRLINE = [(0, 0.064), (35, 0.058), (60, 0.042), (85, 0.030), (100, 0.014), (130, -0.01), (150, -0.04), (165, -0.055), (180, -0.06)]


def hairline_height(theta_deg):
    a, h = zip(*HAIRLINE)
    return np.interp(np.abs(theta_deg), a, h)


def scalp_mask(v, soft=0.006):
    """Where hair grows: above a hairline that runs from the forehead over the temples and ears to the nape."""
    E, _ = head_frame_v3(v)
    rel = v - E
    theta = np.degrees(np.arctan2(rel[:, 0], rel[:, 2]))
    m = _smooth(rel[:, 1] - hairline_height(theta), -soft / 2, soft / 2)
    ears = _target_mask(["ears/l-ear-scale-incr.target", "ears/r-ear-scale-incr.target"], 0.5)
    nape = 1 - _smooth(np.abs(rel[:, 0]), 0.045, 0.06) * _smooth(-rel[:, 1], 0.015, 0.03)  # low hair only near the midline
    m = m * nape * (1 - _smooth(ears, 0.05, 0.25)) * (rel[:, 1] > -0.16)
    # hm08 also has inner mouth and throat skin behind the face; those patches are not connected to the scalp
    # except through the face, so keep only the connected region (m > 0) that contains the crown
    nb = model._neighbours()
    body = model.body_vertex_ids()  # (helper vertices, e.g. MakeHuman's hair helper, are not skin)
    seed = int(body[np.argmax(np.where(m[body] > 0.5, v[body, 1], -np.inf))])
    keep, stack = {seed}, [seed]
    while stack:
        i = stack.pop()
        for j in nb.get(i, ()):
            if j not in keep and m[j] > 0:
                keep.add(j)
                stack.append(j)
    conn = np.zeros(len(v), bool)
    conn[list(keep)] = True
    return m * conn


# ---------------------------------------------------------------- maps
def _png(arr: np.ndarray) -> bytes:
    b = io.BytesIO()
    Image.fromarray(arr).save(b, format="PNG", compress_level=9)
    return b.getvalue()


@lru_cache(maxsize=None)
def skin_albedo() -> np.ndarray:
    """(res, res, 4) uint8."""
    res = ALBEDO_PX
    v = model.neutral()
    src, *_ = model.body_surface()
    M = region_masks()
    fields = np.stack([v[src, 0], v[src, 1], v[src, 2]] + [M[k][src] for k in ("lips", "nose", "cheeks", "ears", "lids", "under_eye", "scalp")], 1)
    F = dilate(texel_field(fields, res), 10).reshape(-1, fields.shape[1])
    p = F[:, :3]
    lips, nose, cheeks, ears, lids, under, scalp = (F[:, 3 + k] for k in range(7))
    rgb = np.ones((len(p), 3))
    mott = fbm(p * 28.0, 4, SEED) - 0.5          # 2-4 cm blotches
    fine = fbm(p * 160.0, 3, SEED + 10) - 0.5    # mm-scale texture
    rgb *= (1 + 0.10 * mott + 0.05 * fine)[:, None]
    red = np.clip(0.4 * cheeks + 0.5 * nose + 0.5 * ears, 0, 1) * (0.7 + 0.6 * fbm(p * 60.0, 2, SEED + 20))
    rgb *= 1 - red[:, None] * np.array([0.0, 0.10, 0.08])                     # flushed: less green/blue
    lipc = _smooth(lips, 0.55, 0.85)
    lipline = 0.5 + 0.5 * np.sin(p[:, 0] * 2 * np.pi / 0.0016 + 3 * fbm(p * 400.0, 2, SEED + 30))  # vertical lip lines
    rgb *= (1 - lipc[:, None] * (np.array([0.05, 0.30, 0.28]) + 0.025 * lipline[:, None]))
    rgb *= 1 - (0.10 * under)[:, None] * np.array([1.0, 1.15, 0.85])          # shadowed, slightly violet under-eye
    rgb *= 1 - (0.06 * lids)[:, None] * np.array([0.6, 1.0, 0.9])
    # sparse moles (body) and light freckles (nose, cheeks): thresholded noise, so they stay round and sparse
    moles = _smooth(vnoise(p * 380.0, SEED + 50), 0.992, 0.997)
    freck = _smooth(vnoise(p * 900.0, SEED + 51), 0.90, 0.97) * np.clip(nose + cheeks, 0, 1)
    rgb *= 1 - (0.45 * moles + 0.07 * freck)[:, None] * np.array([1.0, 1.08, 1.14])
    rgb = np.clip(rgb * ALBEDO_MEAN, 0, 1)
    rgb = np.where(rgb <= 0.0031308, rgb * 12.92, 1.055 * rgb ** (1 / 2.4) - 0.055)  # stored sRGB (glTF base colour)
    a = np.clip(scalp, 0, 1)
    out = np.concatenate([rgb, a[:, None]], 1).reshape(res, res, 4)
    return np.round(out * 255).astype(np.uint8)


@lru_cache(maxsize=None)
def skin_normal() -> np.ndarray:
    """(res, res, 3) uint8 tangent-space normal map from a Forge height field."""
    res = NORMAL_PX
    v = model.neutral()
    src, *_ = model.body_surface()
    M = region_masks()
    fields = np.stack([v[src, 0], v[src, 1], v[src, 2], M["lips"][src], M["nose"][src], M["cheeks"][src], M["lids"][src]], 1)
    F = dilate(texel_field(fields, res), 10)
    p = F[:, :, :3].reshape(-1, 3)
    lips, nose, cheeks, lids = (F[:, :, 3 + k].reshape(-1) for k in range(4))
    h = 0.6 * (fbm(p * 90.0, 3, SEED + 40) - 0.5)                               # soft undulation
    h += (0.35 + 0.65 * np.clip(nose + 0.6 * cheeks, 0, 1)) * (vnoise(p * 700.0, SEED + 41) - 0.5) * 0.25  # coarse pores (finer ones: shader)
    lipc = _smooth(lips, 0.3, 0.7)
    h = h * (1 - 0.8 * lipc) + lipc * 0.9 * np.abs(np.sin(p[:, 0] * 2 * np.pi / 0.0018 + 3 * fbm(p * 300.0, 2, SEED + 42)))
    h *= 1 - 0.7 * _smooth(lids, 0.2, 0.8)
    H = h.reshape(res, res)
    k = 0.7  # bump strength
    du = (np.roll(H, -1, 1) - np.roll(H, 1, 1)) / 2
    dv = -(np.roll(H, -1, 0) - np.roll(H, 1, 0)) / 2   # rows run toward -v
    n = np.stack([-k * du, -k * dv, np.ones_like(H)], 2)
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    return np.round((n * 0.5 + 0.5) * 255).astype(np.uint8)


def eye_texture_bytes() -> bytes:
    """MakeHuman's CC0 eye texture (see assets/PROVENANCE.json), as shipped."""
    return (mh.ASSETS / "eyes" / "materials" / "brown_eye.png").read_bytes()


def png_bytes() -> dict:
    """All v3 maps as PNG bytes; cached on disk by the hash of the sources that produce them."""
    import hashlib
    import json
    from pathlib import Path
    here = Path(__file__).resolve().parent
    key = hashlib.sha256(b"".join((here / f).read_bytes() for f in ("textures.py", "model.py", "mh.py", "controls.py"))).hexdigest()[:16]
    cache = here.parent.parent / ".forge_cache" / f"v3_textures_{key}.json"
    if cache.is_file():
        import base64
        return {k: base64.b64decode(v) for k, v in json.loads(cache.read_text()).items()}
    out = _png_bytes()
    cache.parent.mkdir(exist_ok=True)
    import base64
    cache.write_text(json.dumps({k: base64.b64encode(v).decode() for k, v in out.items()}))
    return out


def _png_bytes() -> dict:
    return {"skin_albedo": _png(skin_albedo()), "skin_normal": _png(skin_normal()), "eye": eye_texture_bytes(),
            "strand_single": _png(strand_alpha(1)), "strand_hair": _png(strand_alpha(6))}


def eye_iris_stats(uv: np.ndarray, pos: np.ndarray) -> dict:
    """Where the texture's iris is, for one eyeball part: its centre and radius in texture pixels (found from the
    luminance step between iris and sclera), the matching angle from the optical axis on the geometry (so the shader's
    iris/sclera split lines up with the texture), and the iris's mean linear luminance (for recolouring)."""
    im = np.asarray(Image.open(io.BytesIO(eye_texture_bytes())).convert("RGB")) / 255.0
    lin = np.where(im <= 0.04045, im / 12.92, ((im + 0.055) / 1.055) ** 2.4)
    lum = lin @ np.array([0.2126, 0.7152, 0.0722])
    H, W = lum.shape
    c3, _ = model.sphere_fit(pos)
    d = (pos - c3) / np.linalg.norm(pos - c3, axis=1, keepdims=True)
    ang = np.arccos(np.clip(d[:, 2], -1, 1))
    px = np.stack([uv[:, 0] * W, (1 - uv[:, 1]) * H], 1)
    c = px[ang < np.percentile(ang, 3)].mean(0)
    radii = np.arange(2, int(0.25 * W))
    phis = np.linspace(0, 2 * np.pi, 72, endpoint=False)
    prof = np.array([np.mean(lum[np.clip((c[1] + r * np.sin(phis)).astype(int), 0, H - 1),
                                 np.clip((c[0] + r * np.cos(phis)).astype(int), 0, W - 1)]) for r in radii])
    sclera = np.median(prof[len(prof) // 2:])
    edge = float(radii[np.argmax(prof > 0.5 * (prof[: len(prof) // 6].mean() + sclera))])
    dist = np.linalg.norm(px - c, axis=1)
    o = np.argsort(dist)
    angle = float(np.interp(edge, dist[o], ang[o]))
    yy, xx = np.mgrid[0:H, 0:W]
    disc = (xx - c[0]) ** 2 + (yy - c[1]) ** 2 < (0.9 * edge) ** 2
    return {"centre_px": [float(c[0]), float(c[1])], "radius_px": edge, "angle": angle, "mean_lum": float(lum[disc].mean()),
            "texture_px": [W, H]}


def strand_alpha(hairs: int, w: int = 256, h: int = 64, seed: int = 21) -> np.ndarray:
    """Alpha profile of a strand ribbon (u along the strand -> x, v across -> y), RGBA white.
    hairs = 1: one tapered hair (brows, lashes); hairs > 1: a ribbon of several hairs with uneven ends (scalp hair)."""
    rng = np.random.default_rng(seed + hairs)
    u = (np.arange(w) + 0.5) / w
    v = (np.arange(h) + 0.5) / h
    U, V = np.meshgrid(u, v)
    if hairs == 1:
        a = _smooth(1 - np.abs(2 * V - 1), 0.0, 0.7) * _smooth(1 - U, 0.0, 0.25)
    else:
        a = np.zeros_like(U)
        for _ in range(hairs * 3):
            c = rng.uniform(0.05, 0.95)
            wid = rng.uniform(0.05, 0.09)
            end = rng.uniform(0.75, 1.0)
            wav = 0.02 * np.sin(2 * np.pi * (U * rng.uniform(1, 3) + rng.random()))
            a = np.maximum(a, _smooth(wid - np.abs(V - c - wav), 0, wid * 0.7) * _smooth(end - U, 0, 0.12) * rng.uniform(0.7, 1.0))
    out = np.ones((h, w, 4))
    out[:, :, 3] = a
    return np.round(out * 255).astype(np.uint8)
