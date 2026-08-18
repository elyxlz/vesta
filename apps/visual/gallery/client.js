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
      "visual-ref: " + shot.dataset.scenarioId +
        " [" + shot.dataset.platform + "]",
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
      ...shots.map(
        (shot) => shot.dataset.platform + ": " + shotImage(shot),
      ),
    ]);
  });
});
dialog.querySelector("button").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
const status = document.querySelector("#capture-status");
const statusTitle = status.querySelector(".status-title");
const statusDetail = status.querySelector(".status-detail");
function showCaptureStatus(nextStatus) {
  const state = nextStatus?.state ?? "ready";
  document.body.dataset.captureState = state;
  status.dataset.state = state;
  status.hidden = state === "ready";
  if (state === "capturing") {
    const elapsed = nextStatus.startedAt
      ? Math.max(0, Math.round((Date.now() - Date.parse(nextStatus.startedAt)) / 1000))
      : 0;
    statusTitle.textContent = nextStatus.message || "Capturing screenshots";
    const context = nextStatus.detail || "Working";
    statusDetail.textContent = context + " · " + elapsed + "s";
  } else if (state === "error") {
    statusTitle.textContent = nextStatus.message || "Screenshot refresh failed";
    statusDetail.textContent = nextStatus.detail || "Fix the issue and save again.";
  }
}
const collapsedGroups = new Set(
  JSON.parse(localStorage.getItem("visual-collapsed") || "[]"),
);
document.querySelectorAll(".scenario-section").forEach((section) => {
  const group = section.dataset.sectionGroup;
  section.open = !collapsedGroups.has(group);
  section.addEventListener("toggle", () => {
    if (section.open) collapsedGroups.delete(group);
    else collapsedGroups.add(group);
    localStorage.setItem("visual-collapsed", JSON.stringify([...collapsedGroups]));
  });
});
const gentleToggle = document.querySelector("#gentle-toggle");
gentleToggle.checked = localStorage.getItem("visual-gentle") !== "0";
gentleToggle.addEventListener("change", () => {
  localStorage.setItem("visual-gentle", gentleToggle.checked ? "1" : "0");
});
document.querySelectorAll(".scan-row .scan-button").forEach((button) => {
  button.addEventListener("click", async () => {
    button.disabled = true;
    const runner = button.closest(".scan-row").dataset.runner;
    const gentle = gentleToggle.checked ? "1" : "0";
    try {
      await fetch("capture/" + runner + "?gentle=" + gentle, {
        method: "POST",
      });
    } catch {
      button.disabled = false;
    }
  });
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
function updateScanRows(payload, status) {
  document.querySelectorAll(".scan-row").forEach((row) => {
    const runner = row.dataset.runner;
    const run = (payload.runs || {})[runner];
    const statusRun = Boolean(
      status &&
        status.state === "capturing" &&
        status.runner === runner &&
        status.startedAt,
    );
    const running = Boolean(run && run.running) || statusRun;
    const button = row.querySelector(".scan-button");
    button.disabled = running;
    button.textContent = running ? "Scanning" : "Scan";
    const slots = document.querySelectorAll(
      '.shot[data-runner="' + runner + '"]:not([data-state="excluded"])',
    );
    // While a scan runs, count this run's replacements from zero; idle, count files on disk.
    const startedMs = running
      ? Date.parse(
          (run && run.startedAt) || (status && status.startedAt) || "",
        )
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
    row.querySelector(".scan-progress").textContent =
      have + "/" + slots.length;
    const failed = Boolean(run && !running && run.exitCode);
    row.dataset.state = failed ? "failed" : "ok";
    row.querySelector(".scan-last").textContent = failed
      ? "last scan failed, see capture-" + runner + ".log"
      : "last scan " +
        (mtimes.length
          ? new Date(Math.max.apply(null, mtimes)).toLocaleString()
          : "never");
  });
}
function markRefreshing(status, payload) {
  const capturing = Boolean(
    status &&
      status.state === "capturing" &&
      status.runner &&
      status.startedAt,
  );
  const startedMs = capturing ? Date.parse(status.startedAt) : 0;
  document.querySelectorAll(".shot").forEach((shot) => {
    const applies =
      capturing &&
      shot.dataset.runner === status.runner &&
      shot.dataset.state !== "excluded";
    if (!applies) {
      shot.classList.remove("refreshing");
      return;
    }
    const entry = (payload[shot.dataset.platform] || {})[
      shot.dataset.screenshot
    ];
    shot.classList.toggle("refreshing", !(entry && entry.mtime >= startedMs));
  });
}
let lastStatus = null;
window.setInterval(async () => {
  if (document.visibilityState === "hidden") return;
  try {
    const [statusResponse, shotsResponse] = await Promise.all([
      fetch("status.json", { cache: "no-store" }),
      fetch("shots.json", { cache: "no-store" }),
    ]);
    if (statusResponse.ok) {
      lastStatus = await statusResponse.json();
      showCaptureStatus(lastStatus);
    }
    if (shotsResponse.ok) {
      const payload = await shotsResponse.json();
      applyShots(payload);
      updateScanRows(payload, lastStatus);
      markRefreshing(lastStatus, payload);
    }
  } catch {
    // The local server may be between restarts.
  }
}, 500);
