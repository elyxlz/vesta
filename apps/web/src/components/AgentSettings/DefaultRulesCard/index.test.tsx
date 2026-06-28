import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as api from "@/api/agents";
import { DefaultRulesCard } from "./index";

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
}));

describe("DefaultRulesCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(api, "getNotificationDefaultOverrides").mockResolvedValue([]);
  });
  afterEach(cleanup);

  it("renders the default per source/type from the aggregated endpoint", async () => {
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue([
      { source: "twitter", type: "tweet", interrupt: false },
      { source: "calendar", type: "reminder", interrupt: true },
    ]);
    render(<DefaultRulesCard />);

    expect(await screen.findByText("twitter")).toBeTruthy();
    expect(screen.getByText("snoozes")).toBeTruthy();
    expect(screen.getByText("calendar")).toBeTruthy();
    expect(screen.getByText("interrupts")).toBeTruthy();
  });

  it("shows a placeholder when there are no defaults yet", async () => {
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue([]);
    render(<DefaultRulesCard />);
    expect(await screen.findByText(/defaults appear here/i)).toBeTruthy();
  });

  it("toggling a default writes an override", async () => {
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue([
      { source: "twitter", type: "tweet", interrupt: false },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationDefaultOverrides")
      .mockResolvedValue([]);
    render(<DefaultRulesCard />);

    await userEvent.click(
      await screen.findByRole("button", { name: /default for twitter/i }),
    );

    // snoozes (static) -> interrupts: differs from the static default, so it pins an override.
    expect(setSpy).toHaveBeenCalledWith("bob", [
      { source: "twitter", type: "tweet", action: "interrupt" },
    ]);
    expect(await screen.findByText("by you")).toBeTruthy();
    expect(screen.getByText("interrupts")).toBeTruthy();
  });

  it("toggling an override back to the source default clears it (inherit)", async () => {
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue([
      { source: "twitter", type: "tweet", interrupt: false },
    ]);
    vi.spyOn(api, "getNotificationDefaultOverrides").mockResolvedValue([
      { source: "twitter", type: "tweet", action: "interrupt" },
    ]);
    const setSpy = vi
      .spyOn(api, "setNotificationDefaultOverrides")
      .mockResolvedValue([]);
    render(<DefaultRulesCard />);

    expect(await screen.findByText("by you")).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: /default for twitter/i }),
    );

    // interrupts (override) -> snoozes equals the static default, so the override is removed.
    expect(setSpy).toHaveBeenCalledWith("bob", []);
    await waitFor(() => expect(screen.queryByText("by you")).toBeNull());
  });
});
