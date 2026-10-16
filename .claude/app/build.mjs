// Builds the editor app: src/main.tsx (and the renderer's own remotion/src it plays) into dist/app.js + app.css.
// Uses the renderer's node_modules ($AI_EDITOR_HOME/remotion, installed by setup), so the app and every render
// run the same Remotion and React. home.py (app_render.ensure_built) runs it when the sources change.
//   node .claude/app/build.mjs [--dev]
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const home = process.env.AI_EDITOR_HOME || path.join(os.homedir(), ".ai-video-editor");
const NM = path.join(home, "remotion", "node_modules");
if (!fs.existsSync(NM)) {
  console.error(`No renderer at ${NM}. Run: python3 .claude/skills/setup/scripts/setup.py remotion`);
  process.exit(1);
}
const esbuild = createRequire(path.join(NM, "noop.js"))("esbuild");
const dev = process.argv.includes("--dev");
fs.mkdirSync(path.join(here, "dist"), { recursive: true });
// the user's own components into remotion/src first (scripts/gen-registry.mjs), so the Player shows them as the render does
const src = path.join(here, "..", "remotion", "src");
const gen = path.join(here, "..", "remotion", "scripts", "gen-registry.mjs");
if (fs.existsSync(gen)) (await import(pathToFileURL(gen).href)).generate({ src });
await esbuild.build({
  entryPoints: { app: path.join(here, "src", "main.tsx") },
  outdir: path.join(here, "dist"),
  bundle: true,
  format: "esm",
  target: "es2020",
  jsx: "automatic",
  minify: !dev,
  sourcemap: dev ? "inline" : false,
  nodePaths: [NM],   // bare imports from the app and from remotion/src resolve in the renderer's install
  alias: { react: path.join(NM, "react"), "react-dom": path.join(NM, "react-dom") },   // one React for both
  loader: { ".json": "json", ".css": "css" },
  define: { "process.env.NODE_ENV": dev ? '"development"' : '"production"' },
  logLevel: "warning",
});
console.log(`built ${path.join(here, "dist", "app.js")}`);
