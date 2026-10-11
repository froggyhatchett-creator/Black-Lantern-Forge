"""Software rasterizer and shader for previews (preview_version 1).

Pipeline
  1. Project every triangle of every component with the fixed Camera.
  2. Cull back faces: front faces have negative signed area in y-down pixel space.
  3. Rasterize into a z-buffer at (W*ssaa) x (H*ssaa) samples, testing each
     sample center with inclusive edge functions (no gaps; ties keep the
     first-drawn triangle). Store triangle id + barycentrics (deferred shading).
  4. Shade each visible sample once:
       n  = normalize(barycentric blend of corner normals)
       uv = barycentric blend of corner UVs
       c  = material.sample(u, v)                       procedural texture
       diffuse  = c * (1 - metallic)
       specular = 0.04 + (c - 0.04) * metallic
       color = ambient * diffuse
             + sum over 2 lights: I * (diffuse * max(0, n.L) + specular * (n.h)^e * (e + 8) / (8 pi))
             + specular * environment(reflect(v, n), roughness) * 0.9
       e = clamp(int(2 / roughness^4 - 2), 1, 2048), raised by integer squaring
  5. Display value = sqrt(clamp(color, 0, 1))  (gamma-2 approximation; sqrt is exact).
  6. Average the ssaa x ssaa samples per pixel, quantize: int(255 * x + 0.5).

Only + - * / sqrt, comparisons, and integer ops are used. No libm
transcendentals. So on IEEE-754 binary64 platforms the pixel buffer is
determined bit-for-bit by (asset, presentation, settings).
"""

from __future__ import annotations

import math
from array import array

from forge.render.camera import Camera

# Lighting rig. All directions are in CAMERA space (x = screen right, y = screen up,
# z = toward the camera), converted to world space per camera, so every view is lit
# the same way relative to the viewer, like a product photo setup.
AMBIENT = 0.10
LIGHTS = (
    ((-0.55, 0.60, 0.60), 0.95),   # key: upper left, in front
    ((0.80, 0.10, 0.45), 0.30),    # fill: right
)
ENV_SKY = (0.90, 0.92, 0.97)            # reflected environment, top
ENV_GROUND = (0.12, 0.11, 0.10)         # reflected environment, bottom
ENV_STRENGTH = 0.9
SOFTBOX_DIR = (-0.80, 0.25, 0.55)       # large studio softbox seen in reflections (camera left)
SOFTBOX_INTENSITY = 0.8
CAMERA_SOFTBOX_INTENSITY = 0.5          # large softbox behind the camera: weight (reflect . view)^3
BACKGROUND_TOP = (0.37, 0.38, 0.40)     # display space (already gamma encoded)
BACKGROUND_BOTTOM = (0.20, 0.20, 0.21)
_INV_8PI = 1.0 / (8.0 * math.pi)


def _norm(v):
    length = math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])
    return (v[0] / length, v[1] / length, v[2] / length)


def _to_world(cam: Camera, v):
    """Camera-space direction -> unit world-space direction."""
    x, y, z = v
    r, u, d = cam.right, cam.up, cam.direction
    return _norm((x * r[0] + y * u[0] + z * d[0], x * r[1] + y * u[1] + z * d[1], x * r[2] + y * u[2] + z * d[2]))


def _ipow(x: float, e: int) -> float:
    """x ** e for integer e >= 1 via binary exponentiation (deterministic sequence of multiplies)."""
    result = 1.0
    while e:
        if e & 1:
            result *= x
        x *= x
        e >>= 1
    return result


def shininess(roughness: float) -> int:
    """Blinn-Phong exponent: int(2 / roughness^2 - 2), clamped to [1, 1024]."""
    return max(1, min(1024, int(2.0 / (roughness * roughness) - 2.0)))


class _Shader:
    def __init__(self, material, cam: Camera):
        self.material = material
        self.metallic = material.metallic
        self.rough = material.roughness
        self.exponent = shininess(material.roughness)
        self.spec_norm = (self.exponent + 8.0) * _INV_8PI
        self.v = cam.direction
        self.right, self.up = cam.right, cam.up
        self.lights = []
        for direction, intensity in LIGHTS:
            L = _to_world(cam, direction)
            v = cam.direction
            h = _norm((L[0] + v[0], L[1] + v[1], L[2] + v[2]))
            self.lights.append((L, h, intensity))
        self.softbox = _to_world(cam, SOFTBOX_DIR)
        self.softbox_exp = max(2, int(1.0 / (material.roughness * material.roughness)))
        self.env_mid = tuple((ENV_SKY[i] + ENV_GROUND[i]) * 0.3 for i in range(3))

    def shade(self, n, u, v):
        nx, ny, nz = n
        cr, cg, cb = self.material.sample(u, v)
        m = self.metallic
        kd = 1.0 - m
        dr, dg, db = cr * kd, cg * kd, cb * kd
        sr, sg, sb = 0.04 + (cr - 0.04) * m, 0.04 + (cg - 0.04) * m, 0.04 + (cb - 0.04) * m
        r, g, b = AMBIENT * dr, AMBIENT * dg, AMBIENT * db
        e, norm = self.exponent, self.spec_norm
        for L, h, intensity in self.lights:
            ndl = nx * L[0] + ny * L[1] + nz * L[2]
            if ndl > 0.0:
                ndh = nx * h[0] + ny * h[1] + nz * h[2]
                spec = _ipow(ndh, e) * norm if ndh > 0.0 else 0.0
                r += intensity * (dr * ndl + sr * spec)
                g += intensity * (dg * ndl + sg * spec)
                b += intensity * (db * ndl + sb * spec)
        # Reflected environment, evaluated in camera space.
        vx, vy, vz = self.v
        ndv = nx * vx + ny * vy + nz * vz
        rx, ry, rz = 2.0 * ndv * nx - vx, 2.0 * ndv * ny - vy, 2.0 * ndv * nz - vz
        r_up = rx * self.up[0] + ry * self.up[1] + rz * self.up[2]
        r_right = rx * self.right[0] + ry * self.right[1] + rz * self.right[2]
        t = 0.5 + 0.5 * r_up
        t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
        hf = 0.6 - 0.5 * r_right                      # studio falloff: brighter toward camera-left
        hf = 0.15 if hf < 0.15 else (1.0 if hf > 1.0 else hf)
        sbd = rx * self.softbox[0] + ry * self.softbox[1] + rz * self.softbox[2]
        box = SOFTBOX_INTENSITY * _ipow(sbd, self.softbox_exp) if sbd > 0.0 else 0.0
        rdv = rx * vx + ry * vy + rz * vz
        if rdv > 0.0:
            box += CAMERA_SOFTBOX_INTENSITY * rdv * rdv * rdv
        rough = self.rough
        out = []
        for c, s, i in ((r, sr, 0), (g, sg, 1), (b, sb, 2)):
            env = (ENV_GROUND[i] + (ENV_SKY[i] - ENV_GROUND[i]) * t) * hf
            env = env + (self.env_mid[i] - env) * rough + box
            c += s * env * ENV_STRENGTH
            c = 0.0 if c < 0.0 else (1.0 if c > 1.0 else c)
            out.append(math.sqrt(c))
        return out


def render_pixels(presented, camera: Camera, ssaa: int) -> bytes:
    """Return RGB8 pixels (top-down rows) for camera.width_px x camera.height_px."""
    W, H = camera.width_px, camera.height_px
    SW, SH = W * ssaa, H * ssaa
    sample_cam = Camera(camera.view, camera.direction, camera.right, camera.up, camera.target,
                        camera.half_width, camera.half_height, SW, SH)

    # ---- triangle setup (fixed order: component order, then face order)
    tri_corner_normals = []
    tri_corner_uvs = []
    tri_shader = []
    shaders = []
    screen = []
    for comp_index, (mesh, pres) in enumerate(zip(presented.asset.components, presented.components)):
        shader = _Shader(pres.material, camera)
        shaders.append(shader)
        proj = [sample_cam.project(p) for p in mesh.positions]
        for f, (a, b, c) in enumerate(mesh.triangles):
            na, nb, nc = pres.normal_indices[f]
            ua, ub, uc = pres.uv_indices[f]
            screen.append((proj[a], proj[b], proj[c]))
            tri_corner_normals.append((pres.normals[na], pres.normals[nb], pres.normals[nc]))
            tri_corner_uvs.append((pres.uvs[ua], pres.uvs[ub], pres.uvs[uc]))
            tri_shader.append(comp_index)

    n_samples = SW * SH
    depth = array("d", [-math.inf]) * n_samples
    owner = array("i", [-1]) * n_samples
    bary1 = array("d", [0.0]) * n_samples
    bary2 = array("d", [0.0]) * n_samples

    # ---- rasterize
    for t, ((x0, y0, z0), (x1, y1, z1), (x2, y2, z2)) in enumerate(screen):
        area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
        if not area < 0.0:
            continue  # back-facing or degenerate in screen space
        inv = 1.0 / area
        bx0 = max(0, int(math.floor(min(x0, x1, x2))))
        bx1 = min(SW - 1, int(math.ceil(max(x0, x1, x2))))
        by0 = max(0, int(math.floor(min(y0, y1, y2))))
        by1 = min(SH - 1, int(math.ceil(max(y0, y1, y2))))
        if bx0 > bx1 or by0 > by1:
            continue
        dx21, dy21 = x2 - x1, y2 - y1
        dx02, dy02 = x0 - x2, y0 - y2
        dx10, dy10 = x1 - x0, y1 - y0
        edges = ((-dy21, dx21, x1, y1), (-dy02, dx02, x2, y2), (-dy10, dx10, x0, y0))
        for py in range(by0, by1 + 1):
            cy = py + 0.5
            # Approximate span from the three edge half-planes (optimization only;
            # the exact per-sample test below decides coverage).
            lo, hi = float(bx0), float(bx1) + 1.0
            for a_coef, dxe, xe, ye in edges:
                bconst = dxe * (cy - ye) - a_coef * xe  # E(cx) = a_coef * cx + bconst
                if a_coef > 0.0:
                    hi = min(hi, -bconst / a_coef)
                elif a_coef < 0.0:
                    lo = max(lo, -bconst / a_coef)
            sx0 = max(bx0, int(math.floor(lo - 0.5)) - 1)
            sx1 = min(bx1, int(math.ceil(hi - 0.5)) + 1)
            row = py * SW
            for px in range(sx0, sx1 + 1):
                cx = px + 0.5
                e0 = dx21 * (cy - y1) - dy21 * (cx - x1)
                if e0 > 0.0:
                    continue
                e1 = dx02 * (cy - y2) - dy02 * (cx - x2)
                if e1 > 0.0:
                    continue
                e2 = dx10 * (cy - y0) - dy10 * (cx - x0)
                if e2 > 0.0:
                    continue
                l0, l1, l2 = e0 * inv, e1 * inv, e2 * inv
                z = l0 * z0 + l1 * z1 + l2 * z2
                idx = row + px
                if z > depth[idx]:
                    depth[idx] = z
                    owner[idx] = t
                    bary1[idx] = l1
                    bary2[idx] = l2

    # ---- shade + resolve
    out = bytearray(W * H * 3)
    inv_samples = 1.0 / (ssaa * ssaa)
    top, bottom = BACKGROUND_TOP, BACKGROUND_BOTTOM
    for y in range(H):
        for x in range(W):
            ar = ag = ab = 0.0
            for sy in range(ssaa):
                syy = y * ssaa + sy
                bg_t = (syy + 0.5) / SH
                for sx in range(ssaa):
                    idx = syy * SW + x * ssaa + sx
                    t = owner[idx]
                    if t < 0:
                        ar += top[0] + (bottom[0] - top[0]) * bg_t
                        ag += top[1] + (bottom[1] - top[1]) * bg_t
                        ab += top[2] + (bottom[2] - top[2]) * bg_t
                        continue
                    l1, l2 = bary1[idx], bary2[idx]
                    l0 = 1.0 - l1 - l2
                    (n0, n1, n2) = tri_corner_normals[t]
                    nx = l0 * n0[0] + l1 * n1[0] + l2 * n2[0]
                    ny = l0 * n0[1] + l1 * n1[1] + l2 * n2[1]
                    nz = l0 * n0[2] + l1 * n1[2] + l2 * n2[2]
                    length = math.sqrt(nx * nx + ny * ny + nz * nz)
                    if length > 0.0:
                        nx, ny, nz = nx / length, ny / length, nz / length
                    (u0, u1, u2) = tri_corner_uvs[t]
                    u = l0 * u0[0] + l1 * u1[0] + l2 * u2[0]
                    v = l0 * u0[1] + l1 * u1[1] + l2 * u2[1]
                    cr, cg, cb = shaders[tri_shader[t]].shade((nx, ny, nz), u, v)
                    ar += cr
                    ag += cg
                    ab += cb
            o = (y * W + x) * 3
            out[o] = int(ar * inv_samples * 255.0 + 0.5)
            out[o + 1] = int(ag * inv_samples * 255.0 + 0.5)
            out[o + 2] = int(ab * inv_samples * 255.0 + 0.5)
    return bytes(out)
