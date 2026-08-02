const watchUrl =
  typeof WATCH_CAPTURE_URL === "string" ? WATCH_CAPTURE_URL : "";
const shardUrls = [
  typeof WATCH_CAPTURE_URL_1 === "string" ? WATCH_CAPTURE_URL_1 : "",
  typeof WATCH_CAPTURE_URL_2 === "string" ? WATCH_CAPTURE_URL_2 : "",
];
const shardIndex = Number(
  typeof MAESTRO_SHARD_INDEX === "undefined" ? 0 : MAESTRO_SHARD_INDEX,
);
const captureUrl = watchUrl || shardUrls[shardIndex] || "";
const action = typeof ACTION === "string" ? ACTION : "";
const screenshot = typeof SCREENSHOT === "string" ? SCREENSHOT : "";

if (captureUrl) {
  const response = http.post(captureUrl, {
    body: JSON.stringify(screenshot ? { screenshot } : { action }),
    headers: { "Content-Type": "application/json" },
  });

  if (!response.ok) {
    throw new Error(
      `Local screenshot bridge returned ${response.status}: ${response.body}`,
    );
  }
}
