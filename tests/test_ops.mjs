// The app's ops.ts against tests/fixtures/ops-cases.json, the cases project_store.py also passes (tests/check_ops.py).
// Bundles ops.ts with the renderer's esbuild ($AI_EDITOR_HOME/remotion/node_modules), then runs every case.
//   node tests/test_ops.mjs
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const home = process.env.AI_EDITOR_HOME || path.join(os.homedir(), ".ai-video-editor");
const req = createRequire(path.join(home, "remotion", "node_modules", "noop.js"));
const esbuild = req("esbuild");
const out = path.join(fs.mkdtempSync(path.join(os.tmpdir(), "ops-test-")), "ops.mjs");
await esbuild.build({ entryPoints: [path.join(root, ".claude", "app", "src", "ops.ts")], outfile: out, bundle: true, format: "esm",
  platform: "node", logLevel: "warning" });
const { applyOp, deriveDuration, OpError } = await import(pathToFileURL(out).href);

const fx = JSON.parse(fs.readFileSync(path.join(root, "tests", "fixtures", "ops-cases.json"), "utf8"));
// JSON.stringify with sorted keys: key order is not part of the contract
const canon = (x) => JSON.stringify(x, (k, v) => (v && typeof v === "object" && !Array.isArray(v)
  ? Object.fromEntries(Object.keys(v).sort().map((key) => [key, v[key]])) : v));
const bad = [];
for (const c of fx.cases) {
  const doc = JSON.parse(JSON.stringify(fx.base));
  let got;
  try {
    for (const op of c.ops) applyOp(doc, op, c.author);
    doc.durationInFrames = deriveDuration(doc);
    got = { doc };
  } catch (e) {
    if (!(e instanceof OpError)) throw e;
    got = { error: e.kind };
  }
  if (canon(got) !== canon(c.expect)) {
    bad.push(c.name);
    console.log(`FAIL ${c.name}\n  want ${canon(c.expect).slice(0, 400)}\n  got  ${canon(got).slice(0, 400)}`);
  }
}
console.log(bad.length ? `${bad.length} ops case(s) differ` : `${fx.cases.length}/${fx.cases.length} ops cases ok`);
process.exit(bad.length ? 1 : 0);
