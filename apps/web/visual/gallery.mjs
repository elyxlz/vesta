// Builds .visual/web/index.html from the captured PNGs and optionally serves it.
// Cells follow the project matrix; a missing cell renders as an empty slot.
import { readdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { createServer } from "node:http";
import { execFile } from "node:child_process";
import path from "node:path";

const DIR = path.resolve(import.meta.dirname, "../.visual/web");
const CELLS = ["dark-desktop", "light-desktop", "dark-narrow", "light-narrow"];
const PORT = 4174;

const files = existsSync(DIR)
  ? readdirSync(DIR).filter((f) => f.endsWith(".png"))
  : [];
const ids = [...new Set(files.map((f) => f.split("--")[0]))].sort();

const rows = ids
  .map((id) => {
    const cells = CELLS.map((cell) => {
      const file = `${id}--${cell}.png`;
      return files.includes(file)
        ? `<a href="${file}"><img src="${file}" alt="${id} ${cell}" loading="lazy"></a>`
        : `<div class="missing">missing</div>`;
    }).join("");
    return `<section><h2>${id}</h2><div class="row">${cells}</div></section>`;
  })
  .join("\n");

const html = `<!doctype html><meta charset="utf-8"><title>web visual gallery</title>
<style>
body{font-family:system-ui;margin:2rem;background:#111;color:#eee}
h2{font-size:1rem;font-weight:600}
.row{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:2rem}
img{width:100%;border:1px solid #333;border-radius:8px}
.missing{display:grid;place-items:center;border:1px dashed #444;border-radius:8px;color:#666;min-height:120px}
</style>
<h1>web visual gallery (${String(ids.length)} scenarios)</h1>
<p>${CELLS.join(" | ")}</p>
${rows}`;

writeFileSync(path.join(DIR, "index.html"), html);
console.log(
  `gallery: ${String(ids.length)} scenarios, ${String(files.length)} captures`,
);

if (process.argv.includes("--serve")) {
  const types = { ".html": "text/html", ".png": "image/png" };
  createServer((req, res) => {
    const url = req.url === "/" ? "/index.html" : (req.url ?? "/index.html");
    const file = path.join(DIR, path.normalize(url));
    if (!file.startsWith(DIR) || !existsSync(file)) {
      res.writeHead(404);
      res.end();
      return;
    }
    res.writeHead(200, {
      "content-type": types[path.extname(file)] ?? "application/octet-stream",
    });
    res.end(readFileSync(file));
  }).listen(PORT, () => {
    console.log(`gallery served at http://127.0.0.1:${String(PORT)}`);
    if (process.argv.includes("--open")) {
      const opener = process.platform === "darwin" ? "open" : "xdg-open";
      execFile(opener, [`http://127.0.0.1:${String(PORT)}`], () => undefined);
    }
  });
}
