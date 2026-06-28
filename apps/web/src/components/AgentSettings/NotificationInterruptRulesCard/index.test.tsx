import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createRef } from "react";
import * as api from "@/api/agents";
import {
  NotificationInterruptRulesCard,
  type NotificationInterruptRulesHandle,
} from "./index";

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
}));

describe("NotificationInterruptRulesCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    // The card fetches recent notifications for suggestions; default to none unless a test overrides.
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [],
      cursor: null,
    });
  });
  afterEach(cleanup);

  it("loads existing rules on mount", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "pool" },
    ]);
    render(<NotificationInterruptRulesCard />);
    // active rules render condition badges like "source: twitter"
    expect(await screen.findByText(/twitter/)).toBeTruthy();
  });

  it("adds a rule by selecting a suggested source", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "twitter",
          summary: "x",
          notif_type: "tweet",
        },
      ],
      cursor: null,
    });
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([
        { id: "new", source: "twitter", action: "interrupt" },
      ]);
    render(<NotificationInterruptRulesCard />);
    await waitFor(() => expect(api.getNotificationHistory).toHaveBeenCalled());

    // The combobox is select-only: open it and pick a suggested value (selecting closes it).
    await userEvent.type(screen.getByLabelText("source"), "t");
    await userEvent.click(
      await screen.findByRole("option", { name: "twitter" }),
    );
    await userEvent.click(screen.getByRole("button", { name: /add rule/i }));

    await waitFor(() => expect(setSpy).toHaveBeenCalledTimes(1));
    const [, rulesArg] = setSpy.mock.calls[0];
    expect(rulesArg).toHaveLength(1);
    expect(rulesArg[0].source).toBe("twitter");
    expect(rulesArg[0].action).toBe("interrupt");
  });

  it("won't add a rule with no conditions", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );
    const addButton = screen.getByRole("button", {
      name: /add rule/i,
    }) as HTMLButtonElement;
    expect(addButton.disabled).toBe(true);
  });

  it("blocks an invalid keyword regex and accepts a valid one", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );
    const addButton = screen.getByRole("button", {
      name: /add rule/i,
    }) as HTMLButtonElement;

    await userEvent.type(screen.getByLabelText("keyword"), "(unclosed");
    expect(screen.getByText(/invalid keyword regex/i)).toBeTruthy();
    expect(addButton.disabled).toBe(true);

    // Completing the group makes it a valid regex; the error clears and add re-enables.
    await userEvent.type(screen.getByLabelText("keyword"), ")");
    expect(screen.queryByText(/invalid keyword regex/i)).toBeNull();
    expect(addButton.disabled).toBe(false);
  });

  it("deletes a rule and auto-saves", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([
      { id: "a", source: "twitter", action: "pool" },
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
      { id: "a", source: "twitter", action: "pool" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    const { unmount } = render(<NotificationInterruptRulesCard />);
    await screen.findByText(/twitter/);

    // Edit, then unmount within the debounce window (e.g. switching settings tabs). The save must
    // still fire on unmount rather than being silently dropped.
    await userEvent.click(screen.getByRole("button", { name: /delete rule/i }));
    unmount();

    await waitFor(() => expect(setSpy).toHaveBeenCalledWith("bob", []));
  });

  it("offers source/type/sender suggestions from recent notifications", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "twitter",
          summary: "x",
          notif_type: "tweet",
          sender: "@bob",
        },
        {
          type: "notification",
          source: "whatsapp",
          summary: "x",
          notif_type: "message",
          sender: "Alice",
        },
      ],
      cursor: null,
    });
    render(<NotificationInterruptRulesCard />);
    await waitFor(() => expect(api.getNotificationHistory).toHaveBeenCalled());

    // Typing into the source combobox opens it and surfaces values seen in recent notifications.
    await userEvent.type(screen.getByLabelText("source"), "t");
    expect(await screen.findByRole("option", { name: "twitter" })).toBeTruthy();
  });
});

describe("NotificationInterruptRulesCard handle", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [],
      cursor: null,
    });
  });
  afterEach(cleanup);

  it("seeds a pooled rule from a notification via addFromNotification", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    const ref = createRef<NotificationInterruptRulesHandle>();
    render(<NotificationInterruptRulesCard ref={ref} />);
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );

    act(() =>
      ref.current?.addFromNotification({ source: "twitter", type: "tweet" }),
    );

    await waitFor(() => expect(setSpy).toHaveBeenCalledTimes(1));
    const [, rulesArg] = setSpy.mock.calls[0];
    expect(rulesArg[0]).toMatchObject({
      source: "twitter",
      type: "tweet",
      action: "pool",
    });
  });

  it("ignores addFromNotification fired before the ruleset has loaded", async () => {
    // The sibling card's make-rule button can fire before this card's own fetch resolves. If we
    // committed against the unloaded (null) ruleset, the debounced save would overwrite the user's
    // existing rules with just the new one — silent data loss. Guard: it must be a no-op while loading.
    let resolveRules: (
      rules: { id: string; source: string; action: string }[],
    ) => void = () => {};
    vi.spyOn(api, "getNotificationInterruptRules").mockReturnValue(
      new Promise((resolve) => {
        resolveRules = resolve;
      }),
    );
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    const ref = createRef<NotificationInterruptRulesHandle>();
    const { unmount } = render(<NotificationInterruptRulesCard ref={ref} />);

    // Fire the seed while the fetch is still pending (rules === null).
    act(() => ref.current?.addFromNotification({ source: "twitter" }));

    // The fetch resolves with the user's existing rule.
    await act(async () => {
      resolveRules([{ id: "x", source: "email", action: "interrupt" }]);
    });
    // Unmount flushes any pending debounced save; none should exist, so the server is never written.
    unmount();
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );
    expect(setSpy).not.toHaveBeenCalled();
  });
});

describe("NotificationInterruptRulesCard core protection", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(cleanup);

  it("excludes core from the source suggestions", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "core",
          summary: "x",
          notif_type: "default_skill_sync",
        },
        {
          type: "notification",
          source: "twitter",
          summary: "x",
          notif_type: "tweet",
        },
      ],
      cursor: null,
    });
    render(<NotificationInterruptRulesCard />);
    await waitFor(() => expect(api.getNotificationHistory).toHaveBeenCalled());

    // "r" matches both "twitter" and "core", but core is filtered out of the suggestions.
    await userEvent.type(screen.getByLabelText("source"), "r");
    expect(await screen.findByRole("option", { name: "twitter" })).toBeTruthy();
    expect(screen.queryByRole("option", { name: "core" })).toBeNull();
  });

  it("refuses to seed a rule from a core notification", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [],
      cursor: null,
    });
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    const ref = createRef<NotificationInterruptRulesHandle>();
    render(<NotificationInterruptRulesCard ref={ref} />);
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );

    act(() =>
      ref.current?.addFromNotification({
        source: "core",
        type: "default_skill_sync",
      }),
    );

    // No optimistic rule, no save — core can't be targeted.
    expect(screen.queryByText(/core/)).toBeNull();
    await new Promise((r) => setTimeout(r, 350));
    expect(setSpy).not.toHaveBeenCalled();
  });

  it("rolls a rejected rule back out of the list", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [],
      cursor: null,
    });
    vi.spyOn(api, "setNotificationInterruptRules").mockRejectedValue(
      new Error("invalid rules"),
    );
    const ref = createRef<NotificationInterruptRulesHandle>();
    render(<NotificationInterruptRulesCard ref={ref} />);
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );

    act(() =>
      ref.current?.addFromNotification({ source: "twitter", type: "tweet" }),
    );

    // Optimistically shown, then the save fails and the rule is rolled back.
    expect(await screen.findByText(/twitter/)).toBeTruthy();
    await screen.findByText("invalid rules");
    await waitFor(() => expect(screen.queryByText(/twitter/)).toBeNull());
  });
});

describe("NotificationInterruptRulesCard cascade", () => {
  beforeEach(() => vi.restoreAllMocks());
  afterEach(cleanup);

  it("can add a rule from keyword alone", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [],
      cursor: null,
    });
    const setSpy = vi
      .spyOn(api, "setNotificationInterruptRules")
      .mockResolvedValue([]);
    render(<NotificationInterruptRulesCard />);
    await waitFor(() =>
      expect(api.getNotificationInterruptRules).toHaveBeenCalled(),
    );

    await userEvent.type(screen.getByLabelText("keyword"), "urgent");
    await userEvent.click(screen.getByRole("button", { name: /add rule/i }));

    await waitFor(() => expect(setSpy).toHaveBeenCalledTimes(1));
    const [, rulesArg] = setSpy.mock.calls[0];
    expect(rulesArg[0].keyword).toBe("urgent");
    expect(rulesArg[0].source).toBeUndefined();
  });

  it("disables type until a source is picked", async () => {
    vi.spyOn(api, "getNotificationInterruptRules").mockResolvedValue([]);
    vi.spyOn(api, "getNotificationHistory").mockResolvedValue({
      notifications: [
        {
          type: "notification",
          source: "twitter",
          summary: "x",
          notif_type: "tweet",
        },
      ],
      cursor: null,
    });
    render(<NotificationInterruptRulesCard />);
    await waitFor(() => expect(api.getNotificationHistory).toHaveBeenCalled());

    expect((screen.getByLabelText("type") as HTMLInputElement).disabled).toBe(
      true,
    );
    await userEvent.type(screen.getByLabelText("source"), "t");
    await userEvent.click(
      await screen.findByRole("option", { name: "twitter" }),
    );
    expect((screen.getByLabelText("type") as HTMLInputElement).disabled).toBe(
      false,
    );
  });
});
