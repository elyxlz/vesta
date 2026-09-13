import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";

vi.mock("@/api/client", () => ({
  httpClient: { json: vi.fn(), request: vi.fn() },
}));

vi.mock("@/providers/SelectedAgentProvider/context", () => ({
  useSelectedAgent: () => ({ name: "ada" }),
}));

import type { NotificationEvent } from "@vesta/core";
import { httpClient } from "@/api/client";
import { ControllerContext } from "@/providers/ControllerProvider/context";
import {
  fakeAgentNode,
  fakeController,
  fakeTree,
} from "@/test/fake-controller";
import { NotificationsCard } from "./index";

const AGENT = "ada";
const json = vi.mocked(httpClient.json);

function notification(
  id: number,
  summary: string,
  notifId: string,
): NotificationEvent {
  return {
    id,
    type: "notification",
    source: "email",
    summary,
    notif_id: notifId,
    ts: "2026-09-05T09:00:00Z",
  };
}

const STORED = notification(1, "the invoice was paid", "email-1");
const PENDING = notification(2, "the roof is leaking", "email-2");

function mount(pending: NotificationEvent[]) {
  const fake = fakeController(
    fakeTree({ agents: { [AGENT]: fakeAgentNode({}, pending) } }),
  );
  return render(
    <ControllerContext.Provider value={fake.controller}>
      <NotificationsCard />
    </ControllerContext.Provider>,
  );
}

beforeEach(() => {
  json.mockReset();
  json.mockResolvedValue({ events: [STORED], cursor: null });
});

afterEach(cleanup);

describe("NotificationsCard", () => {
  it("renders the page the history returned", async () => {
    mount([]);
    await waitFor(() => {
      expect(screen.queryByText(STORED.summary)).not.toBeNull();
    });
    expect(screen.queryByText("pending")).toBeNull();
  });

  // The pending set rides the replica as whole events, so one the agent has not written to its
  // history yet still has a row to mark: the card merges it in rather than dropping it.
  it("renders a pending notification the history page does not carry", async () => {
    mount([PENDING]);
    await waitFor(() => {
      expect(screen.queryByText(PENDING.summary)).not.toBeNull();
    });
    expect(screen.queryByText(STORED.summary)).not.toBeNull();
    expect(screen.queryByText("pending")).not.toBeNull();
  });

  // The dedup rules mergePending applies are its own; this is the card marking the row it kept.
  it("marks a row the page carries and the pending set still names", async () => {
    mount([STORED]);
    await waitFor(() => {
      expect(screen.getAllByText(STORED.summary)).toHaveLength(1);
    });
    expect(screen.getAllByText("pending")).toHaveLength(1);
  });
});
