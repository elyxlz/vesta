import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const connection = vi.hoisted(() => ({ url: "https://gw-a" }));
vi.mock("@/lib/connection", () => ({
  getConnection: () => connection,
}));

import { chatDrafts, useChatDraft } from "./use-chat-draft";

beforeEach(() => {
  connection.url = "https://gw-a";
  chatDrafts.store.setState({ cells: new Map() });
});
afterEach(cleanup);

describe("useChatDraft", () => {
  it("keeps the draft across an unmount and remount of the agent route", () => {
    const first = renderHook(() => useChatDraft("ada"));
    act(() => {
      first.result.current[1]("half typed");
    });
    first.unmount();

    const second = renderHook(() => useChatDraft("ada"));
    expect(second.result.current[0]).toBe("half typed");
  });

  it("keeps each agent's draft in its own cell across a switch", () => {
    const { result, rerender } = renderHook(
      ({ agent }) => useChatDraft(agent),
      {
        initialProps: { agent: "ada" },
      },
    );
    act(() => {
      result.current[1]("for ada");
    });
    rerender({ agent: "ben" });
    expect(result.current[0]).toBe("");
    rerender({ agent: "ada" });
    expect(result.current[0]).toBe("for ada");
  });

  it("shows one draft to every mounted composer of the same agent", () => {
    const panel = renderHook(() => useChatDraft("ada"));
    const fullscreen = renderHook(() => useChatDraft("ada"));
    act(() => {
      panel.result.current[1]("typed in the panel");
    });
    expect(fullscreen.result.current[0]).toBe("typed in the panel");
    act(() => {
      fullscreen.result.current[1]("");
    });
    expect(panel.result.current[0]).toBe("");
  });

  it("never seeds a draft typed against another gateway", () => {
    const { result, rerender } = renderHook(() => useChatDraft("ada"));
    act(() => {
      result.current[1]("on gateway a");
    });
    connection.url = "https://gw-b";
    rerender();
    expect(result.current[0]).toBe("");
  });
});
