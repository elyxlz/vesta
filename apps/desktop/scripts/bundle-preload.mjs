// The preload runs in a sandboxed renderer, whose require() resolves only electron and a few Node
// built-ins, never a relative file. tsc leaves the `./channels` import as require("./channels"),
// which throws before exposeInMainWorld runs, so the app loses window.vestaNative and falls back
// to the browser bridge. esbuild inlines every local import into one self-contained file the
// sandbox can load; electron stays external because it is the one module the sandbox provides.
import { build } from "esbuild";
import { fileURLToPath } from "node:url";
import path from "node:path";

const desktopDir = fileURLToPath(new URL("..", import.meta.url));

await build({
  entryPoints: [path.join(desktopDir, "src", "preload.ts")],
  outfile: path.join(desktopDir, "dist-electron", "preload.js"),
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["electron"],
});
