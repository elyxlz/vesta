import type { ChatAttachment } from "../attachments/attachment-model";
import type { ChatMessage, HistoryPage } from "../chat/chat-stream-model";
import type { InputMethod } from "./events";
import { record } from "./parse";

type Frame = Record<string, unknown>;
interface Base {
  id?: number;
  ts?: string;
}
type VariantParser = (frame: Frame, base: Base) => ChatMessage | null;

// The chat service's events, as they arrive on the live chat socket and the history page.
// Like the /sync parser, this routes on `type` and checks the fields each variant keys on; a
// frame it cannot classify is dropped, so a renamed daemon field fails loudly in tests rather
// than reaching the view as `undefined`.
export function parseChatEvent(value: unknown): ChatMessage | null {
  const frame = record(value);
  if (frame === null) return null;
  const base = parseBase(frame);
  if (base === null) return null;
  const type = frame.type;
  if (typeof type !== "string") return null;
  const parse = VARIANTS[type];
  return parse === undefined ? null : parse(frame, base);
}

// A history page is parsed at the boundary like a socket frame: each event is checked by
// parseChatEvent and an unrecognized one is dropped, so the fold never sees a shape the view
// cannot render.
export function parseHistoryPage(value: unknown): HistoryPage {
  const page = record(value);
  const events = Array.isArray(page?.events) ? page.events : [];
  const cursor = page?.cursor;
  return {
    events: events.flatMap((event: unknown) => {
      const parsed = parseChatEvent(event);
      return parsed === null ? [] : [parsed];
    }),
    cursor: typeof cursor === "number" ? cursor : null,
  };
}

const VARIANTS: Record<string, VariantParser | undefined> = {
  user: (frame, base) => {
    const text = str(frame.text);
    const attachments = parseAttachments(frame.attachments);
    const inputMethod = parseInputMethod(frame.input_method);
    const intentId = optionalStr(frame.intent_id);
    const addressing = parseAddressing(frame);
    if (text === null || attachments === undefined) return null;
    if (inputMethod === undefined || intentId === undefined) return null;
    if (addressing === null) return null;
    return {
      ...base,
      type: "user",
      text,
      ...(inputMethod === null ? {} : { input_method: inputMethod }),
      ...(attachments === null ? {} : { attachments }),
      ...(intentId === null ? {} : { intent_id: intentId }),
      ...addressing,
    };
  },
  chat: (frame, base) => {
    const text = str(frame.text);
    const attachments = parseAttachments(frame.attachments);
    const addressing = parseAddressing(frame);
    if (text === null || attachments === undefined) return null;
    if (addressing === null) return null;
    return {
      ...base,
      type: "chat",
      text,
      ...(attachments === null ? {} : { attachments }),
      ...addressing,
    };
  },
  assistant: (frame, base) => {
    const text = str(frame.text);
    return text === null ? null : { ...base, type: "assistant", text };
  },
  error: (frame, base) => {
    const text = str(frame.text);
    return text === null ? null : { ...base, type: "error", text };
  },
  thinking: (frame, base) => {
    const text = str(frame.text);
    const signature = str(frame.signature);
    if (text === null || signature === null) return null;
    return { ...base, type: "thinking", text, signature };
  },
  status: (frame, base) => {
    const state = frame.state;
    if (state !== "idle" && state !== "thinking") return null;
    return { ...base, type: "status", state };
  },
  tool_start: (frame, base) => {
    const tool = str(frame.tool);
    const input = str(frame.input);
    const subagent = optionalBool(frame.subagent);
    if (tool === null || input === null || subagent === undefined) return null;
    return {
      ...base,
      type: "tool_start",
      tool,
      input,
      ...(subagent === null ? {} : { subagent }),
    };
  },
  tool_end: (frame, base) => {
    const tool = str(frame.tool);
    const subagent = optionalBool(frame.subagent);
    if (tool === null || subagent === undefined) return null;
    return {
      ...base,
      type: "tool_end",
      tool,
      ...(subagent === null ? {} : { subagent }),
    };
  },
  rate_limited: (frame, base) => {
    const text = str(frame.text);
    const window = optionalStr(frame.window);
    const resetsAt = optionalNum(frame.resets_at);
    if (text === null || window === undefined || resetsAt === undefined)
      return null;
    return { ...base, type: "rate_limited", text, window, resets_at: resetsAt };
  },
  notification: (frame, base) => {
    const source = str(frame.source);
    const summary = str(frame.summary);
    if (source === null || summary === null) return null;
    return {
      ...base,
      type: "notification",
      source,
      summary,
      ...notificationExtras(frame),
    };
  },
  notification_cleared: (frame, base) => {
    const notifId = str(frame.notif_id);
    if (notifId === null) return null;
    return { ...base, type: "notification_cleared", notif_id: notifId };
  },
  subagent_start: (frame, base) => subagentEvent("subagent_start", frame, base),
  subagent_stop: (frame, base) => subagentEvent("subagent_stop", frame, base),
};

// The room a message belongs to and the member who wrote it, stamped by the gateway's chat node
// and absent from a per-agent chat service's rows. A present value of the wrong type drops the
// frame, matching every other optional field here.
function parseAddressing(
  frame: Frame,
): { room?: string; sender?: string } | null {
  const room = optionalStr(frame.room);
  const sender = optionalStr(frame.sender);
  if (room === undefined || sender === undefined) return null;
  return {
    ...(room === null ? {} : { room }),
    ...(sender === null ? {} : { sender }),
  };
}

function subagentEvent(
  type: "subagent_start" | "subagent_stop",
  frame: Frame,
  base: Base,
): ChatMessage | null {
  const agentId = str(frame.agent_id);
  const agentType = str(frame.agent_type);
  if (agentId === null || agentType === null) return null;
  return { ...base, type, agent_id: agentId, agent_type: agentType };
}

// The per-message identity: `id` is absent on an optimistic bubble but a number wherever the
// daemon stamped it, and `ts` is optional on both.
function parseBase(frame: Frame): Base | null {
  const id = optionalNum(frame.id);
  const ts = optionalStr(frame.ts);
  if (id === undefined || ts === undefined) return null;
  return { ...(id === null ? {} : { id }), ...(ts === null ? {} : { ts }) };
}

function notificationExtras(
  frame: Frame,
): Partial<Extract<ChatMessage, { type: "notification" }>> {
  const extras: Partial<Extract<ChatMessage, { type: "notification" }>> = {};
  const notifType = str(frame.notif_type);
  if (notifType !== null) extras.notif_type = notifType;
  const sender = str(frame.sender);
  if (sender !== null) extras.sender = sender;
  const notifId = str(frame.notif_id);
  if (notifId !== null) extras.notif_id = notifId;
  const fields = record(frame.fields);
  if (fields !== null) {
    const entries = Object.entries(fields).flatMap(([key, item]) =>
      typeof item === "string" ? [[key, item] as const] : [],
    );
    extras.fields = Object.fromEntries(entries);
  }
  const decided = frame.decided;
  if (decided === "interrupt" || decided === "snooze" || decided === "trash")
    extras.decided = decided;
  return extras;
}

function str(value: unknown): string | null {
  return typeof value === "string" ? value : null;
}

// Absent or null reads as null; a present value of the wrong type is malformed (`undefined`).
function optionalStr(value: unknown): string | null | undefined {
  if (value == null) return null;
  return typeof value === "string" ? value : undefined;
}

function optionalNum(value: unknown): number | null | undefined {
  if (value == null) return null;
  return typeof value === "number" && Number.isFinite(value)
    ? value
    : undefined;
}

function optionalBool(value: unknown): boolean | null | undefined {
  if (value == null) return null;
  return typeof value === "boolean" ? value : undefined;
}

function parseInputMethod(value: unknown): InputMethod | null | undefined {
  if (value == null) return null;
  return value === "voice" || value === "typed" ? value : undefined;
}

function parseAttachments(value: unknown): ChatAttachment[] | null | undefined {
  if (value == null) return null;
  if (!Array.isArray(value)) return undefined;
  const attachments: ChatAttachment[] = [];
  for (const item of value as unknown[]) {
    const attachment = parseAttachment(item);
    if (attachment === null) return undefined;
    attachments.push(attachment);
  }
  return attachments;
}

function parseAttachment(value: unknown): ChatAttachment | null {
  const item = record(value);
  if (item === null) return null;
  const id = str(item.id);
  const name = str(item.name);
  const mime = str(item.mime);
  const size = optionalNum(item.size);
  if (id === null || name === null || mime === null) return null;
  if (size === null || size === undefined) return null;
  const attachment: ChatAttachment = { id, name, mime, size };
  const width = optionalNum(item.width);
  const height = optionalNum(item.height);
  const duration = optionalNum(item.duration_secs);
  if (width === undefined || height === undefined || duration === undefined)
    return null;
  if (width !== null) attachment.width = width;
  if (height !== null) attachment.height = height;
  if (duration !== null) attachment.duration_secs = duration;
  return attachment;
}
