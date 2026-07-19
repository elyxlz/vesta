import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { createReplica } from "@vesta/core";
import { ApiError } from "@vesta/core";
import type { Controller, Delta, Tree, VestaEvent } from "@vesta/core";
import { ControllerContext } from "@/providers/ControllerProvider";
import { useChatPacing } from "@/stores/use-chat-pacing";
import { fetchHistory } from "@/api/agents";
import { useAgentSocketState } from "./use-agent-socket";

vi.mock("@/api/agents", () => ({ fetchHistory: vi.fn() }));

const fetchHistoryMock = vi.mocked(fetchHistory);

const AGENT = "ada";

function tree(): Tree {
  return {
    gateway: {
      version: "0.0.0",
      channel: "stable",
      autoUpdate: true,
      port: 7777,
      lan: { exposed: false, url: null },
      tunnelUrl: null,
      updateAvailable: false,
      latestVersion: null,
      managed: false,
    },
    agents: {
      [AGENT]: {
        info: {
          status: "alive",
          activityState: "idle",
          buildPhase: null,
          startedAt: null,
          services: {},
        },
        notifications: { pending: [] },
      },
    },
  };
}

function makeController() {
  const replica = createReplica();
  replica.applySnapshot(tree());
  const listeners = new Set<(delta: Delta) => void>();
  const json = vi.fn().mockResolvedValue({});
  const watch = vi.fn();
  const controller: Controller = {
    replica,
    http: { request: vi.fn(), json },
    watch,
    unwatch: vi.fn(),
    reauth: vi.fn(),
    subscribeDeltas: (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    getSyncState: () => "open",
    subscribeSyncState: () => () => undefined,
    close: () => undefined,
  };
  const emit = (delta: Delta): void => {
    replica.applyDelta(delta);
    for (const listener of listeners) listener(delta);
  };
  return { controller, json, watch, emit };
}

function wrapper(controller: Controller) {
  return ({ children }: { children: ReactNode }) =>
    createElement(ControllerContext.Provider, { value: controller }, children);
}

function render(controller: Controller) {
  return renderHook(() => useAgentSocketState({ name: AGENT, active: true }), {
    wrapper: wrapper(controller),
  });
}

// Flush the pending microtasks (the async history seed) so the hook settles.
async function flush() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
}

function chat(id: number, text: string): VestaEvent {
  return { type: "chat", text, id, ts: new Date().toISOString() };
}

// The append echo of a send: a wire `user` event that carries `intent_id` (core's event type does
// not model that client-only field, so assert past it as the runtime frame does).
function userEcho(id: number, text: string, intentId: string): VestaEvent {
  return {
    type: "user",
    text,
    id,
    intent_id: intentId,
  } as unknown as VestaEvent;
}

beforeEach(() => {
  fetchHistoryMock.mockReset();
  useChatPacing.setState({ natural: true });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("useAgentSocketState", () => {
  it("watches the active agent and hydrates the newest history page", async () => {
    fetchHistoryMock.mockResolvedValue({
      events: [chat(1, "hello")],
      cursor: null,
    });
    const { controller, watch } = makeController();

    const { result } = render(controller);
    expect(watch.mock.calls).toEqual([[AGENT]]);

    await flush();

    expect(fetchHistoryMock).toHaveBeenCalledWith(AGENT, "app-chat");
    expect(result.current.historyLoaded).toBe(true);
    expect(result.current.messages.map((m) => m.type)).toEqual(["chat"]);
    expect(result.current.connected).toBe(true);
  });

  it("confirms the optimistic bubble by intent_id without duplicating it", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller, json, emit } = makeController();
    const { result } = render(controller);
    await flush();

    act(() => {
      expect(result.current.send("hi")).toBe(true);
    });
    await flush();

    // Delivery truth is the echo, so the bubble is optimistic ("sending") until it returns.
    const users = () =>
      result.current.messages.filter((m) => m.type === "user");
    expect(users()).toHaveLength(1);
    expect(users()[0]).toMatchObject({ text: "hi", send_state: "sending" });

    const call = json.mock.calls[0];
    if (!call) throw new Error("send did not POST");
    const body = JSON.parse((call[1] as { body: string }).body) as {
      intent_id: string;
    };

    act(() => {
      emit({
        type: "append",
        agent: AGENT,
        events: [userEcho(5, "hi", body.intent_id)],
      });
    });
    await flush();

    // Dedup by id, not text: the echo confirms the existing bubble rather than appending a second.
    expect(users()).toHaveLength(1);
    expect(users()[0]?.send_state).toBeUndefined();
  });

  it("paces a live chat append and toggles isTyping", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    vi.useFakeTimers();
    const { controller, emit } = makeController();
    const { result } = render(controller);
    await flush();

    act(() => {
      emit({ type: "append", agent: AGENT, events: [chat(7, "pong")] });
    });

    // Paced: typing indicator on, message withheld until the typing delay elapses.
    expect(result.current.isTyping).toBe(true);
    expect(result.current.messages).toHaveLength(0);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(8000);
    });

    expect(result.current.messages.map((m) => m.type)).toEqual(["chat"]);
    expect(result.current.isTyping).toBe(false);
  });

  it("keeps the bubble and marks it retry when the send POST returns 503", async () => {
    fetchHistoryMock.mockResolvedValue({ events: [], cursor: null });
    const { controller, json } = makeController();
    json.mockRejectedValueOnce(new ApiError(503, "unavailable"));
    const { result } = render(controller);
    await flush();

    act(() => {
      expect(result.current.send("retryable")).toBe(true);
    });
    await flush();

    const users = result.current.messages.filter((m) => m.type === "user");
    expect(users).toHaveLength(1);
    expect(users[0]).toMatchObject({ text: "retryable", send_state: "retry" });
  });

  it("reseeds the tail on resync without duplicating rows by id", async () => {
    useChatPacing.setState({ natural: false });
    fetchHistoryMock.mockResolvedValueOnce({
      events: [chat(1, "a")],
      cursor: null,
    });
    const { controller, emit } = makeController();
    const { result } = render(controller);
    await flush();

    act(() => {
      emit({ type: "append", agent: AGENT, events: [chat(2, "b")] });
    });
    expect(result.current.messages).toHaveLength(2);

    // The refetched newest page carries both rows; the reseed must not duplicate them.
    fetchHistoryMock.mockResolvedValueOnce({
      events: [chat(1, "a"), chat(2, "b")],
      cursor: null,
    });
    act(() => {
      emit({ type: "resync", agent: AGENT });
    });
    await flush();

    expect(result.current.messages.map((m) => m.type)).toEqual([
      "chat",
      "chat",
    ]);

    // A replayed append for an id already in the reseeded tail is deduped away.
    act(() => {
      emit({ type: "append", agent: AGENT, events: [chat(2, "b")] });
    });
    expect(result.current.messages).toHaveLength(2);
  });
});
