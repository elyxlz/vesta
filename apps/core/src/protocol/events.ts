import type { ChatAttachment } from "../attachments/attachment-model";

export type InputMethod = "voice" | "typed";

// Every event carries the events.db rowid as `id`; the snapshot is a frame, not
// an event, so it is absent from this union. Field names mirror the agent's
// Python wire verbatim (snake_case), which vestad relays unchanged.
interface EventBase {
  id: number;
  ts?: string;
}

interface NotificationFields {
  type: "notification";
  source: string;
  summary: string;
  notif_type?: string;
  sender?: string;
  fields?: Record<string, string>;
  decided?: "interrupt" | "snooze" | "trash";
  notif_id?: string;
}

export type NotificationEvent = EventBase & NotificationFields;

export type VestaEvent =
  | (EventBase & { type: "status"; state: "idle" | "thinking" })
  | (EventBase & {
      type: "user";
      text: string;
      input_method?: InputMethod;
      attachments?: ChatAttachment[];
      // The client id of the send this row echoes; a client confirms its optimistic bubble on it.
      intent_id?: string;
      // The room this message belongs to and the member who wrote it, stamped on every row the
      // chat node stores and absent from an optimistic bubble.
      room?: string;
      sender?: string;
    })
  | (EventBase & { type: "assistant"; text: string })
  | (EventBase & { type: "thinking"; text: string; signature: string })
  | (EventBase & {
      type: "chat";
      text: string;
      attachments?: ChatAttachment[];
      room?: string;
      sender?: string;
    })
  | NotificationEvent;
