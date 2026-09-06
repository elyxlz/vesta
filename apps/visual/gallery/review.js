const reviewDialog = document.querySelector("#review-dialog");
const reviewStatus = document.querySelector("#review-status");
const reviewApprove = document.querySelector("#review-approve");
let review = null;
let reviewRequest = 0;
const reviewPart = document.querySelector("#review-part");

function renderReview(result) {
  review = result;
  reviewPart.replaceChildren(
    ...result.parts.map((part, index) => {
      const option = document.createElement("option");
      option.value = String(index);
      option.textContent = `${index + 1} / ${result.parts.length} · ${part.status}`;
      return option;
    }),
  );
  reviewPart.value = String(
    Math.max(
      0,
      result.parts.findIndex((part) => part.status !== "same"),
    ),
  );
  reviewApprove.disabled = !["new", "changed"].includes(result.status);
  renderPart();
}

function renderPart() {
  const result = review.parts[Number(reviewPart.value)];
  const labels = {
    missing: "No current capture. Run a scan first.",
    new: "New screenshot. No approved baseline yet.",
    same: "No changed pixels.",
    changed: `${result.pixels} changed pixels (${((result.ratio ?? 0) * 100).toFixed(3)}%).`,
    resized: "The screenshot dimensions changed.",
    removed:
      "This page section no longer exists. Approval accepts the shorter page.",
  };
  reviewStatus.textContent =
    review.status === "incomplete"
      ? "Page capture is incomplete. Refresh it before approval."
      : labels[result.status];
  for (const kind of ["baseline", "current", "diff"]) {
    const image = document.querySelector(`#review-${kind}`);
    image.hidden = !result[kind];
    if (result[kind]) image.src = result[kind];
    else image.removeAttribute("src");
  }
}
reviewPart.addEventListener("change", renderPart);

function reviewPath(result) {
  return `comparison/${encodeURIComponent(result.platform)}/${encodeURIComponent(result.name)}`;
}

document.querySelectorAll(".review-shot").forEach((button) => {
  button.addEventListener("click", async () => {
    const request = ++reviewRequest;
    const shot = button.closest(".shot");
    review = null;
    reviewApprove.disabled = true;
    reviewDialog.querySelectorAll("img").forEach((image) => {
      image.hidden = true;
    });
    document.querySelector("#review-title").textContent =
      `${shot.dataset.title} · ${shot.dataset.platform}`;
    reviewStatus.textContent = "Comparing pixels…";
    reviewDialog.showModal();
    try {
      const response = await fetch(
        reviewPath({
          platform: shot.dataset.platform,
          name: shot.dataset.screenshot,
        }),
      );
      if (!response.ok) throw new Error(await response.text());
      const result = await response.json();
      if (request === reviewRequest) renderReview(result);
    } catch (error) {
      if (request === reviewRequest) reviewStatus.textContent = error.message;
    }
  });
});

reviewApprove.addEventListener("click", async () => {
  if (!review) return;
  const request = reviewRequest;
  reviewApprove.disabled = true;
  try {
    const response = await fetch(
      `${reviewPath(review)}?hash=${review.currentHash}`,
      { method: "POST" },
    );
    if (!response.ok) throw new Error(await response.text());
    const result = await response.json();
    if (request === reviewRequest) renderReview(result);
  } catch (error) {
    if (request === reviewRequest) reviewStatus.textContent = error.message;
  }
});

document
  .querySelector("#review-close")
  .addEventListener("click", () => reviewDialog.close());
reviewDialog.addEventListener("click", (event) => {
  if (event.target === reviewDialog) reviewDialog.close();
});
reviewDialog.addEventListener("close", () => {
  reviewRequest += 1;
  review = null;
});
