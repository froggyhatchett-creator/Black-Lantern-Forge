// Stolen Fire E2 in the real Character Studio (Playwright + Chromium/SwiftShader): exports the three test characters
// (neutral, ID-A, the longest legs) with foot locks off and on, checks the option's UI and that it leaves the DNA
// alone, and captures the walk with the option on. tools/footlock_report.py then measures the GLBs.
// usage: node tools/studio_v3_footlock.mjs <base-url> <outdir> [id_a.dna.json]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";

const root = path.join(path.dirname(fileURLToPath(import.meta.url)), "..");
const base = process.argv[2] || "http://127.0.0.1:8799/";
const out = process.argv[3] || "stolen_fire_e2";
const idA = JSON.parse(fs.readFileSync(process.argv[4] || path.join(root, "examples/character_forge_aaa/humanity/v3_phase3d/v3_identity_id_a.dna.json"), "utf8"));
for (const d of ["off", "on", "shots"]) fs.mkdirSync(path.join(out, d), { recursive: true });
const checks = [];
const ok = (name, pass, detail = "") => { checks.push({ name, pass: !!pass, detail }); console.log(`${pass ? "PASS" : "FAIL"} ${name} ${detail}`); };

const browser = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const errors = [];
const open = async (url) => {
  const page = await browser.newPage({ viewport: { width: 1200, height: 860 } });
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto(url);
  await page.waitForFunction(() => document.body.dataset.ready, null, { timeout: 180000 });
  return page;
};

// the option is offered on generator v3 only, unticked
const v2 = await open(base);
ok("v2 studio: no foot-lock option", await v2.evaluate(() => document.getElementById("foot-lock-row").hidden && document.getElementById("foot-lock-note").hidden));
await v2.close();
const page = await open(base + "?gen=3");
ok("v3 studio: foot-lock option shown, unticked", await page.evaluate(() => !document.getElementById("foot-lock-row").hidden && !document.getElementById("foot-lock").checked
  && window.studio.footLock === false));

const chars = {
  neutral: () => { const s = window.studio; s.applyPreset("neutral", false); s.evaluate(); },
  id_a: (d) => { const s = window.studio; s.fromDNA(d); s.evaluate(); },
  long_legs: () => { const s = window.studio; s.applyPreset("neutral", false); s.state.params["body.leg_length"] = s.man.params["body.leg_length"].max; s.evaluate(); },
};
const grab = (lock) => page.evaluate((lock) => {
  const s = window.studio, box = document.getElementById("foot-lock");
  if (box.checked !== lock) box.click();  // through the UI, as a user would
  const b = s.exportBytes(); let str = ""; for (let i = 0; i < b.length; i += 32768) str += String.fromCharCode(...b.subarray(i, i + 32768));
  return { glb: btoa(str), dna: JSON.stringify(s.toDNA()), footLock: s.footLock };
}, lock);
for (const [name, fn] of Object.entries(chars)) {
  await page.evaluate(fn, idA);
  const off = await grab(false), on = await grab(true), off2 = await grab(false);
  fs.writeFileSync(path.join(out, "off", `${name}.glb`), Buffer.from(off.glb, "base64"));
  fs.writeFileSync(path.join(out, "on", `${name}.glb`), Buffer.from(on.glb, "base64"));
  ok(`${name}: the checkbox sets the option`, on.footLock === true && off.footLock === false);
  ok(`${name}: off -> on -> off exports the same bytes when off`, off.glb === off2.glb);
  ok(`${name}: on differs from off`, on.glb !== off.glb);
  ok(`${name}: the option leaves the DNA unchanged`, on.dna === off.dna);
}
// the preview plays the locked walk
await page.evaluate(() => { const s = window.studio, box = document.getElementById("foot-lock"); if (!box.checked) box.click();
  s.applyPreset("neutral", false); s.evaluate(); s.state.clip = "walk"; document.getElementById("clip").value = "walk"; s.playing = true; s.clipT = 0; });
await page.waitForTimeout(1500);
await page.locator("#view").screenshot({ path: path.join(out, "shots", "studio_walk_foot_locks_on.png") });
const tab = await page.evaluate(() => document.getElementById("glb-export").closest("[role=tabpanel]").id);
await page.locator(`[aria-controls=${tab}]`).click();
await page.locator("fieldset:has(#glb-export)").screenshot({ path: path.join(out, "shots", "studio_export_panel.png") });
ok("preview uses the locked walk", await page.evaluate(() => window.studio.playClip("walk") !== window.studio.clips.walk));
ok("no console or page errors", errors.length === 0, JSON.stringify(errors));
fs.writeFileSync(path.join(out, "studio_checks.json"), JSON.stringify({ checks, errors }, null, 1));
await browser.close();
process.exit(checks.every((c) => c.pass) ? 0 : 1);
