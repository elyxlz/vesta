import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import {
  render,
  screen,
  waitFor,
  cleanup,
  fireEvent,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as api from "@/api/agents";
import { NotificationInterruptRulesCard } from "./index";

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
}));

describe("NotificationInterruptRulesCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });
  afterEach(cleanup);

  it("loads existing rules on mount", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "snooze" },
    ]);
    render(<NotificationInterruptRulesCard />);
    expect(await screen.findByText(/twitter/)).toBeTruthy();
  });

  it("renders match-predicate conditions read-only", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      {
        id: "a",
        source: "whatsapp",
        match: [{ field: "chat_name", op: "contains", value: "Bride squad" }],
        action: "snooze",
      },
    ]);
    render(<NotificationInterruptRulesCard />);
    expect(await screen.findByText(/chat_name: Bride squad/)).toBeTruthy();
  });

  it("points the user to the agent to add a rule", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );
    expect(screen.getByText(/just ask bob/i)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /add rule/i })).toBeNull();
  });

  it("cycles snooze -> trash only after confirming the destructive drop", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "snooze" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    // snooze steps into trash next; stepping into trash is destructive, so it must confirm first.
    await userEvent.click(
      await screen.findByRole("button", { name: /action: snooze/i }),
    );
    // No save yet — the confirm dialog is open.
    expect(setSpy).not.toHaveBeenCalled();
    await userEvent.click(
      await screen.findByRole("button", { name: /trash them/i }),
    );
    await waitFor(() => expect(setSpy).toHaveBeenCalled());
    expect(setSpy.mock.calls.at(-1)![1][0].action).toBe("trash");
  });

  it("does not trash when the confirm is cancelled", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "snooze" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await userEvent.click(
      await screen.findByRole("button", { name: /action: snooze/i }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: /cancel/i }),
    );
    // Cancelling leaves the rule untouched and saves nothing.
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("renders a trash rule and cycles it back to interrupt", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "whatsapp", action: "trash" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await userEvent.click(
      await screen.findByRole("button", { name: /action: trash/i }),
    );
    await waitFor(() => expect(setSpy).toHaveBeenCalled());
    expect(setSpy.mock.calls.at(-1)![1][0].action).toBe("interrupt");
  });

  it("deletes a rule and auto-saves", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "snooze" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await screen.findByText(/twitter/);
    await userEvent.click(screen.getByRole("button", { name: /delete rule/i }));
    await waitFor(() => expect(setSpy).toHaveBeenCalledWith("bob", []));
  });

  it("flushes a pending debounced save on unmount", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "snooze" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    const { unmount } = render(<NotificationInterruptRulesCard />);
    await screen.findByText(/twitter/);
    await userEvent.click(screen.getByRole("button", { name: /delete rule/i }));
    unmount();
    await waitFor(() => expect(setSpy).toHaveBeenCalledWith("bob", []));
  });

  it("reorders rules by drag and persists the new order", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "snooze" },
      { id: "b", source: "whatsapp", action: "snooze" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await screen.findByText(/twitter/);

    const handles = screen.getAllByRole("button", {
      name: /drag to reorder rule/i,
    });
    const row0 = handles[0].closest("div")!;
    fireEvent.dragStart(handles[1]);
    fireEvent.dragOver(row0);
    fireEvent.drop(row0);

    await waitFor(() => expect(setSpy).toHaveBeenCalled());
    expect(
      setSpy.mock.calls.at(-1)![1].map((r: { id: string }) => r.id),
    ).toEqual(["b", "a"]);
  });

  it("rolls a rejected change back", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "snooze" },
    ]);
    vi.spyOn(api, "setNotificationInterruptRules").mockRejectedValue(
      new Error("invalid rules"),
    );
    render(<NotificationInterruptRulesCard />);
    await screen.findByText(/twitter/);
    // Delete optimistically removes it, then the save fails and it's restored.
    await userEvent.click(screen.getByRole("button", { name: /delete rule/i }));
    await screen.findByText("invalid rules");
    expect(screen.getByText(/twitter/)).toBeTruthy();
  });
});
