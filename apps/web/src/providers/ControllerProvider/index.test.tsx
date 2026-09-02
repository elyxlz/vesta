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
import { REAUTH_POLL_MS, TOKEN_REFRESH_BUFFER_MS } from "@vesta/core";
import type { Controller } from "@vesta/core";
import { restoreConnection } from "@/lib/connection";
import { ControllerProvider } from "./index";
import { ControllerContext, useControllerReconnect } from "./context";

vi.mock("@/providers/AuthProvider/context", () => ({
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

// A fake WebSocket capturing constructions and letting the test drive the events core's
// adaptWebSocket wires up (onopen / onmessage / onclose).
class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: ((event: { reason: string }) => void) | null = null;
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
    this.onclose?.({ reason: "" });
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

function reauthTokens(socket: FakeWebSocket): string[] {
  return socket.sent
    .map((frame) => JSON.parse(frame) as { type: string; token?: string })
    .filter((frame) => frame.type === "reauth")
    .map((frame) => frame.token ?? "");
}

// Far past the disconnect grace, without mirroring the constant: the overlay decision is "a blip
// shows nothing, an outage shows it", not the exact millisecond.
const WELL_PAST_GRACE_MS = 5_000;
// A short-lived grant, so the poll after the mount refresh finds the token expiring again.
const SHORT_GRANT_SECS = REAUTH_POLL_MS / 1000;

const refreshAnswer = { ok: true as boolean };
let refreshes = 0;
const fetchStub = vi.fn((input: string): Promise<Response> => {
  if (input.endsWith("/auth/refresh")) {
    refreshes += 1;
    if (!refreshAnswer.ok) return Promise.reject(new TypeError("offline"));
    return Promise.resolve(
      new Response(
        JSON.stringify({
          access_token: `next-${String(refreshes)}`,
          refresh_token: "ref",
          expires_in: SHORT_GRANT_SECS,
        }),
        { status: 200 },
      ),
    );
  }
  return Promise.resolve(new Response("{}", { status: 200 }));
});

function storeConnection(expiring: boolean): void {
  restoreConnection({
    url: "https://vestad.test",
    accessToken: "tok",
    refreshToken: "ref",
    expiresAt: expiring
      ? Date.now() + TOKEN_REFRESH_BUFFER_MS - 1
      : Date.now() + 60 * 60 * 1000,
  });
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  refreshAnswer.ok = true;
  refreshes = 0;
  vi.stubGlobal("WebSocket", FakeWebSocket);
  vi.stubGlobal("fetch", fetchStub);
  storeConnection(false);
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

afterAll(() => {
  vi.unstubAllGlobals();
});

describe("ControllerProvider", () => {
  // A restored session whose token is expiring refreshes before the first dial (the URL carries
  // the fresh token) and rotates again in-band on the poll interval once the short grant nears
  // its own expiry, never tearing the socket down to do it.
  it("refreshes an expiring token before dialing and rotates in-band on the poll interval", async () => {
    vi.useFakeTimers();
    storeConnection(true);
    render(
      <ControllerProvider>
        <div>app body</div>
      </ControllerProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const socket = latestSocket();
    expect(socket.url).toContain("token=next-1");
    openSocket(socket);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(REAUTH_POLL_MS + 1);
    });

    expect(reauthTokens(socket)).toContain("next-2");
    expect(socket.closed).toBe(false);
  });

  // A refresh that cannot complete is a no-op: the socket dials with the token it has and is
  // never torn down to rotate one.
  it("keeps the socket when the reauth refresh cannot complete", async () => {
    vi.useFakeTimers();
    storeConnection(true);
    refreshAnswer.ok = false;
    render(
      <ControllerProvider>
        <div>app body</div>
      </ControllerProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    const socket = latestSocket();
    expect(socket.url).toContain("token=tok");
    await act(async () => {
      socket.onopen?.();
      await vi.advanceTimersByTimeAsync(REAUTH_POLL_MS);
    });

    expect(reauthTokens(socket)).toEqual([]);
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
