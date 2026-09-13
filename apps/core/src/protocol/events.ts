import type { ChatAttachment } from "../attachments/attachment-model";

export type InputMethod = "voice" | "typed";

// The rows a chat surface holds: the chat node's stored messages, whose `id` is the node's
// message id, and the agent's own notification rows from `GET /history?channel=notifications`,
// whose `id` is the events.db rowid. Field names mirror each producer's snake_case wire.
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
  | (EventBase & {
      type: "chat";
      text: string;
      attachments?: ChatAttachment[];
      room?: string;
      sender?: string;
    })
  | NotificationEvent;
