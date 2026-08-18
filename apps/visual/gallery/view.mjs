import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";
import { promisify } from "node:util";
import {
  FAMILIES,
  PLATFORMS,
  RUNNERS,
  appsRoot,
  platformsOfFamily,
} from "../platforms.mjs";
import {
  excludedNote,
  loadAllRegistries,
  scenarioOnPlatform,
} from "../registry.mjs";
import { pngSize, shotEntries, storeDirectory } from "../store.mjs";

const execFileAsync = promisify(execFile);
const CARD_COLUMNS = 3;

export function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

export async function gitMetadata() {
  const git = (args) =>
    execFileAsync("git", args, { cwd: appsRoot })
      .then((result) => result.stdout.trim())
      .catch(() => "");
  return {
    revision: (await git(["rev-parse", "--short", "HEAD"])) || "unknown",
    dirty: Boolean(await git(["status", "--porcelain"])),
  };
}

function slotFor(scenario, platform, shots) {
  const { label, frame, theme } = PLATFORMS[platform];
  if (!scenarioOnPlatform(scenario, platform)) {
    return {
      platform,
      label,
      frame,
      theme,
      state: "excluded",
      note: excludedNote(scenario),
    };
  }
  const entry = (shots[platform] ?? {})[scenario.screenshot];
  if (!entry) {
    return { platform, label, frame, theme, state: "missing", note: "Not captured yet" };
  }
  return {
    platform,
    label,
    frame,
    theme,
    state: "captured",
    src: entry.src,
    mtime: entry.mtime,
    size: entry.size ?? null,
  };
}

// The page model: sections keyed by family and group in registry order, mobile first;
// each scenario carries one slot per family platform.
export function galleryView(scenarios, shots, options = {}) {
  const sections = new Map();
  const ordered = Object.keys(FAMILIES).flatMap((family) =>
    scenarios.filter((scenario) => scenario.family === family),
  );
  for (const scenario of ordered) {
    const familyLabel = FAMILIES[scenario.family].label;
    const group = scenario.group || "Other";
    const key = `${familyLabel} · ${group}`;
    const section = sections.get(key) ?? {
      key,
      family: scenario.family,
      familyLabel,
      group,
      scenarios: [],
    };
    section.scenarios.push({
      id: scenario.id,
      title: scenario.title,
      description: scenario.description,
      group,
      screenshot: scenario.screenshot,
      family: scenario.family,
      slots: platformsOfFamily(scenario.family).map((platform) =>
        slotFor(scenario, platform, shots),
      ),
    });
    sections.set(key, section);
  }
  return {
    git: options.git ?? { revision: "unknown", dirty: false },
    reports: options.reports ?? [],
    sections: [...sections.values()],
  };
}

// Frames are gallery chrome around a shot, never baked into the PNG, so the store
// stays diffable. Each frame names its own CSS class in styles.css.
export function frameHtml(frame, screenHtml) {
  if (frame === "browser") {
    return `<span class="frame frame-browser"><span class="browser-bar"><span class="dot"></span><span class="dot"></span><span class="dot"></span><span class="address"></span></span>${screenHtml}</span>`;
  }
  if (frame === "desktop-window") {
    return `<span class="frame frame-desktop-window"><span class="titlebar"><span class="light close"></span><span class="light minimize"></span><span class="light zoom"></span></span>${screenHtml}</span>`;
  }
  if (frame === "phone-browser") {
    return `<span class="frame frame-phone frame-phone-browser"><span class="browser-bar compact"><span class="address"></span></span>${screenHtml}</span>`;
  }
  if (frame === "pixel" || frame === "galaxy") {
    return `<span class="frame frame-android frame-${frame}"><span class="punch-hole"></span>${screenHtml}</span>`;
  }
  return `<span class="frame frame-phone">${screenHtml}</span>`;
}

export function slotHtml(scenario, slot) {
  const subject = `${scenario.title} on ${slot.label}`;
  const captured = slot.state === "captured";
  const image = captured ? `${slot.src}?v=${slot.mtime}` : "";
  const ratio = slot.size
    ? ` style="--shot-ratio: ${slot.size.width} / ${slot.size.height}"`
    : "";
  const content = captured
    ? `<img src="${escapeHtml(image)}" data-stamp="${slot.mtime}" alt="${escapeHtml(subject)}" loading="lazy">`
    : `<span class="missing">${escapeHtml(slot.note)}</span>`;
  const screen = `<span class="device-screen"${ratio}>${content}</span>`;
  return `
          <div class="shot" data-screenshot="${escapeHtml(scenario.screenshot)}" data-platform="${slot.platform}" data-state="${slot.state}" data-scenario-id="${escapeHtml(scenario.id)}" data-group="${escapeHtml(scenario.group)}" data-title="${escapeHtml(scenario.title)}" data-runner="${PLATFORMS[slot.platform].runner}" data-theme="${slot.theme}">
            <button class="preview"${captured ? ` data-image="${escapeHtml(image)}"` : ""} aria-label="Open ${escapeHtml(subject)}">${frameHtml(slot.frame, screen)}</button>
            <div class="shot-meta">
              <span class="platform-tag">${escapeHtml(slot.label)}</span>
              <button class="copy-ref" type="button" aria-label="Copy reference for ${escapeHtml(subject)}">Copy ref</button>
            </div>
          </div>`;
}

// A card shows one theme at a time: the light slots by default, the dark ones
// when the gallery's Dark toggle is on. Columns count one theme's slots.
export function cardHtml(scenario) {
  const themes = [...new Set(scenario.slots.map((slot) => slot.theme))];
  const perTheme = scenario.slots.filter((slot) => slot.theme === themes[0]).length;
  const columns = Math.min(perTheme, CARD_COLUMNS);
  return `
        <article class="card" data-themes="${themes.join(" ")}">
          <div class="shots" style="--shots: ${columns}">${scenario.slots
            .map((slot) => slotHtml(scenario, slot))
            .join("")}</div>
          <div class="card-copy">
            <div class="card-head">
              <h3>${escapeHtml(scenario.title)}</h3>
              <button class="copy-card" type="button" aria-label="Copy reference for ${escapeHtml(scenario.title)}">Copy ref</button>
            </div>
            <p>${escapeHtml(scenario.description)}</p>
          </div>
        </article>`;
}

export function sectionId(index) {
  return `scenario-section-${index}`;
}

export function sectionHtml(section, index) {
  const id = sectionId(index);
  const count = section.scenarios.length;
  return `
    <details class="scenario-section" id="${id}" open data-section-group="${escapeHtml(section.key)}" data-family="${section.family}" aria-labelledby="${id}-title">
      <summary class="section-header">
        <h2 class="section-title" id="${id}-title">${escapeHtml(section.key)}</h2>
        <span class="section-count">${count} ${count === 1 ? "screen" : "screens"}</span>
        <span class="section-chevron" aria-hidden="true"></span>
      </summary>
      <div class="grid">${section.scenarios.map(cardHtml).join("")}</div>
    </details>`;
}

// The side navigation: one macro entry per family, its sections beneath, each
// linking to the section it names.
export function sideNavHtml(view) {
  const families = new Map();
  view.sections.forEach((section, index) => {
    const entries = families.get(section.family) ?? { label: section.familyLabel, sections: [] };
    entries.sections.push({ ...section, id: sectionId(index) });
    families.set(section.family, entries);
  });
  return [...families.entries()]
    .map(
      ([family, entries]) => `
      <div class="side-family" data-family="${family}">
        <a class="side-family-title" href="#${entries.sections[0].id}">${escapeHtml(entries.label)}</a>${entries.sections
          .map(
            (section) => `
        <a class="side-link" href="#${section.id}" data-section="${section.id}">
          <span>${escapeHtml(section.group)}</span>
          <span class="side-count">${section.scenarios.length}</span>
        </a>`,
          )
          .join("")}
      </div>`,
    )
    .join("");
}

export function scanRowsHtml() {
  const cells = Object.entries(RUNNERS)
    .map(
      ([runner, definition]) => `
      <div class="scan-row" data-runner="${runner}">
        <span class="scan-runner">${escapeHtml(definition.label)}</span>
        <span class="scan-progress"></span>
        <button class="scan-button" type="button">Scan</button>
        <span class="scan-last">never</span>
      </div>`,
    )
    .join("");
  return `<div class="scan-grid">${cells}
    </div>`;
}

export async function composeGallery() {
  const registries = await loadAllRegistries();
  const scenarios = Object.values(registries).flatMap(
    (registry) => registry.scenarios,
  );
  const shots = await shotEntries();
  await Promise.all(
    Object.values(shots)
      .flatMap((platformShots) => Object.values(platformShots))
      .map(async (entry) => {
        entry.size = await pngSize(path.join(storeDirectory, entry.src)).catch(
          () => null,
        );
      }),
  );
  const reports = Object.entries(RUNNERS)
    .filter(([, definition]) =>
      existsSync(path.join(definition.reportDirectory, definition.reportFile)),
    )
    .map(([runner, definition]) => ({
      label: `${definition.label} report`,
      href: `reports/${runner}/${definition.reportFile}`,
    }));
  return galleryView(scenarios, shots, { git: await gitMetadata(), reports });
}
