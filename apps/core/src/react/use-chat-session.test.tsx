// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, renderHook } from "@testing-library/react";
import { initialChatState, type ChatState } from "../chat/chat-stream-model";
import { useChatSession } from "./use-chat-session";

afterEach(cleanup);

const heldTail: ChatState = {
  ...initialChatState(),
  messages: [{ type: "chat", text: "hi", id: 1 }],
  historyLoaded: true,
};

describe("useChatSession with no session", () => {
  it("renders the held tail between controller epochs instead of an unloaded one", () => {
    const { result } = renderHook(() => useChatSession(null, heldTail));
    expect(result.current.chat).toBe(heldTail);
    expect(result.current.chat.historyLoaded).toBe(true);
    expect(result.current.socket).toBe("closed");
  });

  it("renders an empty unloaded tail when nothing is held", () => {
    const { result } = renderHook(() => useChatSession(null, null));
    expect(result.current.chat.messages).toEqual([]);
    expect(result.current.chat.historyLoaded).toBe(false);
  });
});
