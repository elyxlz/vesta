// Cloudflare Email Routing worker for the cloudflare-email skill.
// Parses inbound mail with postal-mime and forwards a JSON summary to the
// agent's local service via the public vestad tunnel (INBOUND_URL),
// authenticated by the WORKER_SECRET.

import PostalMime from "postal-mime";

export default {
  async email(message, env, ctx) {
    if (!env.INBOUND_URL || !env.WORKER_SECRET) {
      console.log("cloudflare-email worker: env not configured");
      message.setReject("agent not configured");
      return;
    }

    // message.raw is single-use — buffer once, then parse.
    const rawBuffer = await new Response(message.raw).arrayBuffer();
    const parsed = await PostalMime.parse(rawBuffer);

    const headers = Object.fromEntries(message.headers.entries());

    const toList = (parsed.to || [])
      .map((t) => t.address)
      .filter(Boolean)
      .join(", ");

    const payload = {
      message_id: parsed.messageId || message.headers.get("message-id") || "",
      from: parsed.from?.address || message.from,
      to: toList || message.to,
      subject: parsed.subject || message.headers.get("subject") || "",
      body_text: parsed.text || "",
      body_html: parsed.html || "",
      in_reply_to: parsed.inReplyTo || "",
      references: parsed.references || "",
      headers,
    };

    // Throw on failure so Cloudflare Email Routing retries / bounces. If we
    // returned silently after consuming raw, the email would be dropped from
    // the agent's perspective and the sender would get no signal.
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
      throw new Error(`inbound POST failed: ${r.status} ${txt}`);
    }
  },
};
