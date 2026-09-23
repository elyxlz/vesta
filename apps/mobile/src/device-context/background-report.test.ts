import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ConnectionConfig } from "@vesta/core";
import {
  BACKGROUND_REPORT_MIN_DISTANCE_M,
  DEVICE_CONTEXT_TASK,
  reportDeviceContextInBackground,
  syncBackgroundReport,
} from "./background-report";

const state = vi.hoisted(() => ({
  connection: null as ConnectionConfig | null,
  preferences: null as string | null,
  context: {} as Record<string, unknown>,
  defined: [] as string[],
  backgroundGranted: true,
  started: false,
  calls: [] as { call: string; options?: unknown }[],
  written: [] as ConnectionConfig[],
}));
vi.mock("expo-location", () => ({
  Accuracy: { Balanced: 3 },
  getBackgroundPermissionsAsync: () =>
    Promise.resolve({ granted: state.backgroundGranted }),
  startLocationUpdatesAsync: (name: string, options: unknown) => {
    state.calls.push({ call: `start:${name}`, options });
    return Promise.resolve();
  },
  hasStartedLocationUpdatesAsync: () => Promise.resolve(state.started),
  stopLocationUpdatesAsync: (name: string) => {
    state.calls.push({ call: `stop:${name}` });
    return Promise.resolve();
  },
}));
vi.mock("expo-task-manager", () => ({
  defineTask: (name: string) => {
    state.defined.push(name);
  },
}));
vi.mock("@react-native-async-storage/async-storage", () => ({
  default: { getItem: () => Promise.resolve(state.preferences) },
}));
vi.mock("@/storage/connection", () => ({
  readConnection: () => Promise.resolve(state.connection),
  writeConnection: (next: ConnectionConfig) => {
    state.written.push(next);
    return Promise.resolve();
  },
}));
vi.mock("@/controller/device-identity", () => ({
  deviceIdentity: () =>
    Promise.resolve({ id: "install-1", descriptor: "Vesta Mobile on iOS" }),
}));
vi.mock("./device-context", () => ({
  readDeviceContext: () => Promise.resolve(state.context),
}));

const connection: ConnectionConfig = {
  url: "https://gateway.example",
  accessToken: "access-token",
  refreshToken: "refresh-token",
  expiresAt: Date.now() + 60 * 60 * 1000,
  hosted: false,
};

describe("reportDeviceContextInBackground", () => {
  const fetchMock = vi.fn();
  beforeEach(() => {
    state.connection = connection;
    state.preferences = null;
    state.context = { timezone: "Asia/Tokyo" };
    state.written = [];
    fetchMock.mockReset();
    fetchMock.mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("defines the task at import so a headless launch finds it", () => {
    expect(state.defined).toEqual([DEVICE_CONTEXT_TASK]);
  });

  it("PUTs the device context to the gateway with the stored session", async () => {
    await reportDeviceContextInBackground();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://gateway.example/devices/install-1/context");
    expect(init.method).toBe("PUT");
    expect(new Headers(init.headers).get("authorization")).toBe(
      "Bearer access-token",
    );
    expect(JSON.parse(init.body as string)).toEqual({ timezone: "Asia/Tokyo" });
  });

  it("does nothing without a stored session or with nothing to report", async () => {
    state.connection = null;
    await reportDeviceContextInBackground();
    state.connection = connection;
    state.context = {};
    await reportDeviceContextInBackground();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("refreshes an expiring session, writes the rotated tokens, and reports with them", async () => {
    state.connection = { ...connection, expiresAt: Date.now() + 60 * 1000 };
    fetchMock.mockImplementation((url: string) =>
      Promise.resolve(
        url.endsWith("/auth/refresh")
          ? new Response(
              JSON.stringify({
                access_token: "rotated-access",
                refresh_token: "rotated-refresh",
                expires_in: 3600,
              }),
              { status: 200 },
            )
          : new Response("{}", { status: 200 }),
      ),
    );
    await reportDeviceContextInBackground();
    const urls = fetchMock.mock.calls.map((call) => call[0] as string);
    expect(urls).toEqual([
      "https://gateway.example/auth/refresh",
      "https://gateway.example/devices/install-1/context",
    ]);
    const put = fetchMock.mock.calls[1]?.[1] as RequestInit;
    expect(new Headers(put.headers).get("authorization")).toBe(
      "Bearer rotated-access",
    );
    expect(state.written.map((written) => written.refreshToken)).toEqual([
      "rotated-refresh",
    ]);
  });
});

describe("syncBackgroundReport", () => {
  beforeEach(() => {
    state.calls = [];
    state.backgroundGranted = true;
    state.started = false;
  });

  it("starts significant-change updates when sharing is on and location is allowed always", async () => {
    await syncBackgroundReport(true);
    expect(state.calls).toEqual([
      {
        call: `start:${DEVICE_CONTEXT_TASK}`,
        options: {
          accuracy: 3,
          distanceInterval: BACKGROUND_REPORT_MIN_DISTANCE_M,
          significantChangesOnly: true,
        },
      },
    ]);
  });

  it("stops a started task when sharing turns off or the always-on grant is gone", async () => {
    state.started = true;
    await syncBackgroundReport(false);
    state.backgroundGranted = false;
    await syncBackgroundReport(true);
    expect(state.calls).toEqual([
      { call: `stop:${DEVICE_CONTEXT_TASK}` },
      { call: `stop:${DEVICE_CONTEXT_TASK}` },
    ]);
  });

  it("does nothing when no task runs and none should", async () => {
    await syncBackgroundReport(false);
    expect(state.calls).toEqual([]);
  });
});
