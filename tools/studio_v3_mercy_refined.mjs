// Mercy face refinement: Mercy-inspired (Phase 3C) and Mercy-inspired (refined) in the real Character Studio, picked
// through the Identity tab on the female body preset, identical cameras. Bald (styling only) at front, three-quarter
// and profile, eye close-ups open / half-lidded (blink 0.35) / closed, a hair-on look with the existing styling
// (shoulder hair, silver with a purple highlight), body dumps for the Python comparison, and a browser GLB export each.
// usage: node tools/studio_v3_mercy_refined.mjs <base-url> <outdir>
import fs from "node:fs";
import path from "node:path";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const [base, out] = process.argv.slice(2);
for (const d of ["shots", "dumps"]) fs.mkdirSync(path.join(out, d), { recursive: true });
const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1000, height: 700 } });
page.setDefaultTimeout(900000);
const errors = [], checks = [];
page.on("pageerror", (e) => errors.push(String(e)));
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
const ok = (name, pass, detail = "") => { checks.push({ name, pass: !!pass, detail }); console.log(pass ? "PASS" : "FAIL", name, detail); };
await page.goto(base + "?gen=3");
await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 600000 });

const PRESETS = ["MERCY-INSPIRED", "MERCY-REFINED"];
const settle = (n = 3) => page.evaluate((n) => new Promise((r) => { const f0 = window.studio.frames; const t = () => (window.studio.frames - f0 >= n ? r() : requestAnimationFrame(t)); t(); }), n);
const shot = async (name) => { await settle(); await page.locator("#view").screenshot({ path: path.join(out, "shots", `${name}.png`), timeout: 900000 }); };
const reset = () => page.evaluate(() => { const s = window.studio; s.applyPreset("female", false); s.state.clip = "none"; s.playing = false; s.clipT = 0;
  s.spin.yaw = 0; s.spin.vel = 0; s.state.pose = "A-pose (rest)"; s.state.expr = {}; document.getElementById("turntable").checked = false; s.dirtyGeo = true; s.evaluate(); });
const faceCam = (yawDeg, dist = 0.55, drop = 0.035) => page.evaluate(([y, d, dr]) => { const s = window.studio; s.evaluate();
  const a = s.parts.eye_l.g.eyeC, b = s.parts.eye_r.g.eyeC; s.cam.target = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2 - dr, (a[2] + b[2]) / 2];
  s.cam.dist = d; s.cam.yaw = y * Math.PI / 180; s.cam.pitch = 0.02; }, [yawDeg, dist, drop]);
const pick = async (name) => { await page.click("#t-identity"); await page.click(`[data-identity="${name}"]`); await page.evaluate(() => window.studio.evaluate()); };
const style = async (hair, color, hl, amount) => { await page.click("#t-look"); await page.selectOption("#hairstyle", hair);
  await page.evaluate(([c, h, a]) => { const s = window.studio; s.state.hair_color = c; s.state.hl_color = h; s.state.hl_amount = a; s.dirtyGeo = true; s.syncUI(); s.evaluate(); }, [color, hl, amount]); };
const setBlink = (w) => page.evaluate((w) => { const s = window.studio; s.state.expr = { blink_l: w, blink_r: w }; s.dirtyGeo = true; s.evaluate(); }, w);
const dump = async (tag) => {
  const d = await page.evaluate(() => { const s = window.studio; s.evaluate(); const b = s.parts.body.cur;
    const enc = (a) => { const u = new Uint8Array(a.buffer, a.byteOffset, a.byteLength); let t = ""; for (let i = 0; i < u.length; i += 32768) t += String.fromCharCode(...u.subarray(i, i + 32768)); return btoa(t); };
    return { body: enc(Float32Array.from(b)), params: s.state.params, identity: s.state.identity, lidFit: s.state.lidFit || 1, expr: s.state.expr,
      affinity: s.presetAffinity() }; });
  fs.writeFileSync(path.join(out, "dumps", `${tag}.f4`), Buffer.from(d.body, "base64"));
  delete d.body; fs.writeFileSync(path.join(out, "dumps", `${tag}.json`), JSON.stringify(d));
  return d;
};

const listed = await page.evaluate(() => [...document.querySelectorAll("[data-identity]")].map((b) => b.dataset.identity));
ok("both Mercy presets are offered", PRESETS.every((p) => listed.includes(p)), listed.join(", "));
for (const p of PRESETS) {
  await reset();
  const eye0 = await page.evaluate(() => window.studio.state.params["face.eye_size"]);  // the female body preset's own value
  await pick(p);
  const st = await page.evaluate(() => { const s = window.studio; return { preset: s.state.identity.preset, fem: s.state.params["body.femininity"],
    eye: s.state.params["face.eye_size"], lidFit: s.state.lidFit || 1, note: document.getElementById("identity-note").textContent }; });
  ok(`${p}: preset and its controls applied`, st.preset === p && st.fem === 1 && st.eye === (p === "MERCY-REFINED" ? 1.25 : eye0) && st.lidFit === 2, JSON.stringify(st));
  for (const w of [0, 0.35, 1]) { await setBlink(w); await dump(`${p}_blink${w}`); }
  await setBlink(0);
  await style("bald", "#3b2416", "#a47b52", 0);
  for (const y of [0, 35, 90]) { await faceCam(y); await shot(`bald_${p}_${y}`); }
  for (const w of [0, 0.35, 1]) { await setBlink(w); await faceCam(12, 0.22, 0); await shot(`eyes_${p}_${w}`); }
  await setBlink(0);
  await style("shoulder", "#d9d6de", "#7a3fb5", 0.6);
  for (const y of [0, 35]) { await faceCam(y); await shot(`hair_${p}_${y}`); }
  await page.evaluate((p) => { window.studio.state.name = p.toLowerCase().replace(/-/g, "_"); }, p);
  const glb = await page.evaluate(() => { const b = window.studio.exportBytes(); let s = ""; for (let i = 0; i < b.length; i += 32768) s += String.fromCharCode(...b.subarray(i, i + 32768)); return btoa(s); });
  const name = `v3_identity_${p.toLowerCase().replace(/-/g, "_")}`;
  fs.writeFileSync(path.join(out, `${name}.glb`), Buffer.from(glb, "base64"));
  fs.writeFileSync(path.join(out, `${name}.dna.json`), JSON.stringify(await page.evaluate(() => window.studio.toDNA()), null, 1));
  ok(`GLB exported: ${p}`, glb.length > 1e6, `${(glb.length * 0.75 / 1e6).toFixed(1)} MB`);
}
ok("no page errors", !errors.length, errors.slice(0, 3).join(" | "));
fs.writeFileSync(path.join(out, "studio_checks.json"), JSON.stringify({ checks, errors }, null, 1));
await browser.close();
process.exit(checks.every((c) => c.pass) ? 0 : 1);
