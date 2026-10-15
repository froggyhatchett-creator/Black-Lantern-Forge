"""Image-to-3D character reconstruction with full-body completion from partial references.

METHOD (stated plainly): hybrid of classic computer vision and procedural
fitting.  No pretrained network, no landmark-detection model and no generative
model is used (none is available in this environment).

  1. ingest     validate PNG/JPEG/WebP by content, size and authorization; hash for traceability
  2. segment    alpha channel if present, else a border-color background model + Otsu threshold,
                morphological cleanup, largest connected component, hole fill
  3. measure    silhouette width profile in *head-height units* (crown -> neck minimum), so
                full-body, waist-up and head-and-shoulders references share one scale
  4. regions    decide which anatomical regions are visible, cropped or unobservable; detect
                seated/crouched posture and stylized (large-head) proportions
  5. fit        analysis-by-synthesis: candidate characters' SDF silhouettes are measured with the
                same code and compared over visible rows only (coordinate descent, both sex priors)
  6. sample     skin, hair and garment colors from region-masked pixels
  7. DNA        every trait gets provenance observed / estimated / invented and a confidence;
                regions never seen are generated from presets (invented) and say so

What this does NOT do: recover identity-level facial detail, depth from a single
front image, the back of the body, or anything hidden by clothing.  Those traits
are marked estimated or invented, never observed.
"""

from __future__ import annotations

import copy
import hashlib
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image, UnidentifiedImageError

from forge_character_forge import dna as dnam
from forge_character_forge.anatomy import build_field
from forge_character_forge.appearance import _SKIN_SRGB, linear_to_hex, srgb_to_linear
from forge_character_forge.params import BodyParams, FaceParams, preset
from forge_character_forge.skeleton import build_skeleton

SUPPORTED_FORMATS = {"PNG": "image/png", "JPEG": "image/jpeg", "WEBP": "image/webp"}
SUPPORTED_EXT = {".png", ".jpg", ".jpeg", ".webp"}
MIN_SIDE, MAX_SIDE, MAX_PIXELS = 64, 8192, 40_000_000
METHOD = "hybrid: classic CV segmentation + silhouette measurement + analysis-by-synthesis procedural fitting"
# canonical landmark depth below the crown, in head units, for an upright adult (~7.6 heads tall)
REGION_DEPTH = {"head": 1.0, "neck": 1.25, "shoulders": 1.45, "chest": 2.1, "arms_upper": 2.4, "waist": 2.9,
                "hips_pelvis": 3.6, "hands": 4.0, "thighs": 4.6, "knees": 5.6, "lower_legs": 6.6, "feet": 7.5}
PROFILE_K = np.round(np.arange(0.25, 7.76, 0.25), 2)
HAIR_CROWN_FRACTION = 0.06
# waist-to-hip width ratio (A-pose front silhouette) of the male and female presets, measured with this code
WHR_MALE, WHR_FEMALE = 0.776, 0.608


class ReferenceError(ValueError):
    pass


@dataclass
class Reference:
    id: str
    path: str
    view: str
    rgb: np.ndarray            # float sRGB 0..1 (H, W, 3)
    alpha: np.ndarray | None   # bool mask from the alpha channel, if meaningful
    meta: dict


def load_reference(path, view: str = "front", authorized: bool = False) -> Reference:
    p = Path(path)
    if not authorized:
        raise ReferenceError("reference images must be explicitly authorized by the user (authorized=True)")
    if view not in ("front", "side", "back", "three_quarter"):
        raise ReferenceError(f"unsupported view {view!r}")
    if p.suffix.lower() not in SUPPORTED_EXT:
        raise ReferenceError(f"unsupported file type {p.suffix!r}; use PNG, JPEG or WebP")
    try:
        data = p.read_bytes()
    except OSError as exc:
        raise ReferenceError(f"cannot read {p}: {exc}") from exc
    try:
        Image.MAX_IMAGE_PIXELS = MAX_PIXELS
        with Image.open(p) as im:
            fmt = im.format
            im.verify()
        im = Image.open(p)
        im.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise ReferenceError(f"malformed or unreadable image: {exc}") from exc
    if fmt not in SUPPORTED_FORMATS:
        raise ReferenceError(f"file content is {fmt}, not PNG/JPEG/WebP")
    w, h = im.size
    if min(w, h) < MIN_SIDE or max(w, h) > MAX_SIDE or w * h > MAX_PIXELS:
        raise ReferenceError(f"image size {w}x{h} outside supported range")
    alpha = None
    if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
        a = np.asarray(im.convert("RGBA"))[..., 3]
        if (a < 128).mean() > 0.02:
            alpha = a >= 128
    rgb = np.asarray(im.convert("RGB"), dtype=np.float64) / 255.0
    sha = hashlib.sha256(data).hexdigest()
    return Reference(sha[:16], str(p), view, rgb, alpha,
                     {"sha256": sha, "file": p.name, "format": fmt, "mime": SUPPORTED_FORMATS[fmt], "width": w,
                      "height": h, "view": view, "authorized_by_user": True})


# ---------------------------------------------------------------- segmentation

def _otsu(values: np.ndarray) -> float:
    hist, edges = np.histogram(values, bins=256)
    p = hist / max(hist.sum(), 1)
    c = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(p)
    m0 = np.cumsum(p * c)
    mt = m0[-1]
    between = (mt * w0 - m0) ** 2 / np.maximum(w0 * (1 - w0), 1e-12)
    return float(c[int(np.argmax(between))])


def _dilate(m, r=1):
    out = m.copy()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            out |= np.roll(np.roll(m, dy, 0), dx, 1)
    return out


def _erode(m, r=1):
    return ~_dilate(~m, r)


def _components(mask: np.ndarray) -> tuple[np.ndarray, int]:
    """4-connected labeling via run-length union-find."""
    H, W = mask.shape
    labels = np.zeros((H, W), np.int32)
    parent = [0]

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    prev_runs = []
    for y in range(H):
        row = mask[y]
        d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
        starts, ends = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        runs = []
        for s, e in zip(starts, ends):
            lab = 0
            for ps, pe, pl in prev_runs:
                if ps < e and s < pe:
                    if lab == 0:
                        lab = find(pl)
                    else:
                        a, b = find(lab), find(pl)
                        if a != b:
                            parent[max(a, b)] = min(a, b)
                            lab = min(a, b)
            if lab == 0:
                parent.append(len(parent))
                lab = len(parent) - 1
            labels[y, s:e] = lab
            runs.append((s, e, lab))
        prev_runs = runs
    lut = np.array([find(i) for i in range(len(parent))], np.int32)
    return lut[labels], len(parent)


def segment(ref: Reference) -> tuple[np.ndarray, dict]:
    if ref.alpha is not None:
        mask = ref.alpha.copy()
        method, quality = "alpha_channel", 0.95
    else:
        img = ref.rgb
        H, W, _ = img.shape
        b = max(2, int(0.03 * min(H, W)))
        border = np.concatenate([img[:b].reshape(-1, 3), img[-b:].reshape(-1, 3), img[:, :b].reshape(-1, 3),
                                 img[:, -b:].reshape(-1, 3)])
        # single dominant background color; the figure may touch the border in cropped references
        c1 = np.median(border, 0)
        dist = np.linalg.norm(img - c1, axis=2)
        thr = float(np.clip(_otsu(dist.ravel()), 0.06, 0.35))
        mask = dist > thr
        sep = float((dist[mask].mean() - dist[~mask].mean()) / (dist.std() + 1e-9)) if mask.any() and (~mask).any() else 0
        method, quality = "border_color_model+otsu", float(np.clip(sep / 2.5, 0.1, 0.9))
    mask = _erode(_dilate(mask, 2), 2)  # close small gaps
    mask = _dilate(_erode(mask, 1), 1)  # remove speckle
    labels, n = _components(mask)
    if n <= 1 or not mask.any():
        raise ReferenceError("no foreground figure found in the reference")
    counts = np.bincount(labels.ravel())
    counts[0] = 0
    mask = labels == int(np.argmax(counts))
    # fill holes: background = components of ~mask touching the border
    inv_labels, _ = _components(~mask)
    edge = set(np.unique(np.concatenate([inv_labels[0], inv_labels[-1], inv_labels[:, 0], inv_labels[:, -1]])))
    # fill only small holes; larger enclosed regions are real background (e.g. between hair and neck)
    sizes = np.bincount(inv_labels.ravel())
    small = [i for i in range(len(sizes)) if i not in edge and sizes[i] < 0.0005 * mask.size]
    holes = ~mask & np.isin(inv_labels, small)
    mask |= holes
    frac = float(mask.mean())
    if frac < 0.01:
        raise ReferenceError("foreground figure is too small to analyze")
    return mask, {"method": method, "quality": round(quality, 3), "foreground_fraction": round(frac, 4)}


# ---------------------------------------------------------------- silhouette measurement

@dataclass
class Silhouette:
    top: int
    bottom: int
    head_h: float
    neck_row: int
    cx: float
    widths_hu: dict           # k (head units below crown) -> core width in head units (NaN if not visible)
    touches: dict
    height_hu: float | None   # full height in head units when the bottom is visible
    head_width_hu: float
    rows_visible_hu: float    # how many head units below the crown are inside the image


def _core_width(row: np.ndarray, cx: float) -> float:
    d = np.diff(np.concatenate([[0], row.astype(np.int8), [0]]))
    s, e = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
    if not len(s):
        return 0.0
    for a, b in zip(s, e):
        if a <= cx < b:
            return float(b - a)
    i = int(np.argmin(np.minimum(np.abs(s - cx), np.abs(e - cx))))
    return float(e[i] - s[i])


def measure_silhouette(mask: np.ndarray, crown_row: int | None = None, neck_mask: np.ndarray | None = None) -> Silhouette:
    """Width profile in head units. Shoulders: first sustained width jump on ``mask``; neck: narrowest
    row just above the shoulders on ``neck_mask`` (hair removed) when given."""
    H, W = mask.shape
    rows = np.nonzero(mask.any(1))[0]
    first, bottom = int(rows[0]), int(rows[-1])
    top = first if crown_row is None else crown_row
    span = max(bottom - first, 8)
    cols_top = np.nonzero(mask[first:first + max(2, span // 12)].any(0))[0]
    cx = float((cols_top[0] + cols_top[-1]) / 2)
    w = np.array([_core_width(mask[y], cx) for y in range(H)])
    win = max(3, int(round(span * 0.01)) | 1)
    ws = np.convolve(w, np.ones(win) / win, mode="same")
    # head width: robust max over the upper part of the head (before any jump)
    shoulder = None
    run_max = 0.0
    for y in range(top, bottom + 1):
        above = ws[top:max(top + 1, y - win)]
        run_max = float(above.max()) if len(above) else 0.0
        if y - top > 4 * win and run_max > 0 and ws[y] > 1.6 * run_max and ws[min(y + win, bottom)] > 1.6 * run_max:
            shoulder = y
            break
    nm = neck_mask if neck_mask is not None else mask
    wn = np.array([_core_width(nm[y], cx) for y in range(H)])
    wns = np.convolve(wn, np.ones(win) / win, mode="same")
    if shoulder is None:
        # second cue: a narrow neck followed by a much wider row (stylized art has narrow shoulders)
        for y in range(top + 4 * win, (shoulder if shoulder is not None else bottom) + 1):
            above = wns[top:y - win]
            if len(above) < 2 * win:
                continue
            hm = top + int(np.argmax(above))
            recent = wns[hm + 1:y - win]
            rmax = ws[top:max(top + 1, y - win)].max()
            if len(recent) >= win and 0 < recent.min() < 0.8 * wns[hm] and wns[y] > 2.4 * recent.min() \
                    and ws[y] > 1.1 * rmax and wns[min(y + win, bottom)] > 2.4 * recent.min():
                shoulder = y
                break
    if shoulder is not None:
        lo = top + int(0.55 * (shoulder - top))
        full_narrowing = ws[lo:shoulder].min() < 0.85 * ws[top:lo].max() if shoulder > lo else False
        seg_ = (ws if full_narrowing or neck_mask is None else wns)[lo:shoulder]
        valid = seg_ > 0.2 * max(run_max, 1)
        neck = lo + int(np.argmin(np.where(valid, seg_, np.inf))) if valid.any() else shoulder
    else:
        neck = bottom
    head_h = float(max(neck - top, 4))
    touches = {"top": first <= 0, "bottom": bottom >= H - 1, "left": bool(mask[:, 0].any()), "right": bool(mask[:, -1].any())}
    widths = {}
    for k in PROFILE_K:
        y = int(round(top + k * head_h))
        ok = top <= y <= bottom and not (touches["bottom"] and y >= H - 2)
        widths[float(k)] = wn[y] / head_h if ok else float("nan")
    height_hu = (bottom - top) / head_h if not touches["bottom"] and shoulder is not None else None
    hmax = float(np.max(wns[top:neck + 1])) if neck > top else float(run_max)
    return Silhouette(top, bottom, head_h, int(neck), cx, widths, touches, height_hu, hmax / head_h,
                      float((min(bottom, H - 1) - top) / head_h))


# ---------------------------------------------------------------- synthetic silhouettes

def field_silhouette(body: BodyParams, face: FaceParams, view: str = "front", cell: float = 0.009) -> np.ndarray:
    """Full orthographic silhouette of the SDF body (slow; used for images/overlays)."""
    skel = build_skeleton(body, face)
    F = build_field(body, face, skel)
    h = skel.marks["height"]
    ys = np.arange(h + 0.03, -0.02, -cell)
    zs = np.arange(-0.25, 0.30, cell * 1.5)
    if view == "side":  # rows = y (top first), cols = z (character faces image right)
        xs = np.arange(-0.25, 0.25, cell * 1.5)
        zs = np.arange(-0.25, 0.30, cell)
        X, Y, Z = np.meshgrid(xs, ys, zs, indexing="ij")
        d = F.evaluate(np.stack([X, Y, Z], -1).reshape(-1, 3)).reshape(len(xs), len(ys), len(zs))
        return (d.min(0) < 0).copy()
    xs = np.arange(-0.75, 0.75, cell)
    Xg, Yg, Zg = np.meshgrid(xs, ys, zs, indexing="ij")
    d = F.evaluate(np.stack([Xg, Yg, Zg], -1).reshape(-1, 3)).reshape(len(xs), len(ys), len(zs))
    return (d.min(2) < 0).T.copy()


def _rows_mask(F, ys, xs: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """Front-projected occupancy of several rows in one field evaluation. Returns (len(ys), len(xs))."""
    ys = np.asarray(ys, float)
    X, Z = np.meshgrid(xs, zs, indexing="ij")
    pts = np.empty((len(ys), X.size, 3))
    pts[:, :, 0] = X.ravel()
    pts[:, :, 1] = ys[:, None]
    pts[:, :, 2] = Z.ravel()
    d = F.evaluate(pts.reshape(-1, 3)).reshape(len(ys), len(xs), len(zs))
    return (d < 0).any(2)


def synthetic_silhouette(body: BodyParams, face: FaceParams, dx: float = 0.0075) -> Silhouette:
    """Measure the SDF body exactly as a reference silhouette would be measured, sampling only needed rows."""
    skel = build_skeleton(body, face)
    F = build_field(body, face, skel)
    m = skel.marks
    xs = np.arange(-0.62, 0.62, dx)
    zs = np.arange(-0.24, 0.28, 0.024)
    cx = len(xs) / 2 - 0.5
    ys = np.arange(m["y_crown"] + 0.03, m["y_crown"] - 0.03, -0.003)
    rows = _rows_mask(F, ys, xs, zs[(zs > -0.15) & (zs < 0.15)])
    crown = ys[int(np.argmax(rows.any(1)))]
    ny = np.arange(m["y_chin"] + 0.03, m["y_neck_base"] - 0.02, -0.003)
    nw = [_core_width(r, cx) for r in _rows_mask(F, ny, xs, zs)]
    neck_y = ny[int(np.argmin(nw))]
    head_h = crown - neck_y
    ky = [crown - k * head_h for k in PROFILE_K] + [crown - f * head_h for f in (0.3, 0.4, 0.5, 0.6)]
    rows = _rows_mask(F, ky, xs, zs)
    widths = {}
    for i, k in enumerate(PROFILE_K):
        widths[float(k)] = _core_width(rows[i], cx) * dx / head_h if ky[i] > 0 else float("nan")
    hmax = max(_core_width(r, cx) for r in rows[len(PROFILE_K):])
    return Silhouette(0, int(round(crown / dx)), head_h / dx, int(round(head_h / dx)), cx, widths,
                      {"top": False, "bottom": False, "left": False, "right": False}, crown / head_h,
                      hmax * dx / head_h, crown / head_h)


# ---------------------------------------------------------------- analysis

@dataclass
class Observation:
    ref: Reference
    mask: np.ndarray
    seg: dict
    sil: Silhouette
    regions: dict             # region -> "visible" | "cropped" | "unobservable"
    posture: str
    style: str
    colors: dict
    notes: list = field(default_factory=list)


def _region_visibility(sil: Silhouette, posture: str) -> dict:
    out = {}
    for reg, depth in REGION_DEPTH.items():
        if sil.touches["top"] and depth <= 1.0:
            out[reg] = "cropped"
        elif depth <= sil.rows_visible_hu + (0.3 if not sil.touches["bottom"] else 0.0):
            out[reg] = "visible"
        else:
            out[reg] = "cropped"
    if posture == "seated":
        for reg in ("thighs", "knees", "lower_legs", "feet"):
            out[reg] = "occluded_by_pose"
    out["back"] = "unobservable"
    return out


def _skin_from_rgb(c_srgb: np.ndarray) -> tuple[float, float]:
    lin = srgb_to_linear(c_srgb)
    best, best_t = 1e9, 0.3
    pal = [srgb_to_linear(s) for s in _SKIN_SRGB]
    for t in np.linspace(0, 1, 101):
        x = t * (len(pal) - 1)
        i = min(int(x), len(pal) - 2)
        f = x - i
        c = pal[i] * (1 - f) + pal[i + 1] * f
        err = np.linalg.norm(np.log(lin + 1e-3) - np.log(c + 1e-3))
        if err < best:
            best, best_t = err, t
    warm = (c_srgb[1] - c_srgb[2]) - (0.13 - 0.04 * best_t)
    return float(best_t), float(np.clip(warm * 6, -1, 1))


def analyze(ref: Reference, posture_hint: str | None = None) -> Observation:
    mask, seg = segment(ref)
    sil, hair_excluded = _measure_with_hair_exclusion(ref, mask)
    seg = dict(seg, hair_excluded_from_measurement=hair_excluded)
    notes = []
    style = "realistic"
    posture = posture_hint or "standing"
    if sil.height_hu is not None and posture_hint is None:
        H = sil.height_hu
        hip_k = 3.6
        lower = [v for k, v in sil.widths_hu.items() if k >= hip_k and not math.isnan(v)]
        hipw = sil.widths_hu.get(3.5, float("nan"))
        if H < 6.3:
            sh = np.nanmax([sil.widths_hu.get(k, np.nan) for k in (1.5, 1.75, 2.0)])
            ratio = sh / max(sil.head_width_hu, 1e-6)
            if ratio >= 2.0:
                posture = "seated"
                notes.append(f"figure is {H:.1f} heads tall with realistic shoulders ({ratio:.1f} head widths): "
                             "classified seated/crouched; leg proportions are not measured")
            else:
                style = "stylized"
                notes.append(f"figure is {H:.1f} heads tall with {ratio:.1f}-head-width shoulders: classified "
                             "stylized proportions")
    regions = _region_visibility(sil, posture)
    colors = _sample_colors(ref, mask, sil, regions)
    if sil.rows_visible_hu < 2.0:
        notes.append("head-and-shoulders/portrait reference: body below the shoulders is completed from presets")
    elif sil.touches["bottom"]:
        notes.append(f"reference cropped at ~{sil.rows_visible_hu:.1f} head units: lower body completed from presets")
    if sil.head_h > 0.35 * ref.rgb.shape[0]:
        notes.append("close-up framing: head-relative proportions are perspective-sensitive and blended with priors")
    return Observation(ref, mask, seg, sil, regions, posture, style, colors, notes)


def _fill_row_gaps(mask: np.ndarray, gap: int) -> np.ndarray:
    """Close horizontal gaps shorter than ``gap`` pixels (eyes, mouth, shadows inside the face)."""
    out = mask.copy()
    for y in np.nonzero(mask.any(1))[0]:
        d = np.diff(np.concatenate([[0], mask[y].astype(np.int8), [0]]))
        s, e = np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]
        for a, b in zip(e[:-1], s[1:]):
            if b - a <= gap:
                out[y, a:b] = True
    return out


def _measure_with_hair_exclusion(ref: Reference, mask: np.ndarray) -> tuple[Silhouette, bool]:
    """Long hair hides the neck. Remove crown-colored pixels for width measurement; keep the true crown."""
    img = ref.rgb
    rows = np.nonzero(mask.any(1))[0]
    top = int(rows[0])
    band = mask.copy()
    band[: top] = False
    band[top + max(3, int(0.03 * mask.shape[0])):] = False
    if band.sum() < 20:
        return measure_silhouette(mask), False
    hair = np.median(img[band], 0)
    cols = mask[:, mask.shape[1] // 2]
    center = np.median(img[cols, mask.shape[1] // 2], 0) if cols.any() else hair
    if np.linalg.norm(hair - center) < 0.15:
        return measure_silhouette(mask), False
    hairlike = np.linalg.norm(img - hair, axis=2) < 0.10
    first = measure_silhouette(mask)
    zone_end = first.top + 2.6 * first.head_h if first.neck_row < mask.shape[0] - 1 else mask.shape[0]
    hairlike[int(min(zone_end, mask.shape[0])):] = False
    m2 = mask & ~hairlike
    m2 = _fill_row_gaps(_dilate(_erode(m2, 1), 1), max(3, int(0.03 * mask.shape[1])))
    if m2.sum() < 0.3 * mask.sum():
        return measure_silhouette(mask), False
    sil = measure_silhouette(mask, crown_row=top, neck_mask=m2)
    # the skull top sits under the hair: compensate with a typical crown-hair volume (prior, ~6% of head height)
    adj = int(round(HAIR_CROWN_FRACTION * sil.head_h))
    return measure_silhouette(mask, crown_row=top + adj, neck_mask=m2), True


def _median_color(img, sel):
    if sel.sum() < 10:
        return None
    px = img[sel]
    lum = px.mean(1)
    keep = lum >= np.percentile(lum, 35)  # lit side; avoids shadowed pixels
    return np.median(px[keep], 0)


def _sample_colors(ref, mask, sil, regions) -> dict:
    img = ref.rgb
    H, W = mask.shape
    yy, xx = np.mgrid[0:H, 0:W]
    hh = sil.head_h
    top = sil.top
    hw = sil.head_width_hu * hh
    out = {}
    face_band = mask & (yy > top + 0.45 * hh) & (yy < top + 0.85 * hh) & (np.abs(xx - sil.cx) < 0.28 * hw)
    crown = mask & (yy >= top) & (yy < top + 0.12 * hh) & (np.abs(xx - sil.cx) < 0.3 * hw)
    skin = _median_color(img, face_band)
    hair = _median_color(img, crown)
    if skin is not None:
        out["skin"] = skin
    if hair is not None and skin is not None and np.linalg.norm(hair - skin) > 0.12:
        out["hair"] = hair
        # long hair: hair-colored pixels beside the neck/shoulders below the chin
        below = mask & (yy > top + 0.95 * hh) & (yy < top + 1.5 * hh) & (np.abs(xx - sil.cx) < 1.0 * hw)
        hairlike = np.linalg.norm(img - hair, axis=2) < 0.10
        frac = (below & hairlike).sum() / max(below.sum(), 1)
        out["hair_long"] = bool(frac > 0.10)
        out["hair_long_fraction"] = float(frac)
        out.update(_hair_shape(img, mask, sil, hair, skin))
    if regions.get("chest") == "visible":
        chest = mask & (yy > top + 1.9 * hh) & (yy < top + 2.6 * hh) & (np.abs(xx - sil.cx) < 0.5 * hw)
        out["torso"] = _median_color(img, chest)
    if regions.get("thighs") == "visible":
        th = mask & (yy > top + 4.1 * hh) & (yy < top + 4.8 * hh) & (np.abs(xx - sil.cx) < 1.1 * hw)
        out["thigh"] = _median_color(img, th)
    rows_any = np.nonzero(mask.any(1))[0]
    bottom = int(rows_any.max()) if len(rows_any) else H
    feet_in_frame = bottom < H - 3 and bottom - top > 5 * hh
    if regions.get("lower_legs") == "visible":
        if feet_in_frame:  # anchor on the soles: head units drift when long hair hides the chin
            span = bottom - top
            sh = mask & (yy > bottom - 0.24 * span) & (yy < bottom - 0.10 * span) & (np.abs(xx - sil.cx) < 1.1 * hw)
        else:
            sh = mask & (yy > top + 6.0 * hh) & (yy < top + 6.8 * hh) & (np.abs(xx - sil.cx) < 1.1 * hw)
        out["shin"] = _median_color(img, sh)
    if regions.get("thighs") == "visible":
        # a skirt or robe closes the gap between the legs below the crotch (legs apart in a standing reference)
        cx = int(round(sil.cx))
        def joined(a):
            r = int(top + a * hh)
            return bool(r < H and mask[r, max(cx - 2, 0):cx + 3].all())
        out["legs_joined_thigh"] = sum(joined(a) for a in (4.5, 4.8, 5.1)) / 3
        out["legs_joined_shin"] = sum(joined(a) for a in (6.0, 6.3)) / 2 if regions.get("lower_legs") == "visible" else 0.0
    return {k: v for k, v in out.items() if v is not None}


def _hair_shape(img, mask, sil, hair, skin=None) -> dict:
    """Hair length (lowest hair-colored row beside the face/neck, in head units below the crown) and fringe
    coverage of the forehead band (with left/right asymmetry).  Crops that cut the hair off are flagged."""
    H, W = mask.shape
    yy, xx = np.mgrid[0:H, 0:W]
    hh, top, hw = sil.head_h, sil.top, sil.head_width_hu * sil.head_h
    dh = np.linalg.norm(img - hair, axis=2)
    hairlike = (dh < 0.22) & mask  # shaded hair varies a lot; closer to hair than to skin
    if skin is not None:
        hairlike &= dh < np.linalg.norm(img - skin, axis=2)
    # only hair connected to the crown counts (dark clothing or shoes can share the hair color)
    lab, _ = _components(_dilate(hairlike, 1) & mask & (np.abs(xx - sil.cx) < 1.3 * hw))
    crown_labels = np.unique(lab[int(top):int(top + 0.12 * hh) + 1][hairlike[int(top):int(top + 0.12 * hh) + 1]])
    hairlike = np.isin(lab, crown_labels[crown_labels > 0]) & hairlike
    side = hairlike & (yy > top + 0.3 * hh) & (np.abs(xx - sil.cx) > 0.30 * hw)
    rows = np.nonzero(side.sum(1) >= 3)[0]
    low = int(rows.max()) if len(rows) else int(top)
    # forehead between the natural hairline and the brows: hair here is a fringe
    band = mask & (yy > top + 0.28 * hh) & (yy < top + 0.36 * hh) & (np.abs(xx - sil.cx) < 0.22 * hw)
    left, right = band & (xx < sil.cx), band & (xx >= sil.cx)
    fl = (hairlike & left).sum() / max(left.sum(), 1)
    fr = (hairlike & right).sum() / max(right.sum(), 1)
    return {"hair_extent_hu": float((low - top) / hh), "hair_cropped": bool(low >= H - 3),
            "fringe": float((fl + fr) / 2), "fringe_asymmetry": float(abs(fl - fr))}


def classify_hair(c: dict) -> tuple[str, float, str]:
    """Map measured hair shape to a studio hairstyle: (style, confidence, note)."""
    ext, fringe, asym = c.get("hair_extent_hu", 0.0), c.get("fringe", 0.0), c.get("fringe_asymmetry", 0.0)
    if c.get("hair_cropped"):
        return "long", 0.3, f"hair reaches the image edge ({ext:.2f} head units visible): length is a lower bound"
    if ext >= HAIR_LONG_HU:
        return "long", 0.45, f"hair extends {ext:.2f} head units below the crown"
    if ext >= HAIR_BOB_HU:
        if fringe > FRINGE_MIN:
            return "bangs", 0.4, f"jaw-length hair ({ext:.2f} hu) with a fringe over the forehead (coverage {fringe:.2f}, " \
                f"left/right difference {asym:.2f})"
        return "bob", 0.4, f"hair ends near the jaw ({ext:.2f} head units below the crown)"
    if fringe > FRINGE_MIN:
        return "pixie", 0.35, f"short hair ({ext:.2f} hu) with forehead coverage {fringe:.2f}"
    return "short", 0.4, f"short hair ({ext:.2f} head units below the crown)"


# ---------------------------------------------------------------- fitting

FIT_GROUPS = {
    "shoulders": ["body.shoulder_width"],
    "chest": ["body.chest_width"],
    "waist": ["body.waist_width"],
    "hips_pelvis": ["body.hip_width"],
    "thighs": ["body.thigh_thickness", "body.leg_length"],
    "lower_legs": ["body.calf_thickness"],
    "head": ["face.face_width"],
}
_STEPS = {"body.shoulder_width": 0.06, "body.chest_width": 0.06, "body.waist_width": 0.06, "body.body_fat": 0.12,
          "body.hip_width": 0.06, "body.thigh_thickness": 0.07, "body.leg_length": 0.05, "body.calf_thickness": 0.07,
          "face.face_width": 0.05, "body.head_size": 0.05}
_BOUNDS = {"body.body_fat": (0.0, 1.0)}


HAIR_BOB_HU = 0.55     # hair length thresholds (head units below the crown), calibrated on the generated references
HAIR_LONG_HU = 1.0     # (front view: long hair behind the shoulders shows only beside the neck, so margins are small)
FRINGE_MIN = 0.12      # hair coverage of the forehead band just above the brows
GARMENT_EASE_HU = 0.06   # silhouette width added by garment thickness + ease, in head units (prior)


def clothed_rows(obs) -> set:
    rows = set()
    if obs is None:
        return rows
    skin = obs.colors.get("skin")
    if skin is None:
        return rows
    if "torso" in obs.colors and np.linalg.norm(obs.colors["torso"] - skin) > 0.14:
        rows |= {k for k in PROFILE_K if 1.5 <= k <= 3.4}
    if "thigh" in obs.colors and np.linalg.norm(obs.colors["thigh"] - skin) > 0.14:
        rows |= {k for k in PROFILE_K if 3.4 < k <= 4.7}
    return {float(k) for k in rows}


def _loss(sil_ref: Silhouette, sil_syn: Silhouette, use_height: bool, clothed: set = frozenset()) -> float:
    errs = []
    for k, v in sil_ref.widths_hu.items():
        s = sil_syn.widths_hu.get(k, float("nan"))
        if math.isnan(v) or math.isnan(s):
            continue
        wgt = 0.5 if k < 1.0 else 1.0
        if k in clothed:  # silhouette includes the garment: remove its ease and trust it less
            v = v - GARMENT_EASE_HU
            wgt *= 0.4
        errs.append(wgt * (v - s) ** 2)
    loss = float(np.mean(errs)) if errs else 1e3
    if use_height and sil_ref.height_hu and sil_syn.height_hu:
        loss += 0.02 * (sil_ref.height_hu - sil_syn.height_hu) ** 2
    return loss


def _spec_parts(values: dict, base_body: BodyParams, base_face: FaceParams):
    b = {k.split(".", 1)[1]: v for k, v in values.items() if k.startswith("body.")}
    f = {k.split(".", 1)[1]: v for k, v in values.items() if k.startswith("face.")}
    return base_body.with_(**b), base_face.with_(**f)


def fit(obs: Observation, base_body: BodyParams, base_face: FaceParams, keys: list, rounds: int = 2,
        locked: set = frozenset(), log=None) -> tuple[dict, float, Silhouette]:
    keys = [k for k in keys if k not in locked]
    use_height = obs.sil.height_hu is not None and obs.posture == "standing"
    clothed = clothed_rows(obs)
    vals = {k: getattr(base_body if k.startswith("body.") else base_face, k.split(".", 1)[1]) for k in keys}

    def evaluate(v):
        b, f = _spec_parts(v, base_body, base_face)
        syn = synthetic_silhouette(b, f)
        return _loss(obs.sil, syn, use_height, clothed), syn

    best, syn = evaluate(vals)
    for r in range(rounds):
        for k in keys:
            step = _STEPS.get(k, 0.05) / (r + 1)
            for direction in (1, -1):
                improved = True
                while improved:
                    trial = dict(vals)
                    lo, hi = _BOUNDS.get(k, (0.65, 1.55))
                    trial[k] = float(np.clip(vals[k] + direction * step, lo, hi))
                    if trial[k] == vals[k]:
                        break
                    try:
                        l2, s2 = evaluate(trial)
                    except Exception:
                        break
                    improved = l2 < best - 1e-6
                    if improved:
                        best, vals, syn = l2, trial, s2
                        if log:
                            log(f"    {k} -> {vals[k]:.3f}  loss {best:.5f}")
    return vals, best, syn


# ---------------------------------------------------------------- top-level reconstruction

def pb_fat_prior(vals: dict) -> float:
    girth = np.mean([vals.get("body.waist_width", 1.0), vals.get("body.thigh_thickness", 1.0)])
    return float(np.clip(0.35 + (girth - 1.0) * 1.5, 0.0, 1.0))


def _whr(sil: Silhouette) -> float | None:
    w = sil.widths_hu
    waist = [w[k] for k in (2.5, 2.75, 3.0, 3.25) if not math.isnan(w.get(k, float("nan")))]
    hips = [w[k] for k in (3.5, 3.75, 4.0, 4.25) if not math.isnan(w.get(k, float("nan")))]
    if len(waist) < 3 or len(hips) < 3 or max(hips) <= 0:
        return None
    return min(waist) / max(hips)


def reconstruct(refs: list[Reference], base_dna: dict | None = None, interpretation: str = "realistic",
                height_m: float | None = None, posture_hint: str | None = None, log=print,
                fit_rounds: int = 1) -> tuple[dict, dict]:
    """Return (dna, report). base_dna locks are respected; unseen regions are completed from presets."""
    if not refs:
        raise ReferenceError("at least one reference image is required")
    front = next((r for r in refs if r.view in ("front", "three_quarter")), refs[0])
    obs = analyze(front, posture_hint)
    side_obs = None
    for r in refs:
        if r.view == "side":
            side_obs = analyze(r, posture_hint)
    log(f"  segmentation: {obs.seg}; posture={obs.posture}; style={obs.style}")
    log(f"  visible rows: {obs.sil.rows_visible_hu:.2f} head units; regions: {obs.regions}")
    locked = set()
    if base_dna is not None:
        locked = {k for k, t in base_dna["traits"].items() if t["locked"]}
    # sex prior: fit from both presets on the visible torso, keep the better one
    vis = obs.regions
    fit_keys = []
    for reg, keys in FIT_GROUPS.items():
        if vis.get(reg) == "visible":
            fit_keys += keys
    if obs.sil.height_hu is not None and obs.posture == "standing":
        fit_keys.append("body.head_size")
    whr = _whr(obs.sil)
    if whr is not None:
        fem = float(np.clip((WHR_MALE - whr) / (WHR_MALE - WHR_FEMALE), 0.0, 1.0))
        fem_note = f"waist/hip width ratio {whr:.3f} (male preset {WHR_MALE}, female preset {WHR_FEMALE})"
        fem_prov, fem_conf = "estimated", float(np.clip(0.35 + 0.5 * abs(fem - 0.5), 0.35, 0.6))
    else:
        fem, fem_prov, fem_conf = 0.5, "invented", 0.1
        fem_note = "waist and hips not both visible: no body-type cue; neutral prior (edit and lock to correct)"
    pname = "female" if fem > 0.66 else ("male" if fem < 0.34 else "neutral")
    b0, f0, _ = preset(pname)
    b0 = b0.with_(femininity=round(fem, 3))
    if base_dna is not None:
        spec = dnam.to_spec(base_dna)
        b0, f0 = (spec.body if "body.femininity" in locked else spec.body.with_(femininity=round(fem, 3))), spec.face
    if height_m:
        b0 = b0.with_(height_m=height_m)
    log(f"  body-type cue: {fem_note} -> femininity {fem:.2f}, prior '{pname}'; fitting {fit_keys}")
    vals, loss, syn = fit(obs, b0, f0, fit_keys, rounds=fit_rounds, locked=locked, log=None)
    log(f"    fit loss {loss:.5f}")
    candidates = [(loss, pname, vals, b0, f0, syn)]
    resid = math.sqrt(loss)
    fit_conf = float(np.clip(1.0 - resid / 0.25, 0.15, 0.9)) * (0.6 + 0.4 * obs.seg["quality"])
    est = {}
    src = [front.id] + ([side_obs.ref.id] if side_obs else [])

    def put(key, value, prov, conf, note):
        est[key] = (value, prov, round(float(conf), 3), note)

    cl = clothed_rows(obs)
    covered = {"body.chest_width", "body.waist_width", "body.shoulder_width"} if any(1.5 <= k <= 3.4 for k in cl) else set()
    if any(3.4 < k <= 4.7 for k in cl):
        covered |= {"body.hip_width", "body.thigh_thickness"}
    for k, v in vals.items():
        if k == "face.face_width":
            put(k, round(float(v), 4), "estimated", fit_conf * 0.5, "head silhouette width; hair and ears bias it")
        elif k in covered:
            put(k, round(float(v), 4), "estimated", fit_conf * 0.6,
                f"silhouette fit through clothing (garment ease prior {GARMENT_EASE_HU} hu removed)")
        else:
            put(k, round(float(v), 4), "observed", fit_conf, f"silhouette fit (residual {resid:.3f} head units)")
    if "body.body_fat" not in est:
        put("body.body_fat", pb_fat_prior(vals), "estimated", 0.3, "from fitted waist and thigh girth")
    if "body.head_size" in vals and obs.style == "stylized":
        if interpretation == "realistic":
            put("body.head_size", float(np.clip(vals["body.head_size"], 0.95, 1.12)), "estimated", 0.4,
                "stylized head ratio reinterpreted toward realistic adult proportions")
        else:
            put("body.head_size", float(np.clip(vals["body.head_size"], 0.75, 1.45)), "observed", fit_conf * 0.8,
                "stylized head ratio kept (faithful interpretation, clamped to stability range)")
    pb, pf, _ = preset(pname)
    put("body.femininity", round(fem, 3), fem_prov, fem_conf, fem_note)
    put("body.breast_size", pb.breast_size, "invented" if side_obs is None else "estimated", 0.25,
        "breast volume is not observable in a front silhouette; preset prior" if side_obs is None else "side view")
    # unseen regions: invented from the chosen preset (never presented as observed)
    for reg, keys in FIT_GROUPS.items():
        if vis.get(reg) != "visible":
            for k in keys:
                g, n = k.split(".", 1)
                base = pb if g == "body" else pf
                put(k, getattr(base, n), "invented", 0.2, f"region '{reg}' not visible ({vis.get(reg)}); preset prior")
    if "body.head_size" not in vals:
        put("body.head_size", 1.0, "invented", 0.2, "full height not visible; adult head ratio prior")
    if height_m:
        put("body.height_m", float(height_m), "user", 1.0, "height supplied by user")
    else:
        put("body.height_m", pb.height_m, "estimated", 0.2,
            "absolute scale is not observable in a single image; population prior for the chosen body type")
    if obs.posture == "seated":
        put("body.leg_length", pb.leg_length, "invented", 0.2, "seated pose: legs foreshortened/occluded; neutral pose regenerated")
    for n in ("arm_length", "hand_size", "foot_size", "neck_length", "torso_length"):
        if f"body.{n}" not in est:
            put(f"body.{n}", getattr(pb, n), "invented", 0.2, "not measured by the silhouette method; preset prior")
    for n in FaceParams.names():
        if f"face.{n}" not in est:
            put(f"face.{n}", getattr(pf, n), "invented", 0.15,
                "facial landmarks are not detected (no landmark model available); preset prior")
    # appearance from color samples
    c = obs.colors
    if "skin" in c and vis.get("head") == "visible":
        tone, under = _skin_from_rgb(c["skin"])
        put("appearance.skin_tone", round(tone, 3), "observed", 0.55, "median lit face-band color (lighting-dependent)")
        put("appearance.undertone", round(under, 3), "estimated", 0.35, "warm/cool from face-band chroma")
    if "hair" in c:
        put("appearance.hair_color", linear_to_hex(srgb_to_linear(c["hair"])), "observed", 0.6, "crown-band color")
        style, conf, note = classify_hair(c)
        put("appearance.hair_style", style, "estimated", conf, note)
    elif "skin" in c:
        put("appearance.hair_style", "buzz", "estimated", 0.3, "crown color matches skin: very short or no hair")
    put("appearance.eye_color", "brown", "invented", 0.1, "iris color is not measured")
    outfit, colors, garment_notes = [], {}, {}
    skin = c.get("skin")
    if skin is not None:
        def differs(x):
            return x is not None and np.linalg.norm(x - skin) > 0.14
        if differs(c.get("torso")):
            outfit.append("tshirt")
            colors["tshirt"] = linear_to_hex(srgb_to_linear(c["torso"]))
        if differs(c.get("thigh")):
            if c.get("legs_joined_thigh", 0) >= 0.66 and obs.posture == "standing":
                g = "robe" if c.get("legs_joined_shin", 0) >= 0.5 else "skirt"
                garment_notes[g] = "no gap between the legs at thigh height" + (" or shin height" if g == "robe" else "")
            else:
                g = "pants" if differs(c.get("shin")) else "shorts"
            outfit.append(g)
            colors[g] = linear_to_hex(srgb_to_linear(c["thigh"]))
    if outfit:
        put("wardrobe.outfit", outfit, "observed", 0.5, "garment colors differ from skin in torso/leg regions"
            + "".join(f"; {g}: {n}" for g, n in garment_notes.items()))
        put("wardrobe.colors", colors, "observed", 0.5, "median garment colors")
    else:
        put("wardrobe.outfit", ["tshirt", "shorts"], "invented", 0.3,
            "no garments observed (or regions not visible); clothed default for public use")
    # assemble DNA
    if base_dna is None:
        dna = dnam.new_dna(pname, name=Path(front.path).stem)
    else:
        dna = copy.deepcopy(base_dna)
    dna = dnam.apply_estimates(dna, est, src)
    dna["sources"] = [r.meta | {"id": r.id} for r in refs]
    dna["regions"] = {"front": obs.regions, **({"side": side_obs.regions} if side_obs else {})}
    dna["reconstruction"] = {
        "method": METHOD, "pretrained_model": None, "landmark_model": None, "generative_model": None,
        "interpretation": interpretation, "posture_detected": obs.posture, "style_detected": obs.style,
        "segmentation": obs.seg, "fit_residual_head_units": round(resid, 4), "body_type_prior": pname,
        "fit_confidence": round(fit_conf, 3), "notes": obs.notes,
        "completion": "every region not marked 'visible' was generated from the preset prior (provenance invented)",
        "likeness": "not claimed: the method fits body proportions to a silhouette and samples colors; facial identity "
                    "and unseen anatomy are not reconstructed and must not be presented as a likeness",
        "uncertainty": uncertainty_intervals(est),
    }
    report = {"observation": obs, "synthetic_silhouette": syn, "loss": loss, "estimates": est, "prior": pname,
              "waist_hip_ratio": whr}
    return dna, report


def uncertainty_intervals(est: dict) -> dict:
    """Heuristic plausible range per numeric estimate: the trait's regeneration window, shrunk by confidence.

    ``[value - (1 - c) * w / 2, value + (1 - c) * w / 2]`` with ``w`` the DNA prior window (relative +/-15 % when
    the trait has no explicit window).  It communicates how loosely each value is pinned down; it is not a
    calibrated statistical interval."""
    out = {}
    for k, (v, prov, conf, _note) in est.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        lo, hi = dnam._PRIOR.get(k, (v * dnam._DEFAULT_WINDOW[0], v * dnam._DEFAULT_WINDOW[1]))
        half = (1.0 - conf) * abs(hi - lo) / 2
        out[k] = [round(v - half, 4), round(v + half, 4)]
    return out


def overlay_image(obs: Observation, syn: Silhouette, syn_mask: np.ndarray) -> np.ndarray:
    """Reference with its segmentation outline and the fitted character's silhouette (scaled by head units)."""
    img = (obs.ref.rgb * 255).astype(np.uint8).copy()
    H, W = obs.mask.shape
    edge = obs.mask & ~_erode(obs.mask, 1)
    img[edge] = (255, 210, 0)
    # scale synthetic mask so head units align
    s = obs.sil.head_h / syn.head_h
    sm = Image.fromarray((syn_mask * 255).astype(np.uint8))
    sm = np.asarray(sm.resize((max(1, int(sm.width * s)), max(1, int(sm.height * s))), Image.NEAREST)) > 127
    oy = int(obs.sil.top - syn.top * s)
    ox = int(obs.sil.cx - syn.cx * s)
    se = sm & ~_erode(sm, 1)
    ys, xs = np.nonzero(se)
    ys, xs = ys + oy, xs + ox
    ok = (ys >= 0) & (ys < H) & (xs >= 0) & (xs < W)
    img[ys[ok], xs[ok]] = (0, 220, 255)
    return img
