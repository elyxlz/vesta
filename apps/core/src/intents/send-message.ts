import type { InputMethod } from "../protocol/events"
import { ApiError, type HttpClient } from "../transport/http"

// Every send carries a client-generated id. It threads through the app-chat SERVICE into the
// UserEvent and returns on the append, making optimistic-echo dedup exact and HTTP retries
// idempotent. The id generator is injected (crypto.randomUUID in production) for testability.
export type IdGenerator = () => string

export interface SendMessageBody {
  text: string
  input_method?: InputMethod
}

// The send POST's disposition once it settles. `null` means accepted (queued-on-tap; delivery truth
// is the append echo, which clears the bubble). A daemon-down signal (502/503/504 from the proxy, or
// a network/timeout failure with no HTTP status) leaves the bubble retryable; any other error fails
// it. A retry re-posts the SAME id (idempotent, deduped on the echo).
export type SendFailure = "retry" | "failed"

export interface SentMessage {
  id: string
  outcome: Promise<SendFailure | null>
}

// POST a send-message intent under a fresh id and own the retryable/failed mapping both clients need.
// Returns the id (for the optimistic bubble and an idempotent retry: pass `() => id` as `newId`) and
// the outcome promise the caller reflects into the bubble's send_state.
export function sendMessage(
  http: HttpClient,
  agent: string,
  body: SendMessageBody,
  newId: IdGenerator,
): SentMessage {
  const id = newId()
  const outcome = http
    .json(`/agents/${encodeURIComponent(agent)}/app-chat/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: body.text, input_method: body.input_method, intent_id: id }),
    })
    .then((): SendFailure | null => null)
    .catch((error: unknown): SendFailure =>
      error instanceof ApiError
        ? error.status === 502 || error.status === 503 || error.status === 504
          ? "retry"
          : "failed"
        : "retry",
    )
  return { id, outcome }
}
