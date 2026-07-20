import { useContext, useEffect } from "react";
import { act, render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Controller } from "@vesta/core";
import { ControllerProvider } from "./index";
import { ControllerContext } from "./context";

const mockConn = vi.hoisted(() => ({ tokenExpiring: false }));

vi.mock("@/lib/connection", () => ({
  getConnection: () => ({
    url: "https://vestad.test",
    accessToken: "tok",
    refreshToken: "ref",
    expiresAt: Date.now() + 60_000,
  }),
  isTokenExpiringSoon: () => mockConn.tokenExpiring,
  connectionHostname: () => "vestad.test",
}));

// Mirrors REAUTH_POLL_MS in index.tsx (not exported).
const REAUTH_POLL_MS = 60_000;

vi.mock("@/lib/token-refresh", () => ({
  ensureFreshToken: () => Promise.resolve("ok"),
}));

vi.mock("@/providers/AuthProvider", () => ({
  useAuth: () => ({
    initialized: true,
    connected: true,
    loading: false,
    expireSession: vi.fn(),
    disconnect: vi.fn(),
  }),
}));

// The screens are their own tested units pulling in the navbar / router; here we only assert
// ControllerProvider's choice to render them, so stub them to markers.
vi.mock("@/components/IncompatibleScreen", () => ({
  IncompatibleScreen: () => <div>incompatible</div>,
}));
vi.mock("@/components/DisconnectedOverlay", () => ({
  DisconnectedOverlay: () => <div>disconnected</div>,
}));

// A fake WebSocket capturing constructions and letting the test drive the frame callbacks
// that core's browser-socket adapter wires up (onopen / onmessage / onclose).
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  readonly sent: string[] = [];
  readonly url: string;
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    this.onclose?.();
  }
}

// Reads the controller from context (null during the pre-connect gate, set once the
// controller is built), so mounting the probe never throws before the gate resolves.
function Probe({ onReady }: { onReady: (controller: Controller) => void }) {
  const controller = useContext(ControllerContext);
  useEffect(() => {
    if (controller) onReady(controller);
  }, [controller, onReady]);
  return null;
}

const helloFrame = JSON.stringify({
  type: "hello",
  version: "0.2.0",
  protocol: 1,
  floor: 1,
});
// floor 2 sits above the client's supported protocol (1), so the handshake is incompatible.
const incompatibleHelloFrame = JSON.stringify({
  type: "hello",
  version: "9.9.9",
  protocol: 2,
  floor: 2,
});
const snapshotFrame = JSON.stringify({
  type: "snapshot",
  tree: { gateway: { version: "9.9.9" }, agents: {} },
});

beforeEach(() => {
  FakeWebSocket.instances = [];
  mockConn.tokenExpiring = false;
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ControllerProvider", () => {
  it("takes over with IncompatibleScreen when the handshake floor is incompatible", async () => {
    const { findByText } = render(
      <ControllerProvider>
        <div>app body</div>
      </ControllerProvider>,
    );

    await waitFor(() => {
      expect(FakeWebSocket.instances).toHaveLength(1);
    });
    const socket = FakeWebSocket.instances[0];
    if (!socket) throw new Error("socket not constructed");

    act(() => {
      socket.onopen?.();
      socket.onmessage?.({ data: incompatibleHelloFrame });
    });

    expect(await findByText("incompatible")).toBeTruthy();
  });

  it("builds the controller and reduces hello+snapshot into the replica", async () => {
    let controller: Controller | null = null;

    render(
      <ControllerProvider>
        <Probe
          onReady={(c) => {
            controller = c;
          }}
        />
      </ControllerProvider>,
    );

    await waitFor(() => {
      expect(FakeWebSocket.instances).toHaveLength(1);
    });
    const socket = FakeWebSocket.instances[0];
    if (!socket) throw new Error("socket not constructed");

    act(() => {
      socket.onopen?.();
      socket.onmessage?.({ data: helloFrame });
      socket.onmessage?.({ data: snapshotFrame });
    });

    await waitFor(() => {
      expect(controller?.replica.getState()?.gateway.version).toBe("9.9.9");
    });
  });

  it("rotates the token in-band when it is expiring", async () => {
    mockConn.tokenExpiring = true;
    vi.useFakeTimers();
    try {
      render(
        <ControllerProvider>
          <div>app body</div>
        </ControllerProvider>,
      );
      // Let the controller-build effect run so the socket exists.
      await act(async () => {
        await vi.advanceTimersByTimeAsync(1);
      });
      const socket = FakeWebSocket.instances[0];
      if (!socket) throw new Error("socket not constructed");
      act(() => {
        socket.onopen?.();
      });

      await act(async () => {
        await vi.advanceTimersByTimeAsync(REAUTH_POLL_MS);
      });

      expect(
        socket.sent.some(
          (frame) => (JSON.parse(frame) as { type: string }).type === "reauth",
        ),
      ).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes the controller socket on unmount", async () => {
    const { unmount } = render(
      <ControllerProvider>
        <div>app body</div>
      </ControllerProvider>,
    );

    await waitFor(() => {
      expect(FakeWebSocket.instances).toHaveLength(1);
    });
    const socket = FakeWebSocket.instances[0];
    if (!socket) throw new Error("socket not constructed");

    unmount();
    expect(socket.closed).toBe(true);
  });
});
