import { describe, expect, it } from "vitest";
import type { ChatMessage } from "./chat-stream-model";
import {
  BUBBLE_GROUP_TIME_GAP_MS,
  chatMessageSide,
  senderOf,
  startsNewBubbleGroup,
} from "./bubble-grouping";

function user(ts?: string): ChatMessage {
  return { type: "user", text: "hi", ts };
}

function agent(ts?: string): ChatMessage {
  return { type: "chat", text: "hello", ts };
}

function from(sender: string, ts?: string): ChatMessage {
  return { type: "chat", text: "hello", sender, ts };
}

// The one row a chat surface holds that no member wrote: a notification page row.
function sideless(): ChatMessage {
  return { type: "notification", source: "whatsapp", summary: "2 new" };
}

describe("chatMessageSide", () => {
  it("maps user to the user side and chat to the agent side", () => {
    expect(chatMessageSide(user())).toBe("user");
    expect(chatMessageSide(agent())).toBe("agent");
  });

  it("gives a sideless row no side", () => {
    expect(chatMessageSide(sideless())).toBeNull();
  });
});

describe("senderOf", () => {
  it("reads the named member of a room message", () => {
    expect(senderOf(from("ada"))).toBe("ada");
  });

  it("falls back to the side for a message no room named", () => {
    expect(senderOf(user())).toBe("user");
    expect(senderOf(agent())).toBe("agent");
  });
});

describe("startsNewBubbleGroup", () => {
  const base = "2026-07-15T10:00:00Z";
  const plus = (ms: number) =>
    new Date(new Date(base).getTime() + ms).toISOString();

  it("keeps same-sender messages within the threshold tight", () => {
    expect(
      startsNewBubbleGroup(
        agent(base),
        agent(plus(BUBBLE_GROUP_TIME_GAP_MS - 1)),
      ),
    ).toBe(false);
  });

  it("starts a new group at exactly the threshold", () => {
    expect(
      startsNewBubbleGroup(agent(base), agent(plus(BUBBLE_GROUP_TIME_GAP_MS))),
    ).toBe(true);
  });

  it("starts a new group past the threshold", () => {
    expect(
      startsNewBubbleGroup(
        agent(base),
        agent(plus(BUBBLE_GROUP_TIME_GAP_MS + 1)),
      ),
    ).toBe(true);
  });

  it("starts a new group on a sender change regardless of timing", () => {
    expect(startsNewBubbleGroup(user(base), agent(base))).toBe(true);
  });

  it("starts a new group when a second agent speaks inside the threshold", () => {
    expect(
      startsNewBubbleGroup(
        from("ada", base),
        from("ben", plus(BUBBLE_GROUP_TIME_GAP_MS - 1)),
      ),
    ).toBe(true);
  });

  it("keeps the same agent's messages inside the threshold tight", () => {
    expect(
      startsNewBubbleGroup(
        from("ada", base),
        from("ada", plus(BUBBLE_GROUP_TIME_GAP_MS - 1)),
      ),
    ).toBe(false);
  });

  it("groups two unnamed agent messages, since both read as the same sender", () => {
    expect(
      startsNewBubbleGroup(
        agent(base),
        agent(plus(BUBBLE_GROUP_TIME_GAP_MS - 1)),
      ),
    ).toBe(false);
  });

  it("never starts a group with no previous side-carrying message", () => {
    expect(startsNewBubbleGroup(null, agent(base))).toBe(false);
  });

  it("falls back to tight when a timestamp is absent", () => {
    expect(startsNewBubbleGroup(user(), user())).toBe(false);
    expect(startsNewBubbleGroup(user(base), user())).toBe(false);
  });

  it("falls back to tight when a timestamp is unparseable", () => {
    expect(startsNewBubbleGroup(user(base), user("not-a-date"))).toBe(false);
    expect(startsNewBubbleGroup(user("not-a-date"), user(base))).toBe(false);
  });

  it("never starts a group off a sideless row", () => {
    expect(startsNewBubbleGroup(sideless(), agent(base))).toBe(false);
  });
});
