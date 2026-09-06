import { escapeHtml, scanRowsHtml, sectionHtml, sideNavHtml } from "./view.mjs";
import { captureSelection } from "../selection.mjs";

// The stylesheet and the client script are static files the server serves under
// /gallery/, separately from the lightweight live shot index.
export function galleryHtml(view) {
  const sections = view.sections.map(sectionHtml).join("");
  const suite = view.selection?.suite ?? captureSelection().suite;
  const scenarios = view.sections.flatMap((section) => section.scenarios);
  const slots = scenarios.flatMap((scenario) => scenario.slots);
  const captured = slots.filter((slot) => slot.state === "captured").length;
  const targets = new Set(slots.map((slot) => slot.platform)).size;
  const noun = suite === "all" ? "scenarios" : suite;
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
<body data-revision="${escapeHtml(view.git.revision)}" data-suite="${suite}" data-page="${escapeHtml(view.selection?.page ?? "")}">
  <a class="skip-link" href="#gallery-content">Skip to screenshots</a>
  <div class="layout">
    <nav class="side" aria-label="Gallery">
      <a class="brand" href="/"><span class="brand-mark" aria-hidden="true">v.</span><span>Vesta<span class="brand-caption">VISUAL QA</span></span></a>
      <div class="suite-nav">
        <a href="/?suite=all"${suite === "all" ? ' aria-current="page"' : ""}><span>All scenarios</span><span aria-hidden="true">↗</span></a>
        <a href="/?suite=pages"${suite === "pages" ? ' aria-current="page"' : ""}><span>Page library</span><span aria-hidden="true">↗</span></a>
        <a href="/?suite=states"${suite === "states" ? ' aria-current="page"' : ""}><span>Edge cases</span><span aria-hidden="true">↗</span></a>
      </div>
      <div class="side-nav"><p class="side-label">COLLECTIONS</p>${sideNavHtml(view)}</div>
      <section class="scan-bar" aria-label="Capture runs">
        <p class="side-label">CAPTURE RUNNERS</p>${scanRowsHtml()}
        <button class="scan-button scan-open" id="scan-open" type="button" title="Plan a scan: see which shots changed on each platform, then start it."><span aria-hidden="true">＋</span> New capture</button>
      </section>
      <footer class="side-footer"><div class="report-links"><a href="references.json">JSON index ↗</a>${reportLinks}</div><span class="revision">${escapeHtml(view.git.revision)}${view.git.dirty ? " · dirty" : ""}</span></footer>
    </nav>
    <main id="gallery-content" tabindex="-1">
      <header class="workspace-header">
        <div><p class="eyebrow">THE APP, IN EVERY DETAIL</p><h1>${suite === "states" ? "Edge cases" : "Visual library"}<span class="title-dot">.</span></h1><p class="workspace-description">${suite === "states" ? "The uncommon states, ready for a closer look." : "Every page and state. Every platform. A clear view of what changed."}</p></div>
        <dl class="library-stats"><div><dt>${noun}</dt><dd>${scenarios.length}</dd></div><div><dt>targets</dt><dd>${targets}</dd></div><div><dt>saved captures</dt><dd>${captured}</dd></div></dl>
      </header>
      <div class="library-toolbar">
        <div class="search-field"><svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 4.5 4.5"/></svg><label class="sr-only" for="page-search">Find a page, state, or route</label><input id="page-search" type="search" placeholder="Find a page, state, or route…"></div>
        <span id="search-count" role="status">${scenarios.length} ${noun}</span>
        <button class="theme-toggle" id="theme-toggle" type="button" aria-pressed="false" title="Show screenshots captured in the app’s dark theme."><svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg><span>Dark captures</span><span class="toggle-track" aria-hidden="true"></span></button>
      </div>
      <div id="search-empty" class="empty-state" hidden><span aria-hidden="true">∅</span><h2>No matching screens</h2><p>Try a page name or route, or clear your search.</p></div>
      ${sections}
      <footer class="workspace-footer"><span>VESTA · VISUAL QA</span><span>Captured pixels. A shared point of reference.</span></footer>
    </main>
  </div>
  <dialog id="lightbox">
    <button aria-label="Close">×</button>
    <nav class="page-images"><button id="image-previous" type="button">Previous</button><span id="image-position"></span><button id="image-next" type="button">Next</button><a id="image-file" target="_blank">Open image</a></nav>
    <img alt="">
  </dialog>
  <dialog id="review-dialog" class="review-dialog" aria-labelledby="review-title">
    <header class="review-header">
      <div><h2 id="review-title">Pixel comparison</h2><p id="review-status" role="status"></p></div>
      <button type="button" id="review-close" aria-label="Close comparison">×</button>
    </header>
    <div class="review-images">
      <figure><figcaption>01 <span>Baseline</span></figcaption><img id="review-baseline" alt="Approved baseline"><p class="review-empty">No baseline image</p></figure>
      <figure><figcaption>02 <span>Current</span></figcaption><img id="review-current" alt="Current capture"><p class="review-empty">No current image</p></figure>
      <figure><figcaption>03 <span>Difference</span></figcaption><img id="review-diff" alt="Changed pixels highlighted"><p class="review-empty">No difference image</p></figure>
    </div>
    <footer><label>Page section <select id="review-part"></select></label> <button type="button" id="review-approve" disabled>Approve entire page</button></footer>
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
  <script src="gallery/review.js"></script>
</body>
</html>`;
}
