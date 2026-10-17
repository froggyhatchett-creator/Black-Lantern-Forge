"""Board segmentation probe (no Blender): region growing from a seed face, stopped at concave creases sharper than
theta degrees, inside a generous board box; reports where the growth leaks out of the board footprint.

    python3 board_grow.py <theta> <out prefix> <slab json from board_select.py> '[x, y, z seed]'
"""
import sys, json, numpy as np, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rodin_reference")); sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from glb_mesh import load
from forge_character_forge.render import Camera, DrawItem, rasterize, save, sheet, label
P, N, UV, F = load()
theta = float(sys.argv[1]); out = sys.argv[2]
key, inv = np.unique(np.round(P, 7), axis=0, return_inverse=True); inv = inv.ravel(); Fw = inv[F]; V = key
nf = np.cross(V[Fw[:, 1]] - V[Fw[:, 0]], V[Fw[:, 2]] - V[Fw[:, 0]]); nf /= np.linalg.norm(nf, axis=1, keepdims=True)
cen = V[Fw].mean(1)
E = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]]); fid = np.tile(np.arange(len(Fw)), 3)
Es = np.sort(E, 1); o = np.lexsort((Es[:, 1], Es[:, 0])); Es, fo = Es[o], fid[o]
same = (Es[1:] == Es[:-1]).all(1); i = np.nonzero(same)[0]
f1, f2 = fo[i], fo[i + 1]                       # each manifold edge -> its two faces
mid = V[Es[i]].mean(1)
cosang = np.clip((nf[f1] * nf[f2]).sum(1), -1, 1); ang = np.degrees(np.arccos(cosang))
concave = ((cen[f2] - mid) * nf[f1]).sum(1) > 0  # neighbour bends toward the normal side: a crease
blocked = concave & (ang > theta)
# bounding volume: generous board box (from the slab frame) so growth cannot run over the whole character
fr = json.load(open(sys.argv[3]))["frame"]; B, a, w, n = (np.array(fr[k]) for k in "Bawn")
lc = np.c_[(cen - B) @ a, (cen - B) @ w, (cen - B) @ n]
inbox = (lc[:, 0] > -0.12) & (lc[:, 0] < 1.12) & (np.abs(lc[:, 1]) < 0.24) & (lc[:, 2] > -0.36) & (lc[:, 2] < 0.16)
ok = ~blocked & inbox[f1] & inbox[f2]
nbr = {}
A1, A2 = f1[ok], f2[ok]
order = np.argsort(A1); 
import collections
adj = collections.defaultdict(list)
for x, y in zip(A1, A2): adj[x].append(y); adj[y].append(x)
seed_pt = np.array(json.loads(sys.argv[4]))
seed = int(np.argmin(np.linalg.norm(cen - seed_pt, axis=1)))
cuts = json.loads(sys.argv[5]) if len(sys.argv) > 5 else []
cutmask = np.zeros(len(Fw), bool)
for c in cuts:  # operator cut: faces inside the sphere are removed (the hole is capped later)
    cutmask |= np.linalg.norm(cen - np.array(c[:3]), axis=1) < c[3]
foot = (lc[:, 0] > -0.06) & (lc[:, 0] < 1.06) & (np.abs(lc[:, 1]) < 0.17)
t = time.time(); reg = np.zeros(len(Fw), bool); reg[seed] = True; dq = collections.deque([seed]); entries = []
while dq:
    q = dq.popleft()
    for r in adj[q]:
        if not reg[r] and not cutmask[r]:
            reg[r] = True; dq.append(r)
            if foot[q] and not foot[r]: entries.append(cen[r])
ent = np.array(entries) if entries else np.zeros((0, 3))
cl = []
for p_ in ent:
    for c in cl:
        if np.linalg.norm(c[0] / c[1] - p_) < 0.05: c[0] += p_; c[1] += 1; break
    else: cl.append([p_.copy(), 1])
print("leak entry clusters (centre, count):", [(np.round(c[0] / c[1], 3).tolist(), c[1]) for c in sorted(cl, key=lambda c: -c[1])][:10])
print("theta", theta, "seed", seed, cen[seed].round(3), "region faces", int(reg.sum()), "time", round(time.time() - t, 1), "s")
np.save(out + "_faces.npy", np.nonzero(reg)[0])
tiles = []
for yaw in (0, 90, 180, 270):
    cam = Camera(yaw_deg=yaw, pitch_deg=0, target=(0.2, 1.05, 0.0), distance=6, ortho_height=1.3)
    tiles.append(label(rasterize([DrawItem(P, F[~reg], color=(0.6, 0.6, 0.62)), DrawItem(P, F[reg], color=(0.95, 0.45, 0.25))], cam, W=520, H=640, background=(0.13, 0.13, 0.15), ground_y=None), f"crease-bounded growth, {theta} deg, yaw {yaw}", size=13))
save(sheet(tiles, 4), out + ".png")
