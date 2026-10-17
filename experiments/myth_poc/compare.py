"""Compare the Myth renders (myth_out/) against our independent GLB player (reference/). Standard library only.

    python compare.py [--myth myth_out] [--ref reference]

Criteria (fixed before any Myth result existed; see README.md):
  validation   no errors: 10 mesh nodes, 2 morph targets on body/brows/lashes/hair, the 7 clips, weights read back
  silhouette   IoU of the measured-mesh silhouettes >= 0.95 on rest frames, >= 0.92 on the walk frame (skinning, pose)
  blink        visible eyeball pixels: blink 0 within 25 % of the reference; blink 0.5 / blink 0 within 0.15 of the
               reference's ratio; blink 1 / blink 0 <= 0.02 (the sparse blink morphs closed the eyes)
  clothing     garment pixels on full-body frames within 15 % of the reference (and > 0: the clothes are there)
Writes compare_report.json and <frame>_side_by_side.png (Myth left, reference right) into the Myth folder.
"""
import argparse
import json
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent


def read_png(path):
    """Reader for the 8-bit, non-interlaced PNGs our own writers produce (any filter type)."""
    b = Path(path).read_bytes()
    assert b[:8] == b"\x89PNG\r\n\x1a\n", path
    pos, idat, w = 8, b"", None
    while pos < len(b):
        n = struct.unpack(">I", b[pos:pos + 4])[0]
        t, d = b[pos + 4:pos + 8], b[pos + 8:pos + 8 + n]
        if t == b"IHDR":
            w, h, depth, ctype = struct.unpack(">IIBB", d[:10])
            assert depth == 8 and d[12] == 0, "8-bit non-interlaced only"
            ch = {0: 1, 2: 3, 6: 4}[ctype]
        elif t == b"IDAT":
            idat += d
        pos += 12 + n
    raw, stride, out, prev = zlib.decompress(idat), w * ch, bytearray(), bytearray(w * ch)
    for y in range(h):
        f, row = raw[y * (stride + 1)], bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = row[i - ch] if i >= ch else 0
            c = prev[i - ch] if i >= ch else 0
            if f == 1:
                row[i] = (row[i] + a) & 255
            elif f == 2:
                row[i] = (row[i] + prev[i]) & 255
            elif f == 3:
                row[i] = (row[i] + (a + prev[i]) // 2) & 255
            elif f == 4:
                p = a + prev[i] - c
                pa, pb, pc = abs(p - a), abs(p - prev[i]), abs(p - c)
                row[i] = (row[i] + (a if pa <= pb and pa <= pc else prev[i] if pb <= pc else c)) & 255
        out += row
        prev = row
    return bytes(out), w, h, ch


def write_png(path, data, w, h, ch):
    raw = b"".join(b"\x00" + data[y * w * ch:(y + 1) * w * ch] for y in range(h))
    chunk = lambda t, d: struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, {1: 0, 3: 2, 4: 6}[ch], 0, 0, 0))
                           + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def iou(a, b):
    inter = sum(1 for x, y in zip(a, b) if x and y)
    union = sum(1 for x, y in zip(a, b) if x or y)
    return inter / union if union else 1.0


def rgb(data, ch):
    return data if ch == 3 else bytes(v for i, v in enumerate(data) if i % 4 != 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--myth", default=str(HERE / "myth_out"))
    ap.add_argument("--ref", default=str(HERE / "reference"))
    a = ap.parse_args()
    md, rd = Path(a.myth), Path(a.ref)
    M = json.loads((md / "myth_metrics.json").read_text())
    R = json.loads((rd / "metrics.json").read_text())
    rep = {"checks": [], "frames": {}}

    def check(name, ok, detail):
        rep["checks"].append({"name": name, "pass": bool(ok), "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    if "headless_error" in M:
        check("headless rendering", False, M["headless_error"])
        (md / "compare_report.json").write_text(json.dumps(rep, indent=1))
        return 2
    v = M["validation"]
    check("validation", not v["errors"], v["errors"] or f"meshes {len(v['mesh_nodes_found'])}, clips {len(v['animations'])}, morphs {v['morph_target_counts']}")
    for name, rm in R.items():
        mm = M["frames"].get(name)
        if mm is None:
            check(f"{name} rendered", False, "missing")
            continue
        m1, w, h, _ = read_png(md / f"{name}_mask.png")
        m2, w2, h2, _ = read_png(rd / f"{name}_mask.png")
        assert (w, h) == (w2, h2)
        j = iou(m1, m2)
        rep["frames"][name] = {"iou": round(j, 4), "myth": mm, "reference": rm}
        check(f"{name} silhouette IoU", j >= (0.92 if "walk" in name else 0.95), f"{j:.4f}")
        if name.startswith("full_"):
            ratio = mm["garment_px"] / max(rm["garment_px"], 1)
            check(f"{name} clothing", mm["garment_px"] > 0 and abs(ratio - 1) <= 0.15, f"{mm['garment_px']} px vs {rm['garment_px']} ({ratio:.2f})")
        b1, bw, bh, bc = read_png(md / f"{name}_beauty.png")
        b2, _, _, rc = read_png(rd / f"{name}_beauty.png")
        l, r = rgb(b1, bc), rgb(b2, rc)
        side = b"".join(l[y * bw * 3:(y + 1) * bw * 3] + r[y * bw * 3:(y + 1) * bw * 3] for y in range(bh))
        write_png(md / f"{name}_side_by_side.png", side, 2 * bw, bh, 3)
    for view in ("front", "34"):
        e = {b: (M["frames"].get(f"face_{view}_blink{b}", {}).get("eye_px"), R[f"face_{view}_blink{b}"]["eye_px"]) for b in ("0.0", "0.5", "1.0")}
        if any(x[0] is None for x in e.values()):
            continue
        (m0, r0), (mh, rh), (m1_, r1_) = e["0.0"], e["0.5"], e["1.0"]
        check(f"blink open, {view}", abs(m0 / max(r0, 1) - 1) <= 0.25, f"visible eyeball {m0} px vs {r0}")
        check(f"blink half, {view}", abs(mh / max(m0, 1) - rh / max(r0, 1)) <= 0.15, f"{mh / max(m0, 1):.3f} of open vs {rh / max(r0, 1):.3f}")
        check(f"blink closed, {view}", m1_ / max(m0, 1) <= 0.02, f"{m1_ / max(m0, 1):.4f} of open ({m1_} px) vs {r1_ / max(r0, 1):.4f}")
    rep["timings_s"] = M.get("timings_s")
    rep["all_pass"] = all(c["pass"] for c in rep["checks"])
    (md / "compare_report.json").write_text(json.dumps(rep, indent=1))
    print("ALL PASS" if rep["all_pass"] else "SOME CHECKS FAILED", "->", md / "compare_report.json")
    return 0 if rep["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
