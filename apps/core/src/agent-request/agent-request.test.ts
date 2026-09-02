import { describe, expect, it, vi } from "vitest";

import {
  agentVisualStatus,
  createAgentRequests,
  IDLE_REQUEST,
} from "./agent-request";

describe("createAgentRequests", () => {
  it("answers idle for an agent it has never seen", () => {
    expect(createAgentRequests().get("ada")).toBe(IDLE_REQUEST);
  });

  it("drops state for a deleted agent so its deleting orb ends when it leaves the roster", () => {
    const requests = createAgentRequests();
    requests.set("ada", "deleting");
    requests.set("bob", "starting");
    requests.reconcile(["bob"]);
    expect(requests.get("ada")).toBe(IDLE_REQUEST);
    expect(requests.get("bob").request).toBe("starting");
  });

  it("keeps a deleting request while its agent is still present, so the orb stays red", () => {
    const requests = createAgentRequests();
    requests.set("ada", "deleting");
    requests.reconcile(["ada"]);
    expect(requests.get("ada").request).toBe("deleting");
  });

  it("notifies subscribers on every change and not on a no-op", () => {
    const requests = createAgentRequests();
    const listener = vi.fn();
    requests.subscribe(listener);
    requests.set("ada", "starting");
    requests.reconcile(["ada"]);
    requests.clear("ada");
    requests.clear("ada");
    expect(listener).toHaveBeenCalledTimes(2);
  });

  it("ignores a second submit while the first is in flight", async () => {
    const requests = createAgentRequests();
    let finish: () => void = () => undefined;
    const first = requests.run(
      "ada",
      "starting",
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
      "could not start",
    );
    const second = vi.fn(() => Promise.resolve());
    await requests.run("ada", "stopping", second, "could not stop");
    expect(second).not.toHaveBeenCalled();
    expect(requests.get("ada").request).toBe("starting");

    finish();
    await first;
    expect(requests.get("ada")).toBe(IDLE_REQUEST);
  });

  it("lands the failure message and returns to idle when the action throws", async () => {
    const requests = createAgentRequests();
    await requests.run(
      "ada",
      "starting",
      () => Promise.reject(new Error("docker down")),
      "could not start",
    );
    expect(requests.get("ada")).toEqual({
      request: "idle",
      error: "docker down",
    });
  });

  it("uses the fallback when the rejection carries no message", async () => {
    const requests = createAgentRequests();
    await requests.run(
      "ada",
      "backing-up",
      () => Promise.reject(new Error("")),
      "backup failed",
    );
    expect(requests.get("ada").error).toBe("backup failed");
  });

  it("clears a stale failure when the next request starts", async () => {
    const requests = createAgentRequests();
    requests.set("ada", "idle", "docker down");
    await requests.run("ada", "starting", () => Promise.resolve(), "x");
    expect(requests.get("ada")).toBe(IDLE_REQUEST);
  });
});

describe("agentVisualStatus", () => {
  // The backup pauses the container, so the roster reports `stopped` while restic runs. A client
  // that started no request of its own is exactly the case the local store cannot cover, so the
  // roster operation must win over the bare `stopped` status.
  it.each<{
    name: string;
    roster: Parameters<typeof agentVisualStatus>[0];
    request: Parameters<typeof agentVisualStatus>[1];
    label: string;
    orbState: string;
  }>([
    {
      name: "busy updating orb for a server-side rebuilding agent",
      roster: { status: "rebuilding", operation: null },
      request: "idle",
      label: "updating...",
      orbState: "busy",
    },
    {
      name: "attention when the agent needs the user to sign in again",
      roster: { status: "not_authenticated", operation: null },
      request: "idle",
      label: "needs you to sign in",
      orbState: "attention",
    },
    {
      name: "attention when the agent needs the user to set it up",
      roster: { status: "unprovisioned", operation: null },
      request: "idle",
      label: "needs to be set up",
      orbState: "attention",
    },
    {
      name: "a roster operation beats a stopped status",
      roster: { status: "stopped", operation: "backing_up" },
      request: "idle",
      label: "backing up...",
      orbState: "busy",
    },
    {
      name: "this client's own request beats the roster",
      roster: { status: "alive", operation: null },
      request: "stopping",
      label: "stopping...",
      orbState: "busy",
    },
    {
      name: "a sign-in in flight reads as signing in",
      roster: { status: "unprovisioned", operation: null },
      request: "authenticating",
      label: "signing in...",
      orbState: "busy",
    },
    {
      name: "the stopped label stays distinct from waiting-on-user labels",
      roster: { status: "stopped", operation: null },
      request: "idle",
      label: "stopped",
      orbState: "off",
    },
    {
      name: "a local delete shows the deleting orb, not the generic busy one",
      roster: { status: "alive", operation: null },
      request: "deleting",
      label: "deleting...",
      orbState: "deleting",
    },
    {
      name: "no agent and no request is off with no words",
      roster: null,
      request: "idle",
      label: "",
      orbState: "off",
    },
  ])("$name", ({ roster, request, label, orbState }) => {
    expect(agentVisualStatus(roster, request, "idle")).toEqual({
      label,
      orbState,
    });
  });
});
