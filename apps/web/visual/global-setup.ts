import { existsSync, readdirSync, rmSync } from "node:fs";
import path from "node:path";

const OUT_DIR = path.resolve(import.meta.dirname, "../.visual/web");

// Clear old top-level captures once before a run, so a renamed or removed
// scenario cannot leave a stale PNG the gallery would still show.
export default function globalSetup(): void {
  if (!existsSync(OUT_DIR)) return;
  for (const file of readdirSync(OUT_DIR)) {
    if (file.endsWith(".png")) rmSync(path.join(OUT_DIR, file));
  }
}
