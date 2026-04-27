// Cloudflare Worker for cloudflare-email skill.
// Triggered on every inbound email matching the routing rules created in setup.
// Forwards a JSON summary of the message to the agent's local service via the
// public vestad tunnel (INBOUND_URL), authenticated by the WORKER_SECRET.

export default {
  async email(message, env, ctx) {
    if (!env.INBOUND_URL || !env.WORKER_SECRET) {
      console.log("cloudflare-email worker: env not configured");
      message.setReject("agent not configured");
      return;
    }

    const headers = {};
    for (const [k, v] of message.headers.entries()) headers[k] = v;

    const raw = await new Response(message.raw).text();
    const { textBody, htmlBody } = parseMime(raw);

    const payload = {
      message_id: message.headers.get("Message-ID") || "",
      from: message.from,
      to: message.to,
      subject: message.headers.get("Subject") || "",
      body_text: textBody,
      body_html: htmlBody,
      headers,
    };

    try {
      const r = await fetch(`${env.INBOUND_URL}/inbound`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-worker-secret": env.WORKER_SECRET,
        },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        const txt = await r.text();
        console.log(`inbound POST failed: ${r.status} ${txt}`);
        // don't reject the email; agent can still see the bounce later
      }
    } catch (err) {
      console.log(`inbound POST error: ${err.message}`);
    }
  },
};

// Minimal MIME parser. Pulls the first text/plain and first text/html parts.
// Good enough for newsletters and basic correspondence; not a full parser.
function parseMime(raw) {
  const parts = raw.split(/\r?\n\r?\n/);
  let textBody = "";
  let htmlBody = "";
  let inText = false;
  let inHtml = false;
  let buf = "";
  for (const line of raw.split(/\r?\n/)) {
    const lower = line.toLowerCase();
    if (lower.startsWith("content-type:")) {
      if (buf) {
        if (inText) textBody = buf;
        else if (inHtml) htmlBody = buf;
      }
      buf = "";
      inText = lower.includes("text/plain");
      inHtml = lower.includes("text/html");
      continue;
    }
    if (inText || inHtml) buf += line + "\n";
  }
  if (buf) {
    if (inText && !textBody) textBody = buf;
    else if (inHtml && !htmlBody) htmlBody = buf;
  }
  return { textBody: textBody.trim(), htmlBody: htmlBody.trim() };
}
