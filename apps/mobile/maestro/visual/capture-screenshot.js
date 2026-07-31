if (WATCH_CAPTURE_URL) {
  const response = http.post(WATCH_CAPTURE_URL, {
    body: JSON.stringify({ screenshot: SCREENSHOT }),
    headers: { "Content-Type": "application/json" },
  });

  if (!response.ok) {
    throw new Error(
      `Local screenshot bridge returned ${response.status}: ${response.body}`,
    );
  }
}
