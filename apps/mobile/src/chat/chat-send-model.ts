import {
  beginSend,
  markSend,
  retryableSends,
  sendMessage,
  type ChatAttachment,
  type ChatState,
  type HttpClient,
  type InputMethod,
  type SendFailure,
} from "@vesta/core";

// The send half of the chat view-model, React-free so it tests as a plain model. Sends are POST
// intents confirmed by their chat-socket echo: a null outcome means queued-on-tap, so only a
// failure marks the bubble. Attachments ride the body as finalized ids while the optimistic
// bubble keeps the full metadata for rendering.
export interface ChatSender {
  send: (
    text: string,
    inputMethod?: InputMethod,
    attachments?: ChatAttachment[],
  ) => void;
  retry: (
    intentId: string,
    text: string,
    inputMethod?: InputMethod,
    attachments?: ChatAttachment[],
  ) => void;
  repostParked: () => void;
}

export function createChatSender(deps: {
  http: HttpClient;
  agent: string;
  commit: (fold: (current: ChatState) => ChatState) => void;
  current: () => ChatState;
  makeId: () => string;
}): ChatSender {
  const applyOutcome = (
    intentId: string,
    outcome: Promise<SendFailure | null>,
  ) => {
    void outcome.then((failure) => {
      if (failure)
        deps.commit((current) => markSend(current, intentId, failure));
    });
  };
  const body = (
    text: string,
    inputMethod: InputMethod,
    attachments?: ChatAttachment[],
  ) => {
    const ids = attachments?.map((attachment) => attachment.id);
    return {
      text,
      input_method: inputMethod,
      attachments: ids && ids.length > 0 ? ids : undefined,
    };
  };

  const retry: ChatSender["retry"] = (
    intentId,
    text,
    inputMethod = "typed",
    attachments,
  ) => {
    deps.commit((current) => markSend(current, intentId, "sending"));
    const { outcome } = sendMessage(
      deps.http,
      deps.agent,
      body(text, inputMethod, attachments),
      () => intentId,
    );
    applyOutcome(intentId, outcome);
  };

  return {
    send: (text, inputMethod = "typed", attachments) => {
      const { id, outcome } = sendMessage(
        deps.http,
        deps.agent,
        body(text, inputMethod, attachments),
        deps.makeId,
      );
      deps.commit((current) =>
        beginSend(current, text, inputMethod, id, attachments),
      );
      applyOutcome(id, outcome);
    },
    retry,
    // On a reconnect, a bubble parked in the retryable state re-posts itself once under its
    // original intent id: the 200 was never seen but dedup makes a double-send impossible, so a
    // flaky link never strands a tap-to-retry the user walked away from.
    repostParked: () => {
      for (const parked of retryableSends(deps.current()))
        retry(
          parked.intentId,
          parked.text,
          parked.inputMethod,
          parked.attachments,
        );
    },
  };
}
