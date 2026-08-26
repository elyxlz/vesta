import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render } from "@testing-library/react";
import { useEffect } from "react";
import type { AgentRow, LogEvent } from "@/lib/types";
import { streamLogs, stopLogs } from "@/api";
import { SelectedAgentProvider } from "@/providers/SelectedAgentProvider";
import { AgentLogStreamProvider, useAgentLogSession } from "./index";

vi.mock("@/api", () => ({
  streamLogs: vi.fn(() => new Promise<void>(() => undefined)),
  stopLogs: vi.fn(() => Promise.resolve()),
  startAgent: vi.fn(() => Promise.resolve()),
  stopAgent: vi.fn(() => Promise.resolve()),
  restartAgent: vi.fn(() => Promise.resolve()),
  createBackup: vi.fn(() => Promise.resolve()),
  listBackups: vi.fn(() => Promise.resolve([])),
  restoreBackup: vi.fn(() => Promise.resolve()),
  deleteBackup: vi.fn(() => Promise.resolve()),
  deleteAgent: vi.fn(() => Promise.resolve()),
}));

const streamLogsMock = vi.mocked(streamLogs);
const stopLogsMock = vi.mocked(stopLogs);

function agentInfo(name: string, status: AgentRow["status"]): AgentRow {
  return {
    name,
    status,
    activityState: "idle",
    buildPhase: null,
    operation: null,
    startedAt: null,
    services: {},
  };
}

function Probe() {
  const session = useAgentLogSession();
  useEffect(() => {
    session.start();
  }, [session]);
  return null;
}

function tree(agent: AgentRow, probe: boolean) {
  return (
    <SelectedAgentProvider agent={agent}>
      <AgentLogStreamProvider>
        {probe ? <Probe /> : null}
      </AgentLogStreamProvider>
    </SelectedAgentProvider>
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("AgentLogStreamProvider", () => {
  // Warmed at the layout, so navigating to the log view renders an already-filled buffer
  // instead of paying the connect + tail cost at click time.
  it("warms the stream on mount while the container is up, with no consumer", () => {
    render(tree(agentInfo("ada", "alive"), false));
    expect(streamLogsMock).toHaveBeenCalledTimes(1);
  });

  // A stopped agent's backlog is a one-shot dump that reads the whole log file server-side,
  // so it streams only when a viewer actually asks.
  it("opens no stream for a stopped agent until a consumer starts the session", () => {
    const { rerender } = render(tree(agentInfo("ada", "stopped"), false));
    expect(streamLogsMock).not.toHaveBeenCalled();
    rerender(tree(agentInfo("ada", "stopped"), true));
    expect(streamLogsMock).toHaveBeenCalledTimes(1);
  });

  it("keeps the stream open after the consumer unmounts", () => {
    const { rerender } = render(tree(agentInfo("ada", "alive"), true));
    expect(streamLogsMock).toHaveBeenCalledTimes(1);
    rerender(tree(agentInfo("ada", "alive"), false));
    expect(stopLogsMock).not.toHaveBeenCalled();
  });

  it("two consumers share one stream", () => {
    render(
      <SelectedAgentProvider agent={agentInfo("ada", "alive")}>
        <AgentLogStreamProvider>
          <Probe />
          <Probe />
        </AgentLogStreamProvider>
      </SelectedAgentProvider>,
    );
    expect(streamLogsMock).toHaveBeenCalledTimes(1);
  });

  it("unmounting the provider stops the stream", () => {
    const { unmount } = render(tree(agentInfo("ada", "alive"), true));
    unmount();
    expect(stopLogsMock).toHaveBeenCalledWith("ada");
  });

  it("switching agents disposes the old session and streams the new agent", () => {
    const { rerender } = render(tree(agentInfo("ada", "alive"), true));
    rerender(tree(agentInfo("bob", "alive"), true));
    expect(stopLogsMock).toHaveBeenCalledWith("ada");
    expect(streamLogsMock).toHaveBeenLastCalledWith(
      "bob",
      expect.any(Function),
      expect.anything(),
    );
  });

  it("feeds status changes so a restarted agent resumes streaming", () => {
    const { rerender } = render(tree(agentInfo("ada", "alive"), true));
    const onEvent = streamLogsMock.mock.calls[0]?.[1];
    if (!onEvent) throw new Error("no stream opened");
    act(() => {
      onEvent({ kind: "End" } satisfies LogEvent);
    });
    rerender(tree(agentInfo("ada", "stopped"), true));
    rerender(tree(agentInfo("ada", "alive"), true));
    expect(streamLogsMock).toHaveBeenCalledTimes(2);
  });
});
