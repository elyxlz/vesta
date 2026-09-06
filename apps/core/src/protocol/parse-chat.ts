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

// The chat node's events, as they arrive on the live room socket and the history page.
// Like the /sync parser, this routes on `type` and checks the fields each variant keys on; a
// frame it cannot classify is dropped, so a renamed field fails loudly in tests rather than
// reaching the view as `undefined`.
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
};

// The room a message belongs to and the member who wrote it, stamped by the chat node. Both are
// optional here, since an optimistic bubble carries neither. A present value of the wrong type
// drops the frame, matching every other optional field here.
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

// The per-message identity: `id` is absent on an optimistic bubble but a number wherever the
// node stamped it, and `ts` is optional on both.
function parseBase(frame: Frame): Base | null {
  const id = optionalNum(frame.id);
  const ts = optionalStr(frame.ts);
  if (id === undefined || ts === undefined) return null;
  return { ...(id === null ? {} : { id }), ...(ts === null ? {} : { ts }) };
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
