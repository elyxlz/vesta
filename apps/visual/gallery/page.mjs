import { escapeHtml, scanRowsHtml, sectionHtml, sideNavHtml } from "./view.mjs";

// The stylesheet and the client script are static files the server serves under
// /gallery/, so the browser caches both across the 500 ms polls.
export function galleryHtml(view) {
  const sections = view.sections.map(sectionHtml).join("");
  const reportLinks = view.reports
    .map(
      (link) =>
        `<a class="report" href="${escapeHtml(link.href)}">${escapeHtml(link.label)}</a>`,
    )
    .join("\n      ");
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vesta Apps QA</title>
  <link rel="stylesheet" href="gallery/styles.css">
</head>
<body data-revision="${escapeHtml(view.git.revision)}">
  <div class="layout">
    <nav class="side" aria-label="Gallery">
      <h1>Vesta Apps QA</h1>
      <div class="meta">
        <span>${escapeHtml(view.git.revision)}${view.git.dirty ? " · dirty" : ""}</span>
        ${reportLinks}
      </div>
      <section class="scan-bar" aria-label="Capture runs">${scanRowsHtml()}
        <div class="scan-controls">
          <label class="gentle-toggle" title="Capture at background priority with fewer workers: slower, but the machine stays responsive.">
            <input type="checkbox" id="gentle-toggle" checked>
            <span>Gentle</span>
          </label>
          <button class="theme-toggle" id="theme-toggle" type="button" aria-pressed="false" aria-label="Dark theme" title="Show every screen in its dark theme.">
            <svg viewBox="0 0 24 24" width="14" height="14" aria-hidden="true"><path fill="currentColor" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg>
            <span>Dark</span>
          </button>
        </div>
      </section>
      <div class="side-nav">${sideNavHtml(view)}
      </div>
    </nav>
    <main>${sections}</main>
  </div>
  <dialog id="lightbox">
    <button aria-label="Close">×</button>
    <img alt="">
  </dialog>
  <script src="gallery/client.js"></script>
</body>
</html>`;
}
