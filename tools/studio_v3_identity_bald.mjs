// Phase 3D/3E: the four identities in the real studio with hair style "bald" (styling only; the hair hides the face in
// profile), identical cameras: three-quarter and profile.  usage: node tools/studio_v3_identity_bald.mjs <base-url> <outdir>
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const [base, out] = process.argv.slice(2);
fs.mkdirSync(path.join(out, "shots"), { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(base + "?gen=3");
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 600000 });
const settle = (n = 3) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const t = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(t)); t(); }), n);
for (const p of ["neutral", "ID-A", "ID-B", "MERCY-INSPIRED"]) {
  await page.evaluate(() => { const s = window.studio; s.applyPreset("female", false); s.state.clip = "none"; s.playing = false; s.clipT = 0; s.spin.yaw = 0;
    s.state.expr = {}; document.getElementById("turntable").checked = false; });
  await page.click("#t-identity"); await page.click(`[data-identity="${p}"]`);
  await page.click("#t-look"); await page.selectOption("#hairstyle", "bald");
  for (const y of [0, 35, 90]) {
    await page.evaluate((y) => { const s = window.studio; s.evaluate(); const a = s.parts.eye_l.g.eyeC, b = s.parts.eye_r.g.eyeC;
      s.cam.target = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - 0.035, (a[2] + b[2]) / 2]; s.cam.dist = 0.55; s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.02; }, y);
    await settle(); await page.locator("#view").screenshot({ path: path.join(out, "shots", `bald_${p}_${y}.png`), timeout: 900000 });
    console.log("shot", p, y);
  }
}
console.log(JSON.stringify({ errors }));
await browser.close();
process.exit(errors.length ? 1 : 0);
