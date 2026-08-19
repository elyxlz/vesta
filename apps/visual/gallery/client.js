const dialog = document.querySelector("#lightbox");
const dialogImage = dialog.querySelector("img");
document.querySelectorAll(".preview").forEach((button) => {
  button.addEventListener("click", () => {
    const image = button.querySelector("img");
    if (!image || !button.dataset.image) return;
    dialogImage.src = button.dataset.image;
    dialogImage.alt = image.alt;
    dialog.showModal();
  });
});
async function writeClipboard(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    // Fall through to the textarea path below.
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let copied;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  }
  area.remove();
  return copied;
}
function refHeader(shot) {
  return [
    "group: " + shot.dataset.group + " | title: " + shot.dataset.title,
    "rev: " + document.body.dataset.revision,
  ];
}
function shotImage(shot) {
  return shot.querySelector(".preview").dataset.image || "not captured";
}
async function copyWithFeedback(copyButton, lines) {
  const label = copyButton.textContent;
  const copied = await writeClipboard(lines.join("\n"));
  copyButton.textContent = copied ? "Copied" : "Copy failed";
  window.setTimeout(() => {
    copyButton.textContent = label;
  }, 1200);
}
document.querySelectorAll(".copy-ref").forEach((copyButton) => {
  copyButton.addEventListener("click", () => {
    const shot = copyButton.closest(".shot");
    void copyWithFeedback(copyButton, [
      "visual-ref: " +
        shot.dataset.scenarioId +
        " [" +
        shot.dataset.platform +
        "]",
      ...refHeader(shot),
      "image: " + shotImage(shot),
    ]);
  });
});
document.querySelectorAll(".copy-card").forEach((copyButton) => {
  copyButton.addEventListener("click", () => {
    const shots = [...copyButton.closest(".card").querySelectorAll(".shot")];
    void copyWithFeedback(copyButton, [
      "visual-ref: " + shots[0].dataset.scenarioId,
      ...refHeader(shots[0]),
      ...shots.map((shot) => shot.dataset.platform + ": " + shotImage(shot)),
    ]);
  });
});
dialog.querySelector("button").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
const collapsedGroups = new Set(
  JSON.parse(localStorage.getItem("visual-collapsed") || "[]"),
);
document.querySelectorAll(".scenario-section").forEach((section) => {
  const group = section.dataset.sectionGroup;
  section.open = !collapsedGroups.has(group);
  section.addEventListener("toggle", () => {
    if (section.open) collapsedGroups.delete(group);
    else collapsedGroups.add(group);
    localStorage.setItem(
      "visual-collapsed",
      JSON.stringify([...collapsedGroups]),
    );
  });
});
// A side link opens its section (a collapsed one would not scroll into view)
// and the section in view marks its link.
document.querySelectorAll(".side-link, .side-family-title").forEach((link) => {
  link.addEventListener("click", () => {
    const target = document.querySelector(link.getAttribute("href"));
    if (target && !target.open) target.open = true;
  });
});
const sideLinks = new Map(
  [...document.querySelectorAll(".side-link")].map((link) => [
    link.dataset.section,
    link,
  ]),
);
const visibleSections = new Set();
function markActiveSection() {
  let first = null;
  document.querySelectorAll(".scenario-section").forEach((section) => {
    if (!first && visibleSections.has(section.id)) first = section.id;
  });
  sideLinks.forEach((link, id) =>
    link.classList.toggle("active", id === first),
  );
}
const sectionObserver = new IntersectionObserver(
  (entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) visibleSections.add(entry.target.id);
      else visibleSections.delete(entry.target.id);
    });
    markActiveSection();
  },
  { rootMargin: "-10px 0px -60% 0px" },
);
document
  .querySelectorAll(".scenario-section")
  .forEach((section) => sectionObserver.observe(section));
const themeToggle = document.querySelector("#theme-toggle");
function applyTheme(dark) {
  document.body.dataset.theme = dark ? "dark" : "light";
  themeToggle.setAttribute("aria-pressed", dark ? "true" : "false");
}
applyTheme(localStorage.getItem("visual-theme") === "dark");
themeToggle.addEventListener("click", () => {
  const dark = document.body.dataset.theme !== "dark";
  localStorage.setItem("visual-theme", dark ? "dark" : "light");
  applyTheme(dark);
});
const gentleToggle = document.querySelector("#gentle-toggle");
gentleToggle.checked = localStorage.getItem("visual-gentle") !== "0";
gentleToggle.addEventListener("change", () => {
  localStorage.setItem("visual-gentle", gentleToggle.checked ? "1" : "0");
});
// One Scan button: the plan dialog asks every runner what a scan would retake
// and starts the chosen runners from there.
const planDialog = document.querySelector("#plan-dialog");
const planRunners = document.querySelector("#plan-runners");
const planNote = document.querySelector("#plan-note");
const planAll = document.querySelector("#plan-all");
const planStart = document.querySelector("#plan-start");
const runnerLabels = {};
document.querySelectorAll(".scan-row").forEach((row) => {
  runnerLabels[row.dataset.runner] =
    row.querySelector(".scan-runner").textContent;
});
let planRequest = 0;

// Why a unit is stale, in one short line: the files that moved (a few named,
// the rest counted), shots never taken, a changed scenario, or a record from
// before per-file hashes.
function reasonLine(reasons) {
  if (!reasons) return "";
  const parts = [];
  const moved = reasons.changed.concat(
    reasons.added.map((f) => "+" + f),
    reasons.removed.map((f) => "-" + f),
  );
  if (moved.length) {
    const shown = moved
      .slice(0, 3)
      .map((f) => f.replace(/^(mobile|web|core)\/src\//, ""));
    parts.push(
      "changed: " +
        shown.join(", ") +
        (moved.length > 3 ? " +" + (moved.length - 3) + " more" : ""),
    );
  }
  if (reasons.extras) parts.push("scenario changed");
  if (reasons.missing && reasons.missing.length)
    parts.push(
      reasons.missing.length === 1 && moved.length === 0 && !reasons.extras
        ? "never taken"
        : reasons.missing.length + " never taken",
    );
  if (reasons.unknown) parts.push("record predates file hashes");
  return parts.length
    ? '<div class="plan-reason">' + escapeText(parts.join(" · ")) + "</div>"
    : "";
}

function unitLine(unit) {
  const where =
    unit.platforms && unit.platforms.length
      ? " · " + unit.platforms.join(", ")
      : "";
  const shots =
    unit.shots.length === 1 && unit.shots[0] === unit.name + ".png"
      ? ""
      : " " +
        unit.shots.length +
        " shot" +
        (unit.shots.length === 1 ? "" : "s");
  return (
    "<li>" +
    escapeText(unit.name) +
    '<span class="plan-shots">' +
    escapeText(shots + where) +
    "</span>" +
    reasonLine(unit.reasons) +
    "</li>"
  );
}

function escapeText(text) {
  return String(text).replace(
    /[&<>"]/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c],
  );
}

function renderPlans(plans) {
  planRunners.innerHTML = Object.entries(plans)
    .map(([runner, plan]) => {
      const stale = plan.units.filter((unit) => unit.stale);
      const running =
        document.querySelector('.scan-row[data-runner="' + runner + '"]')
          .dataset.state === "running";
      const checked = stale.length > 0 && !running ? "checked" : "";
      const disabled = running || stale.length === 0 ? "disabled" : "";
      const count = plan.error
        ? "plan failed"
        : running
          ? "scanning now"
          : stale.length === 0
            ? "up to date"
            : stale.length + " of " + plan.units.length + " to retake";
      const list = stale.length
        ? "<details><summary>" +
          stale.length +
          " stale</summary><ul>" +
          stale.map(unitLine).join("") +
          "</ul></details>"
        : "";
      const error = plan.error
        ? '<div class="plan-error">' + escapeText(plan.error) + "</div>"
        : "";
      return (
        '<div class="plan-runner" data-runner="' +
        runner +
        '" data-stale="' +
        stale.length +
        '">' +
        '<label><input type="checkbox" ' +
        checked +
        " " +
        disabled +
        '><span class="plan-label">' +
        escapeText(runnerLabels[runner] || runner) +
        '</span><span class="plan-count">' +
        count +
        "</span></label>" +
        error +
        list +
        "</div>"
      );
    })
    .join("");
  planStart.disabled = !planRunners.querySelector("input:checked");
  planRunners.querySelectorAll("input").forEach((input) => {
    input.addEventListener("change", () => {
      planStart.disabled = !planRunners.querySelector("input:checked");
    });
  });
}

// One placeholder row per runner while the plan is computed, so the dialog
// keeps its shape and shows which platforms are being asked.
function renderPlanSkeleton() {
  planRunners.innerHTML = Object.entries(runnerLabels)
    .map(
      ([runner, label]) =>
        '<div class="plan-runner plan-skeleton" data-runner="' +
        runner +
        '" aria-busy="true">' +
        '<label><span class="plan-skeleton-box"></span><span class="plan-label">' +
        escapeText(label) +
        '</span><span class="plan-count plan-skeleton-bar"></span></label>' +
        "</div>",
    )
    .join("");
}

async function loadPlan() {
  const request = ++planRequest;
  planStart.disabled = true;
  renderPlanSkeleton();
  planNote.textContent = planAll.checked
    ? "Everything will be retaken."
    : "Checking what changed…";
  try {
    const response = await fetch(
      "plan.json?all=" + (planAll.checked ? "1" : "0"),
    );
    const payload = await response.json();
    if (request !== planRequest) return;
    renderPlans(payload.plans || {});
    const total = Object.values(payload.plans || {}).reduce(
      (sum, plan) => sum + plan.units.filter((unit) => unit.stale).length,
      0,
    );
    planNote.textContent = planAll.checked
      ? "Every shot on the checked platforms will be retaken."
      : total === 0
        ? "Every shot is up to date."
        : "Only the stale shots are retaken; the rest keep their current capture.";
  } catch (error) {
    if (request !== planRequest) return;
    planNote.textContent = "Could not plan: " + error.message;
  }
}

document.querySelector("#scan-open").addEventListener("click", () => {
  planDialog.showModal();
  loadPlan();
});
planAll.addEventListener("change", loadPlan);
document
  .querySelector("#plan-cancel")
  .addEventListener("click", () => planDialog.close());
planDialog.addEventListener("click", (event) => {
  if (event.target === planDialog) planDialog.close();
});
planStart.addEventListener("click", async () => {
  const runners = [...planRunners.querySelectorAll(".plan-runner")]
    .filter((row) => row.querySelector("input").checked)
    .map((row) => row.dataset.runner);
  planStart.disabled = true;
  const gentle = gentleToggle.checked ? "1" : "0";
  const all = planAll.checked ? "1" : "0";
  await Promise.all(
    runners.map((runner) =>
      fetch("capture/" + runner + "?gentle=" + gentle + "&all=" + all, {
        method: "POST",
      }).catch(() => undefined),
    ),
  );
  planDialog.close();
});
function applyShots(payload) {
  document.querySelectorAll(".shot[data-screenshot]").forEach((shot) => {
    if (shot.dataset.state === "excluded") return;
    const entry = (payload[shot.dataset.platform] ?? {})[
      shot.dataset.screenshot
    ];
    if (!entry) return;
    const button = shot.querySelector(".preview");
    const screen = shot.querySelector(".device-screen");
    let image = screen.querySelector("img");
    if (!image) {
      screen.textContent = "";
      image = document.createElement("img");
      image.alt = shot.dataset.screenshot;
      screen.appendChild(image);
      shot.dataset.state = "captured";
    }
    const stamp = String(entry.mtime);
    if (image.dataset.stamp !== stamp) {
      const src = entry.src + "?v=" + stamp;
      image.src = src;
      image.dataset.stamp = stamp;
      button.dataset.image = src;
    }
  });
}
function capturingStatus(statuses, runner) {
  return statuses.find(
    (entry) =>
      entry.state === "capturing" && entry.runner === runner && entry.startedAt,
  );
}
function errorStatus(statuses, runner) {
  return statuses.find(
    (entry) => entry.state === "error" && entry.runner === runner,
  );
}
function stampText(mtimes) {
  return mtimes.length
    ? new Date(Math.max.apply(null, mtimes)).toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      })
    : "never";
}
// Each cell carries its runner's phase while it captures, its error after a
// failure, and the last-scan stamp otherwise.
function updateScanRows(payload, statuses) {
  document.querySelectorAll(".scan-row").forEach((row) => {
    const runner = row.dataset.runner;
    const run = (payload.runs || {})[runner];
    const status = capturingStatus(statuses, runner);
    const running = Boolean(run && run.running) || Boolean(status);
    const slots = document.querySelectorAll(
      '.shot[data-runner="' + runner + '"]:not([data-state="excluded"])',
    );
    // While a scan runs, count this run's replacements from zero; idle, count files on disk.
    const startedMs = running
      ? Date.parse((run && run.startedAt) || (status && status.startedAt) || "")
      : 0;
    let have = 0;
    const mtimes = [];
    slots.forEach((slot) => {
      const entry = (payload[slot.dataset.platform] || {})[
        slot.dataset.screenshot
      ];
      if (!entry) return;
      mtimes.push(entry.mtime);
      if (!running || entry.mtime >= startedMs) have += 1;
    });
    row.querySelector(".scan-progress").textContent = have + "/" + slots.length;
    const failure =
      !running &&
      (errorStatus(statuses, runner) ||
        (run && run.exitCode
          ? { message: "failed", detail: "see capture-" + runner + ".log" }
          : null));
    row.dataset.state = running ? "running" : failure ? "failed" : "ok";
    const last = row.querySelector(".scan-last");
    if (running && status) {
      const elapsed = Math.max(
        0,
        Math.round((Date.now() - Date.parse(status.startedAt)) / 1000),
      );
      last.textContent =
        (status.message || "Capturing") + " · " + elapsed + "s";
      last.title = status.detail || "";
    } else if (failure) {
      last.textContent =
        failure.message + (failure.detail ? ": " + failure.detail : "");
      last.title = failure.detail || "";
    } else {
      last.textContent = stampText(mtimes);
      last.title = "";
    }
  });
}
function markRefreshing(statuses, payload) {
  document.querySelectorAll(".shot").forEach((shot) => {
    const status = capturingStatus(statuses, shot.dataset.runner);
    if (!status || shot.dataset.state === "excluded") {
      shot.classList.remove("refreshing");
      return;
    }
    const startedMs = Date.parse(status.startedAt);
    const entry = (payload[shot.dataset.platform] || {})[
      shot.dataset.screenshot
    ];
    shot.classList.toggle("refreshing", !(entry && entry.mtime >= startedMs));
  });
}
let lastStatuses = [];
window.setInterval(async () => {
  if (document.visibilityState === "hidden") return;
  try {
    const [statusResponse, shotsResponse] = await Promise.all([
      fetch("status.json", { cache: "no-store" }),
      fetch("shots.json", { cache: "no-store" }),
    ]);
    if (statusResponse.ok) {
      lastStatuses = (await statusResponse.json()).statuses || [];
    }
    if (shotsResponse.ok) {
      const payload = await shotsResponse.json();
      applyShots(payload);
      updateScanRows(payload, lastStatuses);
      markRefreshing(lastStatuses, payload);
    }
  } catch {
    // The local server may be between restarts.
  }
}, 500);
