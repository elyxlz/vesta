import { StrictMode, useContext, useEffect } from "react";
import { act, cleanup, render, waitFor } from "@testing-library/react";
import {
  afterAll,
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import type { Controller } from "@vesta/core";
import { ControllerProvider, REAUTH_POLL_MS } from "./index";
import { ControllerContext, useControllerReconnect } from "./context";

const mockConn = vi.hoisted(() => ({ tokenExpiring: false }));
const refresh = vi.hoisted(() => ({
  result: (): Promise<"ok" | "transient"> => Promise.resolve("ok"),
}));

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

vi.mock("@/lib/token-refresh", () => ({
  ensureFreshToken: () => refresh.result(),
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

vi.mock("@/components/DisconnectedOverlay", () => ({
  DisconnectedOverlay: () => <div data-testid="disconnected" />,
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

// Reads the controller and the reconnect handle from context (null during the pre-connect gate),
// so mounting the probe never throws before the gate resolves.
function Probe({
  onReady,
}: {
  onReady: (controller: Controller, reconnect: () => void) => void;
}) {
  const controller = useContext(ControllerContext);
  const reconnect = useControllerReconnect();
  useEffect(() => {
    if (controller) onReady(controller, reconnect);
  }, [controller, reconnect, onReady]);
  return <div data-testid="app-body" />;
}

// A window containing the client (__CLIENT_VERSION__), so the socket proceeds to "open".
const openHelloFrame = JSON.stringify({
  type: "hello",
  version: "9.9.9",
  min_supported: "0.0.0",
});

function latestSocket(): FakeWebSocket {
  const socket = FakeWebSocket.instances.at(-1);
  if (!socket) throw new Error("socket not constructed");
  return socket;
}

function openSocket(socket: FakeWebSocket): void {
  act(() => {
    socket.onopen?.();
    socket.onmessage?.({ data: openHelloFrame });
  });
}

function sentReauth(socket: FakeWebSocket): boolean {
  return socket.sent.some(
    (frame) => (JSON.parse(frame) as { type: string }).type === "reauth",
  );
}

// Far past the disconnect grace, without mirroring the constant: the overlay decision is "a blip
// shows nothing, an outage shows it", not the exact millisecond.
const WELL_PAST_GRACE_MS = 5_000;

beforeEach(() => {
  FakeWebSocket.instances = [];
  mockConn.tokenExpiring = false;
  refresh.result = () => Promise.resolve("ok");
  vi.stubGlobal("WebSocket", FakeWebSocket);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

afterAll(() => {
  vi.unstubAllGlobals();
});

describe("ControllerProvider", () => {
  // A restored session whose token is expiring rotates it in-band twice: once on mount (the frame
  // rides the still-in-flight handshake) and again on the poll interval, never waiting out a poll to
  // start.
  it("rotates an expiring token on mount and again on the poll interval", async () => {
    mockConn.tokenExpiring = true;
    vi.useFakeTimers();
    render(
      <ControllerProvider>
        <div>app body</div>
      </ControllerProvider>,
    );
    // Run the build + mount-refresh effects so the socket exists and a reauth is pending.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const socket = latestSocket();
    // The pending mount reauth rides the handshake the moment it opens, before any interval.
    await act(async () => {
      socket.onopen?.();
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(sentReauth(socket)).toBe(true);
    const afterMount = socket.sent.length;

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REAUTH_POLL_MS);
    });

    expect(socket.sent.length).toBeGreaterThan(afterMount);
  });

  // A refresh that cannot complete is a no-op: the socket is never torn down to rotate a token.
  it("keeps the socket when the reauth refresh cannot complete", async () => {
    mockConn.tokenExpiring = true;
    refresh.result = () => Promise.resolve("transient");
    vi.useFakeTimers();
    render(
      <ControllerProvider>
        <div>app body</div>
      </ControllerProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const socket = latestSocket();
    await act(async () => {
      socket.onopen?.();
      await vi.advanceTimersByTimeAsync(REAUTH_POLL_MS);
    });

    expect(sentReauth(socket)).toBe(false);
    expect(socket.closed).toBe(false);
  });

  // The overlay waits out a grace window so a socket blip never flashes it, while a real outage
  // still surfaces once the window elapses.
  it.each([
    { name: "a blip that opens inside the grace shows nothing", opens: true },
    { name: "an outage past the grace shows the overlay", opens: false },
  ])("$name", async ({ opens }) => {
    vi.useFakeTimers();
    const { queryByTestId } = render(
      <ControllerProvider>
        <div>app body</div>
      </ControllerProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(queryByTestId("disconnected")).toBeNull();
    if (opens) openSocket(latestSocket());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(WELL_PAST_GRACE_MS);
    });

    expect(queryByTestId("disconnected") !== null).toBe(!opens);
  });

  // The gateway-update path re-attaches by asking for a reconnect: the old socket closes and a
  // fresh controller opens a new one.
  it("reconnect() closes the live socket and builds a fresh controller", async () => {
    const seen: Controller[] = [];
    const handles: (() => void)[] = [];
    render(
      <ControllerProvider>
        <Probe
          onReady={(controller, handle) => {
            seen.push(controller);
            handles.push(handle);
          }}
        />
      </ControllerProvider>,
    );
    await waitFor(() => {
      expect(FakeWebSocket.instances).toHaveLength(1);
    });
    const first = latestSocket();
    openSocket(first);
    const reconnect = handles[0];
    if (!reconnect) throw new Error("reconnect handle not captured");

    act(() => {
      reconnect();
    });

    await waitFor(() => {
      expect(FakeWebSocket.instances).toHaveLength(2);
    });
    expect(first.closed).toBe(true);
    expect(seen).toHaveLength(2);
    expect(seen[0]).not.toBe(seen[1]);
  });

  // StrictMode's double effect pass (setup, cleanup, setup with preserved state) is the same
  // sequence React Fast Refresh runs on a hot update, so this pins the dev-mode bug where a
  // hot reload closed the state-held controller for good and /sync never reconnected.
  it("keeps a live controller across an effect remount (StrictMode / Fast Refresh)", async () => {
    let controller: Controller | null = null;

    render(
      <StrictMode>
        <ControllerProvider>
          <Probe
            onReady={(c) => {
              controller = c;
            }}
          />
        </ControllerProvider>
      </StrictMode>,
    );

    await waitFor(() => {
      expect(FakeWebSocket.instances.length).toBeGreaterThan(0);
    });
    openSocket(latestSocket());

    await waitFor(() => {
      expect(controller?.getSyncState()).toBe("open");
    });
  });
});
