// Load a Character DNA file into the real studio and capture front / three-quarter / side views (body and face).
// Usage: node tools/studio_dna_shots.mjs <url> <dna.json> <outdir>
// Rest pose, no animation, secondary motion off, overlays hidden; writes load_report.json with what the studio applied.
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";
import fs from "node:fs";
import path from "node:path";

const [url, dnaPath, out] = process.argv.slice(2);
fs.mkdirSync(out, { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
await page.goto(url);
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 180000 });
const dna = JSON.parse(fs.readFileSync(dnaPath, "utf8"));
const report = await page.evaluate((dna) => {
  const st = window.studio;
  st.fromDNA(dna);
  st.state.clip = "none"; st.state.pose = "A-pose (rest)"; st.playing = false; st.clipT = 0; st.phys.on = false;
  st.dirtyGeo = true; document.querySelector("#turntable").checked = false;
  for (const el of document.querySelectorAll(".stage > :not(canvas)")) el.style.visibility = "hidden";
  const s = st.state, t = dna.traits;
  let maxd = 0; for (const k of Object.keys(st.man.params)) if (t[k]) maxd = Math.max(maxd, Math.abs(s.params[k] - t[k].value));
  return { status: document.querySelector("#status").textContent, max_param_diff_vs_dna: maxd, hair_style: s.hair_style,
    hair_color: s.hair_color, outfit: s.outfit, colors: s.colors, skin_tone: s.skin_tone, eye: s.eye };
}, dna);
const frames = async (n = 3) => { const f = await page.evaluate(() => window.studio.frames);
  await page.waitForFunction((f) => window.studio.frames >= f, f + n, { timeout: 120000 }); };
for (const [where, tag] of [["body", "body"], ["face", "face"]]) {
  for (const [yaw, v] of [[0, "front"], [0.65, "3q"], [Math.PI / 2, "side"]]) {
    await page.evaluate(([w, y]) => { const st = window.studio; st.focus(w); st.cam.yaw = y; st.cam.pitch = 0.04; }, [where, yaw]);
    await frames(); await page.locator("canvas").screenshot({ path: path.join(out, `studio_${tag}_${v}.png`) });
  }
}
report.height_m = await page.evaluate(() => window.studio.heightNow);
report.errors = errors;
fs.writeFileSync(path.join(out, "load_report.json"), JSON.stringify(report, null, 1));
await browser.close();
console.log(JSON.stringify(report));
