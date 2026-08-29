import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useSwitchGateway } from "@/stores/use-switch-gateway";
import { SwitchGatewayDialog } from "./index";

const { auth, connectSavedGateway, navigate } = vi.hoisted(() => {
  const connectSavedGateway = vi.fn();
  return {
    connectSavedGateway,
    navigate: vi.fn(),
    auth: { connected: false, connectSavedGateway },
  };
});

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => auth,
}));

vi.mock("@/router", () => ({
  router: { navigate },
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

describe("SwitchGatewayDialog while disconnected", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem(
      "vesta-recent-gateways",
      JSON.stringify([SAVED_GATEWAY]),
    );
    useSwitchGateway.setState({ open: true });
  });

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    useSwitchGateway.setState({ open: false });
  });

  it("restores a saved gateway and enters the connected app", async () => {
    render(<SwitchGatewayDialog />);

    expect(
      await screen.findByRole("heading", { name: "recent gateways" }),
    ).toBeTruthy();
    await userEvent.click(
      screen.getByRole("button", { name: "connect to a.example" }),
    );

    expect(connectSavedGateway).toHaveBeenCalledWith(SAVED_GATEWAY.connection);
    expect(navigate).toHaveBeenCalledWith("/");
    expect(useSwitchGateway.getState().open).toBe(false);
  });
});
