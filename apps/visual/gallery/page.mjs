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
          <button class="scan-button scan-open" id="scan-open" type="button" title="Plan a scan: see which shots changed on each platform, then start it.">Scan…</button>
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
  <dialog id="plan-dialog" class="plan-dialog" aria-labelledby="plan-title">
    <form method="dialog" class="plan">
      <header class="plan-header">
        <div>
          <h2 id="plan-title">Plan a scan</h2>
          <p class="plan-note" id="plan-note">Checking what changed…</p>
        </div>
        <button type="button" class="plan-close" id="plan-cancel" aria-label="Close">×</button>
      </header>
      <div class="plan-runners" id="plan-runners"></div>
      <footer class="plan-footer">
        <div class="plan-options">
          <label class="gentle-toggle" title="Capture at background priority with fewer workers: slower, but the machine stays responsive.">
            <input type="checkbox" id="gentle-toggle" checked>
            <span>Gentle</span>
          </label>
          <label class="gentle-toggle" title="Retake every shot, changed or not.">
            <input type="checkbox" id="plan-all">
            <span>Everything</span>
          </label>
        </div>
        <button type="button" class="scan-button" id="plan-start" disabled>Start</button>
      </footer>
    </form>
  </dialog>
  <script src="gallery/client.js"></script>
</body>
</html>`;
}
