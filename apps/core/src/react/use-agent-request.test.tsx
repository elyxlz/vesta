// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";

import { useAgentRequest, useAgentVisualStatus } from "./use-agent-request";
import {
  createAgentRequests,
  IDLE_REQUEST,
} from "../agent-request/agent-request";
import { createReplica } from "../replica/store";
import { createSession } from "../session/session";
import type { Controller } from "../controller/controller";

function fakeController(): Controller {
  return {
    replica: createReplica(),
    requests: createAgentRequests(),
    http: {
      request: () => Promise.reject(new Error("unused")),
      json: () => Promise.reject(new Error("unused")),
    },
    session: createSession({
      fetch: () => Promise.reject(new Error("unused")),
      read: () => null,
      write: () => undefined,
    }),
    subscribeDeltas: () => () => undefined,
    getSyncState: () => "open",
    subscribeSyncState: () => () => undefined,
    reportPresence: () => undefined,
    reportViewing: () => undefined,
    reportDeviceContext: () => undefined,
    getFocused: () => false,
    subscribeFocused: () => () => undefined,
    getViewing: () => null,
    subscribeViewing: () => () => undefined,
    getAnyFocused: () => false,
    subscribeAnyFocused: () => () => undefined,
    close: () => undefined,
  };
}

afterEach(() => {
  cleanup();
});

describe("useAgentRequest", () => {
  it("is idle with no controller and with no agent", () => {
    const { result } = renderHook(() => useAgentRequest(null, "ada"));
    expect(result.current).toBe(IDLE_REQUEST);
    const controller = fakeController();
    const named = renderHook(() => useAgentRequest(controller, null));
    expect(named.result.current).toBe(IDLE_REQUEST);
  });

  it("re-renders as the controller's request for that agent changes", () => {
    const controller = fakeController();
    const { result } = renderHook(() => useAgentRequest(controller, "ada"));
    expect(result.current.request).toBe("idle");
    act(() => {
      controller.requests.set("ada", "starting");
    });
    expect(result.current.request).toBe("starting");
    act(() => {
      controller.requests.set("bob", "deleting");
    });
    expect(result.current.request).toBe("starting");
    act(() => {
      controller.requests.set("ada", "idle", "docker down");
    });
    expect(result.current).toEqual({ request: "idle", error: "docker down" });
  });
});

describe("useAgentVisualStatus", () => {
  it("overlays this client's request on the roster and carries the failure apart from the label", () => {
    const controller = fakeController();
    const agent = { name: "ada", status: "alive" as const, operation: null };
    const { result } = renderHook(() =>
      useAgentVisualStatus(controller, agent, "idle"),
    );
    expect(result.current).toEqual({
      label: "alive",
      orbState: "alive",
      request: "idle",
      error: "",
    });
    act(() => {
      controller.requests.set("ada", "stopping");
    });
    expect(result.current).toMatchObject({
      label: "stopping...",
      orbState: "busy",
      request: "stopping",
    });
    act(() => {
      controller.requests.set("ada", "idle", "docker down");
    });
    expect(result.current).toEqual({
      label: "alive",
      orbState: "alive",
      request: "idle",
      error: "docker down",
    });
  });

  it("reads the roster alone with no controller", () => {
    const { result } = renderHook(() =>
      useAgentVisualStatus(
        null,
        { name: "ada", status: "stopped", operation: null },
        "idle",
      ),
    );
    expect(result.current).toMatchObject({ label: "stopped", orbState: "off" });
  });
});
