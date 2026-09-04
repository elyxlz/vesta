// The preload runs in a sandboxed renderer, whose require() resolves only electron and a few Node
// built-ins, never a relative file. tsc leaves the `./channels` import as require("./channels"),
// which throws before exposeInMainWorld runs, so the app loses window.vestaNative and falls back
// to the browser bridge. esbuild inlines every local import into one self-contained file the
// sandbox can load; electron stays external because it is the one module the sandbox provides.
// Wired as electron-builder's beforeBuild hook so every package build bundles the preload, and
// run directly by `npm run compile` for dev and local builds. Both paths call one bundler.
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import path from "node:path";

const desktopDir = fileURLToPath(new URL("..", import.meta.url));

export async function bundlePreload() {
  await build({
    entryPoints: [path.join(desktopDir, "src", "preload.ts")],
    outfile: path.join(desktopDir, "dist-electron", "preload.js"),
    bundle: true,
    platform: "node",
    format: "cjs",
    target: "node20",
    external: ["electron"],
  });
}

export default async function beforeBuild() {
  await bundlePreload();
}

if (process.argv[1] === fileURLToPath(import.meta.url)) await bundlePreload();
