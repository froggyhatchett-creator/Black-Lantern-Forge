"""Surface appearance: skin tone, regional tinting, eye/hair colors and procedural textures.

All textures are synthesized here (FFT-filtered noise, so they tile seamlessly)
and embedded in the GLB; no external image assets are used.  Colors are linear RGB.
"""

from __future__ import annotations

import io
import math
from dataclasses import asdict, dataclass

import numpy as np
from PIL import Image

from forge_character_forge.params import ParameterError

HAIR_STYLES = ("bald", "buzz", "short", "pixie", "bob", "bangs", "long", "bun")
EYE_COLORS = {"brown": (0.20, 0.09, 0.03), "dark_brown": (0.08, 0.035, 0.015), "hazel": (0.28, 0.20, 0.06),
              "green": (0.12, 0.25, 0.10), "blue": (0.10, 0.22, 0.45), "grey": (0.30, 0.33, 0.36),
              "amber": (0.45, 0.22, 0.03)}
# sRGB anchors from light to deep skin; interpolated in linear space
_SKIN_SRGB = [(0.97, 0.83, 0.75), (0.87, 0.67, 0.56), (0.76, 0.54, 0.40), (0.60, 0.40, 0.28),
              (0.42, 0.27, 0.18), (0.25, 0.16, 0.11)]


def srgb_to_linear(c):
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def linear_to_srgb(c):
    c = np.clip(np.asarray(c, float), 0, 1)
    return np.where(c <= 0.0031308, c * 12.92, 1.055 * c ** (1 / 2.4) - 0.055)


def hex_to_linear(h: str) -> np.ndarray:
    h = h.lstrip("#")
    if len(h) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in h):
        raise ParameterError(f"color must be #rrggbb; got {h!r}")
    return srgb_to_linear([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def linear_to_hex(c) -> str:
    s = linear_to_srgb(c)
    return "#" + "".join(f"{int(round(v * 255)):02x}" for v in s)


@dataclass(frozen=True)
class AppearanceParams:
    skin_tone: float = 0.3          # 0 light .. 1 deep
    undertone: float = 0.0          # -1 cool/pink .. +1 warm/olive
    flush: float = 0.5              # regional redness 0..1
    eye_color: str = "brown"
    hair_style: str = "short"
    hair_color: str = "#3b2416"
    hair_highlight_color: str = "#a47b52"   # streak color (appearance only; never anatomy)
    hair_highlight_amount: float = 0.0     # 0 none .. 1 strong streaks
    hair_gradient_enabled: bool = False    # root-to-tip gradient (appearance only)
    hair_gradient_root_color: str = ""     # empty = use hair_color
    hair_gradient_tip_color: str = "#20d0c8"
    hair_gradient_transition: float = 0.45 # 0=near root .. 1=near tip, midpoint of blend in hair-local length
    brow_color: str = ""            # empty = derived from hair
    lip_tint: float = 0.5
    skin_roughness: float = 0.5

    def __post_init__(self):
        for name in ("skin_tone", "flush", "lip_tint", "skin_roughness", "hair_highlight_amount",
                     "hair_gradient_transition"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not 0.0 <= v <= 1.0:
                raise ParameterError(f"AppearanceParams.{name} must be in [0, 1]; got {v!r}")
        if not isinstance(self.hair_gradient_enabled, bool):
            raise ParameterError("AppearanceParams.hair_gradient_enabled must be bool")
        if not isinstance(self.undertone, (int, float)) or not -1.0 <= self.undertone <= 1.0:
            raise ParameterError("AppearanceParams.undertone must be in [-1, 1]")
        if self.eye_color not in EYE_COLORS and not str(self.eye_color).startswith("#"):
            raise ParameterError(f"eye_color must be one of {sorted(EYE_COLORS)} or #rrggbb")
        if self.eye_color.startswith("#"):
            hex_to_linear(self.eye_color)
        if self.hair_style not in HAIR_STYLES:
            raise ParameterError(f"hair_style must be one of {HAIR_STYLES}")
        hex_to_linear(self.hair_color)
        hex_to_linear(self.hair_highlight_color)
        if self.hair_gradient_root_color:
            hex_to_linear(self.hair_gradient_root_color)
        hex_to_linear(self.hair_gradient_tip_color)
        if self.brow_color:
            hex_to_linear(self.brow_color)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, d):
        unknown = set(d) - set(cls.__dataclass_fields__)
        if unknown:
            raise ParameterError(f"unknown AppearanceParams fields: {sorted(unknown)}")
        return cls(**d)

    def skin_linear(self) -> np.ndarray:
        x = self.skin_tone * (len(_SKIN_SRGB) - 1)
        i = min(int(x), len(_SKIN_SRGB) - 2)
        t = x - i
        c = srgb_to_linear(_SKIN_SRGB[i]) * (1 - t) + srgb_to_linear(_SKIN_SRGB[i + 1]) * t
        warm = np.array([1.0, 1.0, 0.86]) if self.undertone > 0 else np.array([1.0, 0.94, 0.97])
        return c * (1 + (warm - 1) * abs(self.undertone))

    def eye_linear(self) -> np.ndarray:
        return np.array(EYE_COLORS[self.eye_color]) if self.eye_color in EYE_COLORS else hex_to_linear(self.eye_color)

    def hair_linear(self) -> np.ndarray:
        return hex_to_linear(self.hair_color)

    def hair_vertex_colors(self, unit_verts: np.ndarray) -> np.ndarray | None:
        """Per-vertex hair color. Streak highlights and optional root-to-tip gradient.

        unit_verts are in head-frame unit space (chin at y=0, face +z). Gradient uses
        the hair mesh's own Y extent in that frame so it follows the hair, not world height.
        Returns None when neither feature is active (preserves historical solid color).
        """
        if self.hair_highlight_amount <= 0 and not self.hair_gradient_enabled:
            return None
        v = np.asarray(unit_verts, float)
        base = self.hair_linear()
        if self.hair_gradient_enabled:
            root = hex_to_linear(self.hair_gradient_root_color) if self.hair_gradient_root_color else base
            tip = hex_to_linear(self.hair_gradient_tip_color)
            y = v[:, 1]
            y_min, y_max = float(y.min()), float(y.max())
            # 0 at crown (highest Y = root), 1 at lowest tips
            t = np.clip((y_max - y) / max(y_max - y_min, 1e-6), 0, 1)
            # transition is the midpoint of a smooth blend; width fixed for stability
            mid = float(self.hair_gradient_transition)
            width = 0.18
            s = np.clip((t - (mid - width)) / (2 * width), 0, 1)
            s = s * s * (3 - 2 * s)  # smoothstep
            col = root[None, :] * (1 - s[:, None]) + tip[None, :] * s[:, None]
        else:
            col = np.tile(base, (len(v), 1))
        if self.hair_highlight_amount > 0:
            m = hair_highlight_mask(v) * self.hair_highlight_amount
            col = col * (1 - m[:, None]) + hex_to_linear(self.hair_highlight_color)[None, :] * m[:, None]
        return col

    def brow_linear(self) -> np.ndarray:
        return hex_to_linear(self.brow_color) if self.brow_color else self.hair_linear() * 0.8


def hair_highlight_mask(unit_verts: np.ndarray) -> np.ndarray:
    """Vertical highlight streaks in [0, 1] from head-space positions (deterministic, shared with the studio)."""
    from forge_character_forge.hair import noise3
    v = np.asarray(unit_verts, float)
    n = noise3(v * np.array([70.0, 3.0, 70.0]), 9) * 0.75 + noise3(v * np.array([150.0, 6.0, 150.0]), 10) * 0.25
    face = np.clip((0.06 - v[:, 2]) / 0.06, 0, 1) * 0.15  # face-framing pieces a little lighter
    return np.clip((n + face - 0.52) / 0.2, 0, 1)


def _value_noise3(p: np.ndarray, scale: float, seed: int = 7) -> np.ndarray:
    """Smooth deterministic 3D noise in [-1, 1] (sum of sines, cheap and stable)."""
    rng = np.random.default_rng(seed)
    out = np.zeros(len(p))
    for _ in range(6):
        d = rng.normal(size=3)
        d /= np.linalg.norm(d)
        f = scale * (0.7 + 0.6 * rng.random())
        out += np.sin(p @ d * f * 2 * np.pi + rng.random() * 6.28)
    return out / 6 * 1.6


def skin_vertex_colors(verts, normals, tags, tag_names, joints, weights, skel, app: AppearanceParams,
                       body) -> np.ndarray:
    base = app.skin_linear()
    col = np.tile(base, (len(verts), 1))
    names = list(tag_names)

    def T(*keys):
        ids = [names.index(k) for k in keys if k in names]
        return np.isin(tags, ids)

    u = skel.marks["height"] / 1.75
    # mottling
    col *= (1.0 + 0.035 * _value_noise3(verts, 9.0))[:, None]
    red = np.array([1.0, 0.72, 0.70])
    flush = app.flush
    # cheeks, nose, ears: soft flush via distance to anchor points
    O = np.array([0.0, skel.marks["y_chin"], skel.marks["head_z"]])
    k = skel.marks["head_h"] / 0.23
    for anchor, rad, amt in ((O + np.array([0.04, 0.072, 0.075]) * k, 0.025, 0.35),
                             (O + np.array([-0.04, 0.072, 0.075]) * k, 0.025, 0.35),
                             (O + np.array([0.0, 0.08, 0.115]) * k, 0.018, 0.30)):
        w = np.clip(1 - np.linalg.norm(verts - anchor, axis=1) / (rad * k), 0, 1) ** 2 * amt * flush
        col *= (1 + (red - 1) * w[:, None])
    ear = T("ear", "concha")
    col[ear] *= (1 + (red - 1) * 0.25 * flush)
    lips = T("lip_upper", "lip_lower")
    lipc = base * np.array([0.78, 0.42, 0.42]) * (0.8 + 0.4 * app.lip_tint)
    col[lips] = col[lips] * 0.35 + lipc * 0.65
    O_ = np.array([0.0, skel.marks["y_chin"], skel.marks["head_z"]])
    mouth = T("oral_cavity", "mouth_slit") & (np.abs(verts[:, 0] - O_[0]) < 0.021 * skel.marks["head_h"] / 0.23)
    col[mouth] = np.array([0.22, 0.04, 0.04])
    col[T("nostril")] = base * 0.25
    # the strip of socket visible between eyeball and lids is shadowed, faintly warm tissue (it read as a red ring at
    # 0.7/0.35/0.35); the lid margin keeps a slight moist warmth
    col[T("eye_socket")] = base * np.array([0.42, 0.33, 0.31])
    col[T("eye_aperture")] = col[T("eye_aperture")] * np.array([0.97, 0.9, 0.88])
    # areola / nipple (developer detail; public bodies are rebuilt with nipple_size 0 but keep pigment off)
    for lab in ("l", "r"):
        c = skel.marks.get(f"nipple_{lab}")
        if c is None or body.areola_size <= 0.01 or body.nipple_size <= 0.01:
            continue
        r = 0.016 * u * body.areola_size * (1 + 0.25 * min(body.breast_size, 2.0))
        w = np.clip(1.15 - np.linalg.norm(verts - c, axis=1) / r, 0, 1) ** 1.5
        w = np.minimum(w, 1.0)
        areola = base * np.array([0.72, 0.52, 0.48])
        col = col * (1 - w[:, None] * 0.8) + areola * (w[:, None] * 0.8)
    # palms and soles lighter
    hand_ids = [i for i, n in enumerate(skel.names) if n.startswith(("hand_", "thumb", "index", "middle", "ring", "pinky"))]
    on_hand = np.isin(joints[:, 0], hand_ids)
    from forge_character_forge.skeleton import hand_frame
    for side, sign in (("l", 1.0), ("r", -1.0)):
        n = hand_frame(sign)["n"]
        sel = on_hand & (np.sign(verts[:, 0]) == sign)
        palm = np.clip(normals[sel] @ n, 0, 1)
        col[sel] = col[sel] * (1 - 0.3 * palm[:, None]) + (base * 1.25 * np.array([1.0, 0.92, 0.88])) * (0.3 * palm[:, None])
    sole = np.clip(-normals[:, 1], 0, 1) * (verts[:, 1] < 0.03 * u)
    col = col * (1 - 0.3 * sole[:, None]) + base * 1.2 * (0.3 * sole[:, None])
    return np.clip(col, 0, 1)


# ---------------------------------------------------------------- textures

def _periodic_noise(n: int, falloff: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    f = np.fft.fftfreq(n)
    fx, fy = np.meshgrid(f, f)
    r = np.sqrt(fx * fx + fy * fy) + 1e-6
    spec = (rng.normal(size=(n, n)) + 1j * rng.normal(size=(n, n))) / r ** falloff
    spec[0, 0] = 0
    img = np.real(np.fft.ifft2(spec))
    img -= img.mean()
    return img / (np.abs(img).max() + 1e-12)


def _pores(n: int, count: int, radius: float, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    h = np.zeros((n, n))
    pts = rng.random((count, 2)) * n
    yy, xx = np.mgrid[0:n, 0:n]
    r = int(radius * 3) + 1
    for px, py in pts:
        x0, y0 = int(px), int(py)
        for dy in range(-r, r + 1):
            for dx in range(-r, r + 1):
                d2 = (x0 + dx - px) ** 2 + (y0 + dy - py) ** 2
                h[(y0 + dy) % n, (x0 + dx) % n] -= math.exp(-d2 / (radius * radius))
    return h / (np.abs(h).max() + 1e-12)


def height_to_normal(h: np.ndarray, strength: float) -> np.ndarray:
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * 0.5 * strength
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * 0.5 * strength
    n = np.stack([-dx, dy, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return ((n * 0.5 + 0.5) * 255 + 0.5).astype(np.uint8)


def png_bytes(arr: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG", optimize=False, compress_level=6)
    return buf.getvalue()


def skin_textures(size: int = 256) -> dict[str, bytes]:
    fine = _periodic_noise(size, 1.4, 11)
    pores = _pores(size, size * 3, 0.9, 12)
    wrinkle = _periodic_noise(size, 2.2, 13)
    h = 0.45 * fine + 0.6 * pores + 0.3 * wrinkle
    normal = height_to_normal(h, 3.0)
    rough = np.clip(0.5 + 0.12 * fine - 0.08 * pores, 0, 1)
    mr = np.zeros((size, size, 3), np.uint8)
    mr[..., 1] = (rough * 255).astype(np.uint8)  # G = roughness, B = metallic (0)
    return {"skin_normal": png_bytes(normal), "skin_mr": png_bytes(mr)}


def iris_texture(color: np.ndarray, size: int = 256, seed: int = 21) -> bytes:
    yy, xx = np.mgrid[0:size, 0:size]
    c = (size - 1) / 2
    r = np.sqrt((xx - c) ** 2 + (yy - c) ** 2) / c
    ang = np.arctan2(yy - c, xx - c)
    rng = np.random.default_rng(seed)
    fib = np.zeros_like(r)
    for k in range(40):
        fib += np.sin(ang * rng.integers(20, 90) + rng.random() * 6.28) * rng.random()
    fib = fib / 40
    sclera = srgb_to_linear([0.92, 0.89, 0.86])
    vein = np.clip(_periodic_noise(size, 1.2, seed + 1) * 3 - 2.2, 0, 1)
    out = np.tile(sclera, (size, size, 1)) * (1 - 0.25 * vein[..., None] * np.array([0.0, 1.0, 1.0]))
    iris_r, pupil_r = 0.46, 0.17
    iris = (r < iris_r)
    tone = color * (0.75 + 0.6 * fib[..., None]) * (1.15 - 0.6 * r[..., None] / iris_r)
    tone = tone * (1 + 0.6 * np.exp(-((r[..., None] - 0.25) / 0.05) ** 2))
    out[iris] = tone[iris]
    limbal = np.exp(-((r - iris_r) / 0.025) ** 2)
    out *= (1 - 0.7 * limbal)[..., None]
    out[r < pupil_r] = 0.004
    return png_bytes((linear_to_srgb(out) * 255 + 0.5).astype(np.uint8))


def strand_texture(size: int = 256, seed: int = 31, alpha_cards: bool = False) -> bytes:
    """Hair strands along +V. RGB = brightness modulation (multiplied by baseColorFactor); A = coverage."""
    rng = np.random.default_rng(seed)
    x = np.arange(size)
    cols = np.zeros(size)
    for _ in range(60):
        cols += np.sin(x / size * 2 * np.pi * rng.integers(4, 120) + rng.random() * 6.28) * rng.random()
    cols = (cols - cols.min()) / (np.ptp(cols) + 1e-9)
    img = np.tile(cols[None, :], (size, 1))
    img = img * (0.85 + 0.15 * _periodic_noise(size, 1.5, seed + 1))
    rgb = np.clip(0.55 + 0.45 * img, 0, 1)
    out = np.zeros((size, size, 4), np.uint8)
    out[..., :3] = (rgb[..., None] * 255).astype(np.uint8)
    if alpha_cards:
        v = np.linspace(0, 1, size)[:, None]
        a = (img > 0.45) * np.clip(1.6 - 1.6 * v, 0, 1) + (img > 0.7) * 0.4
        out[..., 3] = (np.clip(a, 0, 1) * 255).astype(np.uint8)
    else:
        out[..., 3] = 255
    return png_bytes(out)


def fabric_textures(size: int = 256, seed: int = 41) -> dict[str, bytes]:
    yy, xx = np.mgrid[0:size, 0:size]
    weave = np.sin(xx / size * 2 * np.pi * 64) * np.sin(yy / size * 2 * np.pi * 64)
    h = 0.6 * weave + 0.4 * _periodic_noise(size, 1.6, seed)
    return {"fabric_normal": png_bytes(height_to_normal(h, 2.0))}
