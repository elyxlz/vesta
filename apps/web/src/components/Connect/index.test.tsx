import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSwitchGateway } from "@/stores/use-switch-gateway";
import { Connect } from "./index";

const { auth } = vi.hoisted(() => ({
  auth: {
    connected: false,
    sessionExpired: false,
    connect: vi.fn(),
  },
}));

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => auth,
}));

vi.mock("@/providers/RuntimeProvider", () => ({
  useRuntime: () => ({ isDesktopApp: false }),
}));

const SAVED_GATEWAY = {
  id: "gateway-a",
  url: "https://a.example",
  hosted: false,
  lastConnectedAt: 1,
  connection: {
    url: "https://a.example",
    accessToken: "access-token",
    refreshToken: "refresh-token",
    expiresAt: 4_102_444_800_000,
  },
};

describe("Connect recent gateways", () => {
  beforeEach(() => {
    localStorage.clear();
    useSwitchGateway.setState({ open: false });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("opens the recent gateway picker when a saved gateway exists", async () => {
    localStorage.setItem(
      "vesta-recent-gateways",
      JSON.stringify([SAVED_GATEWAY]),
    );

    render(<Connect />);

    const trigger = await screen.findByRole("button", {
      name: "recent gateways",
    });
    await userEvent.click(trigger);

    expect(useSwitchGateway.getState().open).toBe(true);
  });

  it("hides the picker when there are no saved gateways", async () => {
    render(<Connect />);

    await waitFor(() => {
      expect(
        screen.queryByRole("button", { name: "recent gateways" }),
      ).toBeNull();
    });
  });
});
