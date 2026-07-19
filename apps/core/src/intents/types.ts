import type { InputMethod } from "../protocol/events"

// Every intent carries a client-generated id. For send-message the id threads
// through the app-chat notification file into the UserEvent and returns on the
// append, making optimistic-echo dedup exact and HTTP retries idempotent. The
// id generator is injected (crypto.randomUUID in production) for testability.
export type IntentId = string

export type IdGenerator = () => IntentId

export interface IntentEnvelope<TKind extends string, TBody> {
  kind: TKind
  id: IntentId
  agent: string
  body: TBody
}

export interface SendMessageBody {
  text: string
  input_method?: InputMethod
}

export type SendMessageIntent = IntentEnvelope<"send_message", SendMessageBody>

export function createSendMessageIntent(
  agent: string,
  body: SendMessageBody,
  newId: IdGenerator,
): SendMessageIntent {
  return { kind: "send_message", id: newId(), agent, body }
}
