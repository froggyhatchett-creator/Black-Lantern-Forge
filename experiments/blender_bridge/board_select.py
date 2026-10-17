"""Board selection probe (no Blender): faces inside one board-aligned slab, largest welded part, cut loops.

    python3 board_select.py '<spec json>' <out prefix>
"""
import sys, json, numpy as np
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rodin_reference")); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from glb_mesh import load
from forge_character_forge.render import Camera, DrawItem, rasterize, save, sheet, label
P, N, UV, F = load()
spec = json.loads(sys.argv[1]); out = sys.argv[2]
T2, B2 = np.array(spec["top_xy"]), np.array(spec["bottom_xy"])
def zat(xy):
    s = P[np.linalg.norm(P[:, :2] - xy, axis=1) < 0.03]; return np.median(s[:, 2])
T, B = np.r_[T2, zat(T2)], np.r_[B2, zat(B2)]
a = (T - B) / np.linalg.norm(T - B); L = np.linalg.norm(T - B)
# plane normal: smallest PCA axis of points near the axis
rel = P - B; t = rel @ a; rad = np.linalg.norm(rel - np.outer(t, a), axis=1)
near = P[(t > 0.1 * L) & (t < 0.9 * L) & (rad < spec["half_width"])]
c = near.mean(0); _, _, Vt = np.linalg.svd(near - c, full_matrices=False)
n = Vt[2] - (Vt[2] @ a) * a; n /= np.linalg.norm(n); w = np.cross(a, n)
off = spec.get("depth_offset", 0.0)
loc = np.c_[(P - B) @ a, (P - B) @ w, (P - B) @ n - ((c - B) @ n) - off]
inside = (loc[:, 0] > -spec["margin"]) & (loc[:, 0] < L + spec["margin"]) & (np.abs(loc[:, 1]) < spec["half_width"]) & (np.abs(loc[:, 2]) < spec["half_depth"])
for ex in spec.get("exclude_spheres", []):
    inside &= np.linalg.norm(P - np.array(ex[:3]), axis=1) > ex[3]
sel = inside[F].all(1)
# connectivity inside the selection: keep the largest face-connected part
key, inv = np.unique(np.round(P, 7), axis=0, return_inverse=True); inv = inv.ravel(); Fw = inv[F]
Fs = Fw[sel]; sid = np.nonzero(sel)[0]
E = np.sort(np.concatenate([Fs[:, [0, 1]], Fs[:, [1, 2]], Fs[:, [2, 0]]]), 1)
lab = np.arange(len(key))
u = np.unique(E, axis=0)
while True:
    m = np.minimum(lab[u[:, 0]], lab[u[:, 1]]); new = lab.copy(); np.minimum.at(new, u[:, 0], m); np.minimum.at(new, u[:, 1], m); new = new[new]
    if (new == lab).all(): break
    lab = new
fl = lab[Fs[:, 0]]; vals, cnt = np.unique(fl, return_counts=True)
keep = fl == vals[np.argmax(cnt)]
sel2 = np.zeros(len(F), bool); sel2[sid[keep]] = True
# cut boundary of the kept region: edges used once inside it -> loops
Fk = Fw[sel2]
Ek = np.sort(np.concatenate([Fk[:, [0, 1]], Fk[:, [1, 2]], Fk[:, [2, 0]]]), 1)
ue, ce = np.unique(Ek, axis=0, return_counts=True); bd = ue[ce == 1]
# group boundary edges into loops (components)
bl = {}; 
for x, y in bd: bl.setdefault(x, []).append(y); bl.setdefault(y, []).append(x)
seen, loops = set(), []
for s0 in bl:
    if s0 in seen: continue
    st, comp = [s0], []
    while st:
        q = st.pop()
        if q in seen: continue
        seen.add(q); comp.append(q); st += bl[q]
    pts = key[comp]; loops.append({"vertices": len(comp), "centre": pts.mean(0).round(3).tolist(), "extent_mm": ((pts.max(0) - pts.min(0)) * 1000).round(0).tolist()})
loops.sort(key=lambda d: -d["vertices"])
res = {"axis_len_m": round(float(L), 3), "selected_faces_box": int(sel.sum()), "parts_in_box": int(len(vals)), "kept_faces": int(sel2.sum()),
       "cut_loops": len(loops), "loops": loops[:12], "frame": {"B": B.round(4).tolist(), "a": a.round(4).tolist(), "w": w.round(4).tolist(), "n": n.round(4).tolist()}}
json.dump(res, open(out + ".json", "w"), indent=1); print(json.dumps({k: v for k, v in res.items() if k != "loops"})); [print(l) for l in loops[:12]]
np.save(out + "_faces.npy", np.nonzero(sel2)[0])
tiles = []
for yaw in (0, 90, 180, 270):
    cam = Camera(yaw_deg=yaw, pitch_deg=0, target=(0.2, 1.05, 0.0), distance=6, ortho_height=1.3)
    img = rasterize([DrawItem(P, F[~sel2], color=(0.6, 0.6, 0.62)), DrawItem(P, F[sel2], color=(0.95, 0.45, 0.25))], cam, W=520, H=640, background=(0.13, 0.13, 0.15), ground_y=None)
    tiles.append(label(img, f"selection (orange) yaw {yaw}", size=13))
save(sheet(tiles, 4), out + ".png")
