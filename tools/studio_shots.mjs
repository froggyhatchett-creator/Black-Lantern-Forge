// Usage: node tools/studio_shots.mjs <url> <outdir> — close-up review shots (face front/3q, hands, feet, full body front/back).
import { chromium } from "/opt/node-tools/node_modules/playwright/index.mjs";
import path from "node:path";
const [url, out] = process.argv.slice(2);
const b = await chromium.launch({ args: ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const p = await b.newPage({ viewport: { width: 1280, height: 800 } });
await p.goto(url); await p.waitForFunction(() => document.body.dataset.ready, null, { timeout: 120000 });
const frames = async (n = 3) => { const f = await p.evaluate(() => window.studio.frames); await p.waitForFunction((f) => window.studio.frames >= f, f + n, { timeout: 60000 }); };
const shot = async (name, where, yaw, preset, look) => {
  await p.evaluate(([w, y, pr, lk]) => { const st = window.studio; if (pr) st.applyPreset(pr); if (lk) { Object.assign(st.state, lk); st.syncUI(); st.dirtyGeo = true; }
    st.state.clip = "none"; st.focus(w); st.cam.yaw = y; st.cam.pitch = 0.05; }, [where, yaw, preset, look]);
  await frames(); await p.locator("canvas").screenshot({ path: path.join(out, name) });
};
const list = JSON.parse(process.argv[4] || "null") || [["face_front.png", "face", 0], ["face_3q.png", "face", 0.6], ["hands.png", "hands", 0.3], ["feet.png", "feet", 0.4], ["body_front.png", "body", 0], ["body_back.png", "body", Math.PI]];
for (const [n, w, y, pr, lk] of list) await shot(n, w, y, pr, lk);
await b.close();
