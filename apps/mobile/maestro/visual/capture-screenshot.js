const directUrl = typeof CAPTURE_URL === "string" ? CAPTURE_URL : "";
const shardUrls = [
  typeof CAPTURE_URL_1 === "string" ? CAPTURE_URL_1 : "",
  typeof CAPTURE_URL_2 === "string" ? CAPTURE_URL_2 : "",
];
const shardIndex = Number(
  typeof MAESTRO_SHARD_INDEX === "undefined" ? 0 : MAESTRO_SHARD_INDEX,
);
const captureUrl = directUrl || shardUrls[shardIndex] || "";
const action = typeof ACTION === "string" ? ACTION : "";
const screenshot = typeof SCREENSHOT === "string" ? SCREENSHOT : "";
const pageStep = typeof PAGE_STEP === "string" ? PAGE_STEP : undefined;

if (captureUrl) {
  const response = http.post(captureUrl, {
    body: JSON.stringify(screenshot ? { screenshot, pageStep } : { action }),
    headers: { "Content-Type": "application/json" },
  });

  if (!response.ok) {
    throw new Error(
      `Local screenshot bridge returned ${response.status}: ${response.body}`,
    );
  }
  output.captureMore = response.body
    ? JSON.parse(response.body).more === true
    : false;
} else if (pageStep) {
  throw new Error("Page capture requires the local screenshot bridge");
}
