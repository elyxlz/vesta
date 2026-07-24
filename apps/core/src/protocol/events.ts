export type InputMethod = "voice" | "typed"

// Every event carries the events.db rowid as `id`; the snapshot is a frame, not
// an event, so it is absent from this union. Field names mirror the agent's
// Python wire verbatim (snake_case), which vestad relays unchanged.
interface EventBase {
  id: number
  ts?: string
}

interface NotificationFields {
  type: "notification"
  source: string
  summary: string
  notif_type?: string
  sender?: string
  fields?: Record<string, string>
  decided?: "interrupt" | "snooze" | "trash"
  notif_id?: string
}

export type NotificationEvent = EventBase & NotificationFields

export type VestaEvent =
  | (EventBase & { type: "status"; state: "idle" | "thinking" })
  | (EventBase & { type: "user"; text: string; input_method?: InputMethod })
  | (EventBase & { type: "assistant"; text: string })
  | (EventBase & { type: "thinking"; text: string; signature: string })
  | (EventBase & { type: "chat"; text: string })
  | (EventBase & { type: "tool_start"; tool: string; input: string; subagent?: boolean })
  | (EventBase & { type: "tool_end"; tool: string; subagent?: boolean })
  | (EventBase & { type: "error"; text: string })
  | (EventBase & {
      type: "rate_limited"
      text: string
      window: string | null
      resets_at: number | null
    })
  | NotificationEvent
  | (EventBase & { type: "notification_cleared"; notif_id: string })
  | (EventBase & { type: "subagent_start"; agent_id: string; agent_type: string })
  | (EventBase & { type: "subagent_stop"; agent_id: string; agent_type: string })
