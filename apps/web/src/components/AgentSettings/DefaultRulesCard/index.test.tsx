import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor, cleanup } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as api from "@/api/agents";
import { DefaultRulesCard } from "./index";

vi.mock("@/providers/SelectedAgentProvider", () => ({
  useSelectedAgent: () => ({ name: "bob" }),
}));

// Controllable live arrivals (the agent socket); tests mutate liveState.arrivals to simulate a
// notification arriving without a refresh.
const { liveState } = vi.hoisted(() => ({
  liveState: { arrivals: [] as api.NotificationEvent[] },
}));
vi.mock("@/hooks/use-live-notifications", () => ({
  useLiveNotifications: () => ({
    pendingSeed: [],
    arrivals: liveState.arrivals,
    cleared: [],
    connected: true,
  }),
}));

describe("DefaultRulesCard", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    liveState.arrivals = [];
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
    expect(screen.getByText("snooze")).toBeTruthy();
    expect(screen.getByText("calendar")).toBeTruthy();
    expect(screen.getByText("interrupt")).toBeTruthy();
  });

  it("groups types under their source, named once", async () => {
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue([
      { source: "whatsapp", type: "message", interrupt: true },
      { source: "whatsapp", type: "reaction", interrupt: false },
      { source: "telegram", type: "message", interrupt: true },
    ]);
    render(<DefaultRulesCard />);
    await screen.findByText("whatsapp");
    // Few sources -> expanded by default, so the per-type rows are visible...
    expect(screen.getByText("reaction")).toBeTruthy();
    // ...and the source name appears once (a group header), not once per type.
    expect(screen.getAllByText("whatsapp")).toHaveLength(1);
    expect(screen.getByText("telegram")).toBeTruthy();
  });

  it("collapses sources when dense and expands on demand", async () => {
    // 7 sources trips the dense threshold, so groups collapse to a tally.
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue(
      Array.from({ length: 7 }, (_, i) => ({
        source: `src${i}`,
        type: "message",
        interrupt: true,
      })),
    );
    render(<DefaultRulesCard />);
    await screen.findByText("src0");
    // Collapsed: the per-type toggle rows are hidden, only the tally shows.
    expect(
      screen.queryByRole("button", { name: /default for src0 message/i }),
    ).toBeNull();
    expect(screen.getAllByText("1 interrupt").length).toBeGreaterThan(0);
    // The dense affordance appears; expand all reveals every type row.
    await userEvent.click(screen.getByRole("button", { name: /expand all/i }));
    expect(
      screen.getAllByRole("button", { name: /default for src0 message/i }),
    ).toHaveLength(1);
  });

  it("expands a single source on click when dense", async () => {
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue(
      Array.from({ length: 7 }, (_, i) => ({
        source: `src${i}`,
        type: "message",
        interrupt: true,
      })),
    );
    render(<DefaultRulesCard />);
    await screen.findByText("src3");
    expect(
      screen.queryByRole("button", { name: /default for src3 message/i }),
    ).toBeNull();
    await userEvent.click(
      screen.getByRole("button", { name: /src3,.*expand/i }),
    );
    expect(
      screen.getByRole("button", { name: /default for src3 message/i }),
    ).toBeTruthy();
  });

  it("surfaces a newly-arrived source live, without a refresh", async () => {
    // No defaults from the endpoint; the row comes only from a live arrival.
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue([]);
    liveState.arrivals = [
      {
        type: "notification",
        source: "whatsapp",
        summary: "x",
        notif_type: "message",
        interrupt: true,
        notif_id: "n1",
      },
    ];
    render(<DefaultRulesCard />);
    expect(await screen.findByText("whatsapp")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /default for whatsapp message/i }),
    ).toBeTruthy();
  });

  it("lets the newest arrival win the baseline for a (source, type)", async () => {
    // Arrivals are oldest-first; a later interrupt=false must override an earlier interrupt=true.
    vi.spyOn(api, "getNotificationStaticDefaults").mockResolvedValue([]);
    liveState.arrivals = [
      {
        type: "notification",
        source: "whatsapp",
        summary: "x",
        notif_type: "message",
        interrupt: true,
        notif_id: "old",
      },
      {
        type: "notification",
        source: "whatsapp",
        summary: "x",
        notif_type: "message",
        interrupt: false,
        notif_id: "new",
      },
    ];
    render(<DefaultRulesCard />);
    // The newest (interrupt=false) baseline wins -> shown as snooze, not interrupt.
    expect(await screen.findByText("whatsapp")).toBeTruthy();
    expect(screen.getByText("snooze")).toBeTruthy();
    expect(screen.queryByText("interrupt")).toBeNull();
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

    // snooze (static) -> interrupt: differs from the static default, so it pins an override.
    expect(setSpy).toHaveBeenCalledWith("bob", [
      { source: "twitter", type: "tweet", action: "interrupt" },
    ]);
    expect(await screen.findByText("interrupt")).toBeTruthy();
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

    // The override makes the effective disposition interrupt; wait for it to load.
    await userEvent.click(
      await screen.findByRole("button", { name: /default for twitter/i }),
    );

    // interrupt (override) -> snooze equals the static default, so the override is removed.
    expect(setSpy).toHaveBeenCalledWith("bob", []);
    await waitFor(() => expect(screen.getByText("snooze")).toBeTruthy());
  });
});
