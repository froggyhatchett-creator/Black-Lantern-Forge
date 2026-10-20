// Stolen Fire E2: the studio's foot locks (studio/footlock.js) against the Python reference
// (forge_character_forge/v3/footlock.py) on the shared fixtures, in Node (no browser).
// usage: node tools/footlock_parity.mjs   -> prints the largest difference; exit 1 above the tolerance
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { lockClip } from "../studio/footlock.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const dir = path.join(here, "..", "tests", "fixtures", "footlock");
const TOL = 1e-6;  // the studio writes float32 channels; the Python reference keeps float64 (float32 rounding is ~3e-8)
let worst = 0, ok = true;
for (const file of fs.readdirSync(dir).filter((f) => f.endsWith(".json")).sort()) {
  const c = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"));
  for (const [name, clip] of Object.entries(c.clips)) {
    const rot = Object.fromEntries(Object.entries(clip.rot).map(([k, v]) => [k, Float32Array.from(v)]));
    const root = new Float64Array(clip.frames * 3); for (let i = 0; i < root.length; i++) root[i] = clip.root[i] * c.u;
    const { rot: out, report } = lockClip(c.names, c.parents, Float32Array.from(c.rest), rot, root, clip.fps, clip.frames);
    let d = 0;
    for (const [j, exp] of Object.entries(clip.expected)) for (let i = 0; i < exp.length; i++) d = Math.max(d, Math.abs(out[j][i] - exp[i]));
    const spans = Object.fromEntries(Object.entries(report.feet).map(([f, x]) => [f, x.locked]));
    const sameSpans = JSON.stringify(spans) === JSON.stringify(clip.expected_locked);
    const dv = Math.abs(report.ground_speed_m_s - clip.expected_ground_speed_m_s);
    const pass = d <= TOL && sameSpans && dv <= 1e-9;
    ok = ok && pass; worst = Math.max(worst, d);
    console.log(`${pass ? "PASS" : "FAIL"} ${c.character} ${name}: max |js - python| ${d.toExponential(2)}, spans ${sameSpans ? "equal" : JSON.stringify(spans)}, ground speed diff ${dv.toExponential(1)}`);
  }
}
console.log(`worst ${worst.toExponential(2)} (tolerance ${TOL})`);
process.exit(ok ? 0 : 1);
