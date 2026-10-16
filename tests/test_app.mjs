// End-to-end smoke test of the app (.claude/app) in headless Chrome, against a real home server on a temporary
// library: new project, a dropped video lands in the bin and on the main track, an add then undo, a change made
// by Claude's CLI (project.py apply) shows up live with a toast, and the Player's media seeks (206).
// Uses the renderer's chrome-headless-shell over the DevTools pipe (no Playwright needed).
//   node tests/test_app.mjs [--shot out.png]
import { spawn, spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const realHome = process.env.AI_EDITOR_HOME || path.join(os.homedir(), ".ai-video-editor");
const py = process.platform === "win32" ? "python" : "python3";
const lib = path.join(root, ".claude", "lib", "ai_editor");
const shot = process.argv.includes("--shot") ? process.argv[process.argv.indexOf("--shot") + 1] : path.join(os.tmpdir(), "ai-editor-app.png");
const fail = (m) => { console.error(`FAIL ${m}`); cleanup(); process.exit(1); };
let server, chrome, tmp;
function cleanup() {
  try { chrome?.close(); } catch {}
  try { server?.kill(); } catch {}
  try { if (tmp) fs.rmSync(tmp, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 }); } catch {}
}

// 1. the bundle, built with the real renderer install
const b = spawnSync(py, [path.join(lib, "app_render.py"), "build"], { encoding: "utf8", env: { ...process.env, AI_EDITOR_HOME: realHome } });
if (b.status) fail(`build: ${b.stdout}${b.stderr}`);

// 2. a home server on an empty library
tmp = fs.mkdtempSync(path.join(os.tmpdir(), "ai-editor-app-"));
const env = { ...process.env, AI_EDITOR_HOME: path.join(tmp, "home"), AI_EDITOR_LIBRARY: path.join(tmp, "lib"), AI_EDITOR_OPEN: "app" };
fs.mkdirSync(env.AI_EDITOR_LIBRARY, { recursive: true });
server = spawn(py, [path.join(lib, "home.py"), "serve", "--port", "0", "--no-open", "--root", env.AI_EDITOR_LIBRARY], { env, stdio: ["ignore", "pipe", "pipe"] });
let errs = "";
server.stderr.on("data", (d) => { errs = (errs + d).slice(-2000); });
const url = await new Promise((ok, no) => {
  let buf = "";
  server.stdout.on("data", (d) => { buf += d; const m = buf.match(/http:\/\/127\.0\.0\.1:\d+\/\?t=\S+/); if (m) ok(m[0]); });
  setTimeout(() => no(new Error(`no server url: ${errs}`)), 30000);
}).catch((e) => fail(e.message));
const base = url.replace(/\/\?t=.*/, ""), token = url.split("t=")[1];

// 3. a small clip to drop in
const clip = path.join(tmp, "take.mp4");
const ff = spawnSync("ffmpeg", ["-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=640x360:d=3:r=30", "-f", "lavfi", "-i", "sine=d=3",
  "-shortest", "-pix_fmt", "yuv420p", "-c:v", "libx264", clip]);
if (ff.status) fail("ffmpeg could not make the test clip");

// 4. Chrome over the DevTools pipe
const shells = path.join(realHome, "remotion", "node_modules", ".remotion", "chrome-headless-shell");
const find = (d) => { for (const e of fs.existsSync(d) ? fs.readdirSync(d, { withFileTypes: true }) : []) {
  const p = path.join(d, e.name);
  if (e.isFile() && /^chrome-headless-shell(\.exe)?$/.test(e.name)) return p;
  if (e.isDirectory()) { const h = find(p); if (h) return h; } } return null; };
const bin = find(shells);
if (!bin) fail(`no chrome-headless-shell under ${shells} (run setup.py remotion)`);
chrome = (() => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), "ai-editor-chrome-"));
  const proc = spawn(bin, ["--remote-debugging-pipe", "--no-first-run", "--mute-audio", "--autoplay-policy=no-user-gesture-required",
    ...(process.platform === "linux" ? ["--no-sandbox", "--disable-dev-shm-usage"] : []), `--user-data-dir=${profile}`, "about:blank"],
    { stdio: ["ignore", "ignore", "pipe", "pipe", "pipe"] });
  let id = 0, buf = "";
  const waiting = new Map(), listeners = [];
  proc.stdio[4].on("data", (d) => {
    buf += d.toString();
    let i;
    while ((i = buf.indexOf("\0")) >= 0) {
      const m = JSON.parse(buf.slice(0, i));
      buf = buf.slice(i + 1);
      if (m.id && waiting.has(m.id)) { const [ok, no] = waiting.get(m.id); waiting.delete(m.id); m.error ? no(new Error(m.error.message)) : ok(m.result); }
      else listeners.forEach((l) => l(m));
    }
  });
  const send = (method, params = {}, sessionId) => new Promise((ok, no) => {
    waiting.set(++id, [ok, no]);
    proc.stdio[3].write(JSON.stringify({ id, method, params, sessionId }) + "\0");
  });
  return { send, on: (l) => listeners.push(l), close: () => { proc.kill(); try { fs.rmSync(profile, { recursive: true, force: true }); } catch {} } };
})();
const { targetId } = await chrome.send("Target.createTarget", { url: "about:blank" });
const { sessionId: s } = await chrome.send("Target.attachToTarget", { targetId, flatten: true });
const pageErrors = [];
chrome.on((m) => {
  if (m.sessionId !== s) return;
  if (m.method === "Runtime.exceptionThrown") pageErrors.push(m.params.exceptionDetails?.exception?.description ?? m.params.exceptionDetails?.text);
});
await chrome.send("Runtime.enable", {}, s);
await chrome.send("Page.enable", {}, s);
await chrome.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false }, s);
await chrome.send("Page.navigate", { url: `${base}/app/?t=${token}` }, s);
const js = async (expr) => {
  const r = await chrome.send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true }, s);
  if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
  return r.result.value;
};
const until = async (expr, what, ms = 20000) => {
  const t0 = Date.now();
  for (;;) {
    try { if (await js(expr)) return; } catch {}
    if (Date.now() - t0 > ms) fail(`timed out waiting for ${what} (${await js(`JSON.stringify({rows: [...document.querySelectorAll(".row")].map(r => r.className + ":" + r.querySelectorAll(".item").length), toasts: [...document.querySelectorAll(".toast")].map(t => t.className), stateToasts: window.__aiEditor.getState().toasts.length})`).catch(() => "?")})${pageErrors.length ? `; page errors: ${pageErrors.join(" | ")}` : ""}`);
    await new Promise((ok) => setTimeout(ok, 200));
  }
};
const ok = (m) => console.log(`ok   ${m}`);
const S = "window.__aiEditor.getState()";

await until("!!window.__aiEditor", "the app to load");
ok("app loaded at /app/");
await js(`window.__aiEditor.newProject("Smoke test", "youtube")`);
await until(`${S}.doc && ${S}.doc.width === 1920`, "the new project");
ok("new project (YouTube 1920x1080)");

// drop the clip: a File the page builds from its bytes, through the same uploadFiles the drop handler calls
const b64 = fs.readFileSync(clip).toString("base64");
await js(`(async () => { const b = Uint8Array.from(atob(${JSON.stringify(b64)}), c => c.charCodeAt(0));
  await window.__aiEditor.uploadFiles([new File([b], "take.mp4", { type: "video/mp4" })]); })()`);
await until(`${S}.doc.tracks.find(t => t.role === "main").items.length === 1 && ${S}.doc.rev >= 1`, "the clip on the main track");
await until(`document.querySelectorAll(".bin .asset").length >= 1 && document.querySelectorAll(".r-main .item").length === 1`, "the bin and the timeline to show it");
ok("dropped video: in the bin, on the main track (90 frames)");
const main = await js(`${S}.doc.tracks.find(t => t.role === "main").items[0]`);
if (main.durationInFrames !== 90) fail(`clip length ${main.durationInFrames}, want 90`);

// add onto b-roll, then undo
const rev0 = await js(`${S}.doc.rev`);
const aid = await js(`Object.keys(${S}.doc.assets)[0]`);
await js(`window.__aiEditor.dispatch("Add to b-roll", [{ op: "add", track: "broll", item: { type: "video", asset: ${JSON.stringify(aid)}, from: 15, durationInFrames: 30, trimIn: 0 } }])`);
await until(`${S}.doc.rev === ${rev0 + 1} && document.querySelectorAll(".r-broll .item").length === 1`, "the b-roll add to save");
await js(`window.__aiEditor.undo()`);
await until(`${S}.doc.rev === ${rev0 + 2} && ${S}.doc.tracks.find(t => t.role === "broll").items.length === 0`, "undo");
ok("add on b-roll saved (rev+1), undo removed it (rev+2)");

// Claude edits the same project from the CLI: the app picks it up live, with a toast
const edit = await js(`${S}.edit`);
const ops = JSON.stringify({ ops: [{ op: "add", track: "zooms", item: { type: "zoom", from: 30, durationInFrames: 30, props: { scale: 1.2, kind: "punch" } } }] });
const cli = spawnSync(py, [path.join(root, ".claude", "skills", "style-edit", "scripts", "project.py"), "apply", edit, "-", "--author", "claude",
  "--label", "Punch in on the hook"], { input: ops, encoding: "utf8", env });
if (cli.status) fail(`project.py apply: ${cli.stdout}${cli.stderr}`);
const tc = Date.now();
await until(`${S}.doc.tracks.find(t => t.role === "zooms").items.length === 1 && ${S}.toasts.some(t => t.kind === "claude")`, "Claude's change to show", 35000);
console.log(`     (seen ${Date.now() - tc} ms after the CLI wrote it)`);
await until(`!!document.querySelector(".toast.claude")`, "Claude's toast");
await until(`document.querySelectorAll(".r-zooms .item").length === 1`, "the zoom on the timeline");
ok("project.py apply (author claude) showed live: zoom on the timeline, toast with Undo");

// the Player's media seeks
const status = await js(`fetch(window.remotion_staticBase + "/media/take.mp4", { headers: { Range: "bytes=0-99" } }).then(r => r.status)`);
if (status !== 206) fail(`media range request answered ${status}, want 206`);
ok("media seeks (206 on a range request)");

// the preview is the real composition
await until(`!!document.querySelector(".stage .frame video, .stage .frame canvas")`, "the Player's video");
await js(`window.__aiEditor.seek(45)`);
await new Promise((r) => setTimeout(r, 1200));
ok("Player mounted and seeks");

const png = await chrome.send("Page.captureScreenshot", { format: "png" }, s);
fs.writeFileSync(shot, Buffer.from(png.data, "base64"));
ok(`screenshot ${shot}`);
if (pageErrors.length) fail(`page errors: ${pageErrors.join(" | ")}`);
cleanup();
console.log("app smoke ok");
process.exit(0);
