import type { NotificationEvent } from "@vesta/core";

// A notification as the view holds it: core's wire shape minus the strict ledger `id`, which the
// live chat stream leaves optional (ChatMessage) and notification display never reads.
export type NotificationView = Omit<NotificationEvent, "id"> & { id?: number };

export interface NotificationContent {
  headline: string;
  body: string | null;
  context: string | null;
}

interface ParsedChannel {
  attributes: Record<string, string>;
  body: string;
}

const TITLE_FIELDS = ["subject", "title"] as const;
const SECONDARY_FIELDS = ["preview", "reason", "description"] as const;
const CONTEXT_FIELDS = [
  "channel_name",
  "chat_name",
  "server",
  "account",
  "folder",
  "location",
  "start_time",
  "minutes_until",
  "media_type",
] as const;

function decodeXml(value: string): string {
  const named = value
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&amp;", "&");
  return named.replace(/&#(x[0-9a-f]+|\d+);/gi, (entity, code: string) => {
    const value = code.toLowerCase().startsWith("x")
      ? Number.parseInt(code.slice(1), 16)
      : Number.parseInt(code, 10);
    return Number.isFinite(value) && value <= 0x10ffff
      ? String.fromCodePoint(value)
      : entity;
  });
}

function parseChannel(summary: string): ParsedChannel | null {
  const match = summary
    .trim()
    .match(/^<channel\b([^>]*)>([\s\S]*)<\/channel>$/);
  if (!match) return null;

  const attributes: Record<string, string> = {};
  const attributePattern =
    /([A-Za-z_][\w.-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')/g;
  for (const attribute of match[1]?.matchAll(attributePattern) ?? []) {
    const key = attribute[1];
    if (!key) continue;
    attributes[key] = decodeXml(attribute[2] ?? attribute[3] ?? "");
  }
  return {
    attributes,
    body: decodeXml(match[2] ?? "").trim(),
  };
}

function takeFirst(
  fields: Record<string, string>,
  keys: readonly string[],
): string | null {
  for (const key of keys) {
    const value = fields[key]?.trim();
    if (value) return value;
  }
  return null;
}

function humanize(value: string): string {
  const words = value.replaceAll("_", " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : "Notification";
}

function contextValue(key: string, value: string): string {
  if (key === "start_time") return `Starts ${value}`;
  if (key === "minutes_until") return `${value} min`;
  return value;
}

export function parseNotificationContent(
  event: NotificationView,
): NotificationContent {
  const parsed = parseChannel(event.summary);
  if (!parsed) {
    return {
      headline: event.summary.trim() || humanize(event.notif_type ?? "notification"),
      body: null,
      context: null,
    };
  }

  const fields = { ...parsed.attributes, ...(event.fields ?? {}) };
  const title = takeFirst(fields, TITLE_FIELDS);
  const secondary = parsed.body || takeFirst(fields, SECONDARY_FIELDS);
  const context = CONTEXT_FIELDS.flatMap((key) => {
    const value = fields[key]?.trim();
    return value ? [contextValue(key, value)] : [];
  });
  const headline =
    title ?? secondary ?? humanize(event.notif_type ?? fields.type ?? "notification");

  return {
    headline,
    body: title && secondary && secondary !== title ? secondary : null,
    context: context.length > 0 ? context.join(" · ") : null,
  };
}
