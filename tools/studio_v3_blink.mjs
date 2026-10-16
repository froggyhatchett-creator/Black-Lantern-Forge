// Phase 4A blink evidence in the real Character Studio: identical cameras and states, run against the Phase 3D build
// ("before") and this build ("after"). Hair style bald (styling only; the hair does not touch the lids and costs
// minutes per software-rendered frame). Close-ups at half and full blink for Neutral, ID-A, ID-B and Mercy-inspired
// on the female body preset, one identity/body stress combination, a walk frame while blinking, and (after only)
// body dumps for the Python comparison.
// usage: node tools/studio_v3_blink.mjs <base-url> <outdir> <prefix> [--dump]
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const [base, out, prefix] = process.argv.slice(2);
const dumpOn = process.argv.includes("--dump");
fs.mkdirSync(path.join(out, "shots"), { recursive: true });
fs.mkdirSync(path.join(out, "dumps"), { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
page.setDefaultTimeout(900000);
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(base + "?gen=3");
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 600000 });
const settle = (n = 3) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const t = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(t)); t(); }), n);
const shot = async (name) => { await settle(); await page.locator("#view").screenshot({ path: path.join(out, "shots", `${prefix}_${name}.png`) }); console.log("shot", name); };
const setup = async (idn, ctl = {}) => {
  await page.evaluate(() => { const s = window.studio; s.applyPreset("female", false); s.state.clip = "none"; s.playing = false; s.clipT = 0; s.spin.yaw = 0;
    s.state.pose = "A-pose (rest)"; s.state.expr = {}; document.getElementById("turntable").checked = false; });
  await page.click("#t-identity"); await page.click(`[data-identity="${idn}"]`);
  await page.evaluate((ctl) => { const s = window.studio; for (const [k, v] of Object.entries(ctl)) s.setParam(k, v, { record: false }); s.state.hair_style = "bald"; s.evaluate(); }, ctl);
};
const blink = (w) => page.evaluate((w) => { const s = window.studio; s.state.expr = { blink_l: w, blink_r: w }; s.evaluate(); }, w);
const eyeCam = (yaw) => page.evaluate((y) => { const s = window.studio; s.evaluate(); const a = s.parts.eye_l.g.eyeC;
  s.cam.target = [a[0] - 0.012, a[1] - 0.002, a[2]]; s.cam.dist = 0.16; s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.05; }, yaw);
const dump = async (tag) => {
  const d = await page.evaluate(() => { const s = window.studio; s.evaluate(); const b = Float32Array.from(s.parts.body.cur), u = new Uint8Array(b.buffer); let t = "";
    for (let i = 0; i < u.length; i += 32768) t += String.fromCharCode(...u.subarray(i, i + 32768));
    const L = Float32Array.from(s.parts.lashes.cur), ul = new Uint8Array(L.buffer); let tl = ""; for (let i = 0; i < ul.length; i += 32768) tl += String.fromCharCode(...ul.subarray(i, i + 32768));
    return { body: btoa(t), lashes: btoa(tl), params: s.state.params, identity: s.state.identity, expr: s.state.expr, height: s.heightNow }; });
  fs.writeFileSync(path.join(out, "dumps", `${tag}.f4`), Buffer.from(d.body, "base64"));
  fs.writeFileSync(path.join(out, "dumps", `${tag}_lashes.f4`), Buffer.from(d.lashes, "base64"));
  delete d.body; delete d.lashes; fs.writeFileSync(path.join(out, "dumps", `${tag}.json`), JSON.stringify(d));
};
const CASES = [["neutral", {}], ["ID-A", {}], ["ID-B", {}], ["MERCY-INSPIRED", {}], ["MERCY-INSPIRED", { "face.eye_size": 0.8 }]];
for (const [idn, ctl] of CASES) {
  const tag = idn + (Object.keys(ctl).length ? "_eye0.8" : "");
  await setup(idn, ctl);
  for (const w of [0, 0.5, 1]) {
    await blink(w);
    if (dumpOn) await dump(`blink_${tag}_${w}`);
    if (w) for (const y of [10, 50]) { await eyeCam(y); await shot(`${tag}_w${w}_y${y}`); }
  }
}
// walking while blinking (studio playback state at walk frame 10)
await setup("ID-A");
await page.evaluate(() => { const s = window.studio; s.state.clip = "walk"; s.playing = true; });
await settle(6);
await page.evaluate(() => { const s = window.studio; s.playing = false; s.clipT = 10 / 30; s.state.expr = { blink_l: 0.5, blink_r: 0.5 }; s.dirtyGeo = true;
  s.evaluate(); const a = s.parts.eye_l.g.eyeC, b = s.parts.eye_r.g.eyeC; s.cam.target = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2]; s.cam.dist = 0.5; s.cam.yaw = 0.5; s.cam.pitch = 0.05; });
await shot("walk10_blink0.5");
// return to neutral: blink 1 then 0 restores the open geometry exactly
const ret = await page.evaluate(() => { const s = window.studio; s.state.expr = {}; s.evaluate(); const a = Float32Array.from(s.parts.body.cur), l = Float32Array.from(s.parts.lashes.cur);
  s.state.expr = { blink_l: 1, blink_r: 1 }; s.evaluate(); s.state.expr = { blink_l: 0, blink_r: 0 }; s.evaluate();
  let m = 0, ml = 0; for (let i = 0; i < a.length; i++) m = Math.max(m, Math.abs(a[i] - s.parts.body.cur[i])); for (let i = 0; i < l.length; i++) ml = Math.max(ml, Math.abs(l[i] - s.parts.lashes.cur[i]));
  return { body_m: m, lashes_m: ml }; });
console.log(JSON.stringify({ return_to_neutral: ret, errors }));
fs.writeFileSync(path.join(out, `${prefix}_studio_blink.json`), JSON.stringify({ return_to_neutral: ret, errors }, null, 1));
await browser.close();
