import { describe, expect, it } from "vitest";
import {
  initialChatState,
  markSend,
  type ChatAttachment,
  type ChatState,
  type HttpClient,
} from "@vesta/core";
import { createChatSender } from "./chat-send-model";

interface SentBody {
  text?: string;
  input_method?: string;
  attachments?: string[];
  intent_id: string;
}

function harness() {
  const requests: SentBody[] = [];
  let reject = false;
  const http: HttpClient = {
    request: () => Promise.reject(new Error("unused")),
    json: <T>(_path: string, init?: RequestInit) => {
      requests.push(JSON.parse(String(init?.body)) as SentBody);
      return reject
        ? Promise.reject(new Error("network down"))
        : Promise.resolve({} as T);
    },
  };
  let state: ChatState = initialChatState();
  let nextId = 0;
  const commit = (fold: (current: ChatState) => ChatState) => {
    state = fold(state);
  };
  const sender = createChatSender({
    http,
    agent: "apollo",
    commit,
    current: () => state,
    makeId: () => {
      nextId += 1;
      return `intent-${String(nextId)}`;
    },
  });
  return {
    sender,
    requests,
    commit,
    state: () => state,
    setReject: (value: boolean) => {
      reject = value;
    },
  };
}

async function flush() {
  for (let i = 0; i < 10; i += 1) await Promise.resolve();
}

function lastBubble(state: ChatState) {
  const message = state.messages.at(-1);
  if (message?.type !== "user") throw new Error("expected a user bubble");
  return message;
}

const ATTACHMENTS: ChatAttachment[] = [
  { id: "att1", name: "pic.jpg", mime: "image/jpeg", size: 1234 },
  { id: "att2", name: "doc.pdf", mime: "application/pdf", size: 99 },
];

describe("chat send model", () => {
  it("posts finalized attachment ids and gives the optimistic bubble the metadata", () => {
    const { sender, requests, state } = harness();
    sender.send("here you go", "typed", ATTACHMENTS);

    expect(requests[0]).toMatchObject({
      text: "here you go",
      intent_id: "intent-1",
      attachments: ["att1", "att2"],
    });
    expect(state().messages.at(-1)).toMatchObject({
      type: "user",
      text: "here you go",
      send_state: "sending",
      attachments: ATTACHMENTS,
    });
  });

  it("omits the attachments field entirely on a plain text send", () => {
    const { sender, requests } = harness();
    sender.send("hi");
    expect(requests[0]).not.toHaveProperty("attachments");
  });

  it("reposts a parked retry-state bubble under its original intent id", async () => {
    const { sender, requests, state, setReject } = harness();
    setReject(true);
    sender.send("spotty", "typed", ATTACHMENTS);
    await flush();
    expect(lastBubble(state()).send_state).toBe("retry");

    setReject(false);
    sender.repostParked();
    expect(requests).toHaveLength(2);
    expect(requests[1]).toMatchObject({
      intent_id: "intent-1",
      attachments: ["att1", "att2"],
    });
    expect(lastBubble(state()).send_state).toBe("sending");
  });

  it("reposts nothing when bubbles are in flight or already echoed", async () => {
    const { sender, requests, commit, state } = harness();
    sender.send("landing");
    await flush();
    // Still awaiting its echo: in flight, not parked.
    expect(lastBubble(state()).send_state).toBe("sending");
    sender.repostParked();
    expect(requests).toHaveLength(1);

    // The echo confirmed it: cleared, still not parked.
    commit((current) => markSend(current, "intent-1", undefined));
    sender.repostParked();
    expect(requests).toHaveLength(1);
  });
});
